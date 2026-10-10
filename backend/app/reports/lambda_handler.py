"""Lambda handler for report-builder."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.reports.weekly import build_weekly_report

# Configure structured logging
logger = logging.getLogger("report-builder")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(levelname)s] %(asctime)s - %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def get_default_previous_iso_week() -> str:
    """Compute the preceding ISO week (e.g. '2026-W39') from current UTC time."""
    now = datetime.now(UTC)
    prev_date = now.date() - timedelta(days=7)
    iso_year, iso_week, _ = prev_date.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def extract_payload_and_trigger(event: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """Extract payload dict and detect trigger source ('schedule', 'sqs', or 'direct')."""
    # 1. SQS Event Source Mapping
    if "Records" in event and isinstance(event["Records"], list) and len(event["Records"]) > 0:
        record = event["Records"][0]
        if record.get("eventSource") == "aws:sqs" or "body" in record:
            raw_body = record.get("body", "{}")
            try:
                body = json.loads(raw_body) if isinstance(raw_body, str) else raw_body
            except Exception:
                body = {}
            source = body.get("source", "")
            if source == "schedule":
                trigger = "schedule"
            else:
                trigger = "sqs"
            return body, trigger

    # 2. EventBridge Scheduler / Direct Invocation
    body = event
    source = event.get("source", "")
    if source in ("schedule", "aws.scheduler", "aws.events"):
        trigger = "schedule"
    elif source == "manual":
        trigger = "sqs"
    else:
        trigger = "direct"
    return body, trigger


async def run_builder(week: str, reports_bucket: str) -> str:
    """Execute async DB query, build CSV, and upload to S3."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is not configured.")
    engine = create_async_engine(db_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            csv_bytes = await build_weekly_report(week, session)
    finally:
        await engine.dispose()

    s3_key = f"reports/{week}.csv"
    s3_client = boto3.client("s3")
    s3_client.put_object(
        Bucket=reports_bucket,
        Key=s3_key,
        Body=csv_bytes,
        ContentType="text/csv",
    )
    return s3_key


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda entrypoint for the report-builder."""
    payload, trigger = extract_payload_and_trigger(event)

    # Resolve week: explicit week or fallback to previous ISO week
    week = payload.get("week")
    if not week:
        week = get_default_previous_iso_week()

    # Exact log line format required by submission item 5
    logger.info(
        "report-builder triggered",
        extra={"trigger": trigger, "week": week},
    )
    # Also log a standard plaintext line with the trigger for CloudWatch searchability
    logger.info(f"report-builder triggered: trigger={trigger} week={week}")

    reports_bucket = os.environ.get("REPORTS_BUCKET")
    if not reports_bucket:
        raise ValueError("REPORTS_BUCKET environment variable is not configured.")

    # Run report builder
    s3_key = asyncio.run(run_builder(week, reports_bucket))

    logger.info(
        "report-builder completed: trigger=%s week=%s key=%s bucket=%s",
        trigger,
        week,
        s3_key,
        reports_bucket,
    )

    return {
        "status": "success",
        "trigger": trigger,
        "week": week,
        "bucket": reports_bucket,
        "key": s3_key,
    }
