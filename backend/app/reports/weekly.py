"""Weekly meetings report calculation and CSV generation."""

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Meeting, User

ISO_WEEK_REGEX = re.compile(r"^(\d{4})-W(0[1-9]|[1-4]\d|5[0-3])$")


def parse_iso_week(week: str) -> tuple[datetime, datetime]:
    """Parse an ISO week string (e.g. '2026-W40') into UTC start and end datetimes.

    Start: Monday 00:00:00.000000 UTC
    End:   Sunday 23:59:59.999999 UTC
    """
    match = ISO_WEEK_REGEX.match(week.strip())
    if not match:
        raise ValueError(
            f"Invalid ISO week format '{week}'. Expected format 'YYYY-Www', e.g. '2026-W40'."
        )
    year = int(match.group(1))
    week_num = int(match.group(2))
    monday = date.fromisocalendar(year, week_num, 1)
    sunday = date.fromisocalendar(year, week_num, 7)
    start_dt = datetime.combine(monday, time.min, tzinfo=UTC)
    end_dt = datetime.combine(sunday, time.max, tzinfo=UTC)
    return start_dt, end_dt


def get_previous_iso_week(week: str) -> str:
    """Return the ISO week string for the week preceding the given week."""
    start_dt, _ = parse_iso_week(week)
    prev_monday = start_dt.date() - timedelta(days=7)
    iso_year, iso_week_num, _ = prev_monday.isocalendar()
    return f"{iso_year}-W{iso_week_num:02d}"


async def get_meetings_for_range(
    session: AsyncSession, start_dt: datetime, end_dt: datetime
) -> list[Meeting]:
    """Fetch meetings whose start time falls within the given range."""
    stmt = (
        select(Meeting)
        .options(selectinload(Meeting.participants))
        .where(Meeting.starts_at >= start_dt, Meeting.starts_at <= end_dt)
        .order_by(Meeting.starts_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def build_weekly_report(week: str, session: AsyncSession) -> bytes:
    """Query the meetings of one ISO week (e.g. '2026-W40') and return the CSV bytes.

    Contains:
    1. Overall summary: meetings count & duration for the week vs previous week, plus changes.
    2. Five longest meetings: title, start, duration (hours), and number of participants.
    3. Breakdown of meetings and duration per organizer.
    """
    start_dt, end_dt = parse_iso_week(week)
    prev_week = get_previous_iso_week(week)
    prev_start_dt, prev_end_dt = parse_iso_week(prev_week)

    # Query current week and previous week
    current_meetings = await get_meetings_for_range(session, start_dt, end_dt)
    prev_meetings = await get_meetings_for_range(session, prev_start_dt, prev_end_dt)

    # 1. Metric totals
    curr_count = len(current_meetings)
    curr_duration_hours = sum(
        (m.ends_at - m.starts_at).total_seconds() / 3600.0 for m in current_meetings
    )

    prev_count = len(prev_meetings)
    prev_duration_hours = sum(
        (m.ends_at - m.starts_at).total_seconds() / 3600.0 for m in prev_meetings
    )

    count_change = curr_count - prev_count
    duration_change = curr_duration_hours - prev_duration_hours

    # 2. Top 5 longest meetings
    longest_meetings = sorted(
        current_meetings,
        key=lambda m: ((m.ends_at - m.starts_at).total_seconds(), m.starts_at),
        reverse=True,
    )[:5]

    # 3. Breakdown per organizer (User)
    # Fetch user records for owners in current_meetings
    owner_ids = {m.owner_id for m in current_meetings if m.owner_id}
    users_by_id: dict[object, User] = {}
    if owner_ids:
        users_stmt = select(User).where(User.id.in_(owner_ids))
        users_res = await session.execute(users_stmt)
        users_by_id = {u.id: u for u in users_res.scalars().all()}

    organizer_stats: dict[object, dict[str, object]] = {}
    for m in current_meetings:
        oid = m.owner_id
        if oid not in organizer_stats:
            user = users_by_id.get(oid)
            email = user.email if user else "Unknown"
            name = user.name if user else "Unknown"
            organizer_stats[oid] = {
                "email": email,
                "name": name,
                "count": 0,
                "duration_hours": 0.0,
            }
        dur = (m.ends_at - m.starts_at).total_seconds() / 3600.0
        organizer_stats[oid]["count"] = int(organizer_stats[oid]["count"]) + 1
        organizer_stats[oid]["duration_hours"] = float(organizer_stats[oid]["duration_hours"]) + dur

    sorted_organizers = sorted(
        organizer_stats.values(),
        key=lambda o: (float(o["duration_hours"]), int(o["count"])),
        reverse=True,
    )

    # Build CSV output
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")

    # Section 1: Weekly Comparison Summary
    writer.writerow(["METRIC", "CURRENT_WEEK", "PREVIOUS_WEEK", "CHANGE"])
    writer.writerow(["Week Identifier", week, prev_week, "-"])
    writer.writerow(["Meetings Count", curr_count, prev_count, f"{count_change:+d}"])
    writer.writerow(
        [
            "Total Duration (hours)",
            f"{curr_duration_hours:.2f}",
            f"{prev_duration_hours:.2f}",
            f"{duration_change:+.2f}",
        ]
    )
    writer.writerow([])

    # Section 2: Top 5 Longest Meetings
    writer.writerow(["TOP 5 LONGEST MEETINGS"])
    writer.writerow(["Title", "Starts At (UTC)", "Duration (hours)", "Participants Count"])
    if longest_meetings:
        for m in longest_meetings:
            dur_h = (m.ends_at - m.starts_at).total_seconds() / 3600.0
            p_count = len(m.participants)
            writer.writerow(
                [
                    m.title,
                    m.starts_at.isoformat(),
                    f"{dur_h:.2f}",
                    p_count,
                ]
            )
    else:
        writer.writerow(["No meetings recorded for this week", "-", "-", "-"])
    writer.writerow([])

    # Section 3: Breakdown by Organizer
    writer.writerow(["BREAKDOWN BY ORGANIZER"])
    writer.writerow(
        ["Organizer Email", "Organizer Name", "Meetings Count", "Total Duration (hours)"]
    )
    if sorted_organizers:
        for org in sorted_organizers:
            writer.writerow(
                [
                    org["email"],
                    org["name"],
                    org["count"],
                    f"{float(org['duration_hours']):.2f}",
                ]
            )
    else:
        writer.writerow(["No organizers recorded for this week", "-", "-", "-"])

    return output.getvalue().encode("utf-8")
