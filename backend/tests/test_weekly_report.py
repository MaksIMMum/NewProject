import csv
import io
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models import Base, Meeting, Participant, User
from app.reports.weekly import (
    build_weekly_report,
    get_previous_iso_week,
    parse_iso_week,
)


def test_parse_iso_week_valid():
    start_dt, end_dt = parse_iso_week("2026-W40")
    # 2026-W40 starts on Monday Sep 28, 2026 and ends on Sunday Oct 4, 2026
    assert start_dt.year == 2026
    assert start_dt.month == 9
    assert start_dt.day == 28
    assert start_dt.hour == 0
    assert start_dt.minute == 0
    assert start_dt.second == 0
    assert start_dt.tzinfo == UTC

    assert end_dt.year == 2026
    assert end_dt.month == 10
    assert end_dt.day == 4
    assert end_dt.hour == 23
    assert end_dt.minute == 59
    assert end_dt.second == 59
    assert end_dt.tzinfo == UTC


def test_parse_iso_week_year_boundary():
    # 2026-W01 starts on Monday Dec 29, 2025 and ends on Sunday Jan 4, 2026
    start_dt, end_dt = parse_iso_week("2026-W01")
    assert start_dt.year == 2025
    assert start_dt.month == 12
    assert start_dt.day == 29
    assert end_dt.year == 2026
    assert end_dt.month == 1
    assert end_dt.day == 4


def test_parse_iso_week_invalid():
    for invalid in ["2026-40", "2026-W00", "2026-W54", "invalid", "", "2026-W4"]:
        with pytest.raises(ValueError):
            parse_iso_week(invalid)


def test_get_previous_iso_week():
    assert get_previous_iso_week("2026-W40") == "2026-W39"
    # ISO week 01 of 2026: previous week is 2025-W52
    assert get_previous_iso_week("2026-W01") == "2025-W52"


@pytest.fixture
async def db_session(engine):
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        yield session


async def test_build_weekly_report_empty(db_session):
    report_bytes = await build_weekly_report("2026-W40", db_session)
    assert isinstance(report_bytes, bytes)
    content = report_bytes.decode("utf-8")
    assert "METRIC,CURRENT_WEEK,PREVIOUS_WEEK,CHANGE" in content
    assert "Meetings Count,0,0,+0" in content
    assert "Total Duration (hours),0.00,0.00,+0.00" in content
    assert "No meetings recorded for this week" in content
    assert "No organizers recorded for this week" in content


async def test_build_weekly_report_with_data(db_session):
    # 1. Create users
    alice = User(
        cognito_sub="sub-alice",
        email="alice@example.com",
        name="Alice Allison",
    )
    bob = User(
        cognito_sub="sub-bob",
        email="bob@example.com",
        name="Bob Builder",
    )
    p1 = Participant(name="Part 1", email="p1@example.com")
    p2 = Participant(name="Part 2", email="p2@example.com")
    db_session.add_all([alice, bob, p1, p2])
    await db_session.flush()

    # 2. Create meetings
    # Previous week (2026-W39): Sep 21 - Sep 27
    m_prev = Meeting(
        title="Prev Week Standup",
        starts_at=datetime(2026, 9, 22, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 22, 11, 0, tzinfo=UTC),  # 1 hour
        place="Room A",
        owner_id=alice.id,
    )

    # Current week (2026-W40): Sep 28 - Oct 4
    # Meeting 1: Alice, 2 hours, 2 participants
    m1 = Meeting(
        title="Alice Long Planning",
        starts_at=datetime(2026, 9, 28, 9, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 28, 11, 0, tzinfo=UTC),  # 2.0 hours
        place="Room 101",
        owner_id=alice.id,
        participants=[p1, p2],
    )
    # Meeting 2: Bob, 1.5 hours, 1 participant
    m2 = Meeting(
        title="Bob Sync",
        starts_at=datetime(2026, 9, 29, 14, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 29, 15, 30, tzinfo=UTC),  # 1.5 hours
        place="Online",
        owner_id=bob.id,
        participants=[p1],
    )
    # Meeting 3: Alice, 0.5 hours
    m3 = Meeting(
        title="Alice Quick Review",
        starts_at=datetime(2026, 9, 30, 16, 0, tzinfo=UTC),
        ends_at=datetime(2026, 9, 30, 16, 30, tzinfo=UTC),  # 0.5 hours
        place="Online",
        owner_id=alice.id,
    )

    # Next week (2026-W41): Oct 5 - Oct 11 - should not be counted
    m_next = Meeting(
        title="Next Week Kickoff",
        starts_at=datetime(2026, 10, 5, 10, 0, tzinfo=UTC),
        ends_at=datetime(2026, 10, 5, 11, 0, tzinfo=UTC),
        place="Room B",
        owner_id=bob.id,
    )

    db_session.add_all([m_prev, m1, m2, m3, m_next])
    await db_session.commit()

    # Build report for 2026-W40
    report_bytes = await build_weekly_report("2026-W40", db_session)
    content = report_bytes.decode("utf-8")
    reader = list(csv.reader(io.StringIO(content)))

    # Verify Summary Section
    assert reader[0] == ["METRIC", "CURRENT_WEEK", "PREVIOUS_WEEK", "CHANGE"]
    assert reader[1] == ["Week Identifier", "2026-W40", "2026-W39", "-"]
    # Curr count = 3, Prev count = 1 -> Change = +2
    assert reader[2] == ["Meetings Count", "3", "1", "+2"]
    # Curr duration = 2.0 + 1.5 + 0.5 = 4.00, Prev duration = 1.00 -> Change = +3.00
    assert reader[3] == ["Total Duration (hours)", "4.00", "1.00", "+3.00"]

    # Verify Top 5 Longest Meetings Section
    assert "TOP 5 LONGEST MEETINGS" in [r[0] for r in reader if r]
    excluded = {
        "METRIC",
        "Week Identifier",
        "Meetings Count",
        "Total Duration (hours)",
        "Title",
        "Organizer Email",
        "No meetings recorded for this week",
        "No organizers recorded for this week",
    }
    meeting_rows = [r for r in reader if len(r) == 4 and r[0] not in excluded]
    meeting_titles = [r[0] for r in meeting_rows[:3]]
    # m1 (2.0h) > m2 (1.5h) > m3 (0.5h)
    assert meeting_titles == ["Alice Long Planning", "Bob Sync", "Alice Quick Review"]

    # Check participants count on Alice Long Planning
    m1_row = next(r for r in reader if len(r) == 4 and r[0] == "Alice Long Planning")
    assert m1_row[2] == "2.00"
    assert m1_row[3] == "2"

    # Verify Breakdown by Organizer Section
    assert "BREAKDOWN BY ORGANIZER" in [r[0] for r in reader if r]
    alice_row = next(r for r in reader if len(r) == 4 and r[0] == "alice@example.com")
    assert alice_row[1] == "Alice Allison"
    assert alice_row[2] == "2"  # Alice organized 2 meetings
    assert alice_row[3] == "2.50"  # 2.0 + 0.5 = 2.50 hours

    bob_row = next(r for r in reader if len(r) == 4 and r[0] == "bob@example.com")
    assert bob_row[1] == "Bob Builder"
    assert bob_row[2] == "1"
    assert bob_row[3] == "1.50"


async def test_build_weekly_report_idempotency(db_session):
    # Running report twice on same week produces identical bytes
    rep1 = await build_weekly_report("2026-W40", db_session)
    rep2 = await build_weekly_report("2026-W40", db_session)
    assert rep1 == rep2
