import json
from datetime import date
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.ai.agenda import (
    ActionItem,
    AgendaItem,
    ParsedAgenda,
    cost_usd,
)
from app.ai.agenda_lambda import handler


def test_agenda_schema_validation():
    item = AgendaItem(topic="Discuss budget", owner="Olena", minutes=30)
    assert item.topic == "Discuss budget"
    assert item.minutes == 30

    action = ActionItem(task="Send slides", owner="Taras", due=date(2026, 10, 24))
    assert action.task == "Send slides"
    assert action.due == date(2026, 10, 24)

    agenda = ParsedAgenda(
        title="Weekly Sync",
        starts_at="2026-10-19T10:00:00Z",
        duration_minutes=60,
        items=[item],
        action_items=[action],
        language="en",
    )
    assert agenda.title == "Weekly Sync"
    assert len(agenda.items) == 1
    assert len(agenda.action_items) == 1


def test_agenda_schema_invalid():
    with pytest.raises(ValidationError):
        AgendaItem(topic="", owner="Max")  # min_length=1

    with pytest.raises(ValidationError):
        AgendaItem(topic="Topic", minutes=600)  # max 480

    with pytest.raises(ValidationError):
        ParsedAgenda(items=[], language="en", duration_minutes=700)  # max 600


def test_cost_calculation():
    # Haiku: $0.10/M in, $0.50/M out
    usage_haiku = {"input_tokens": 1000, "output_tokens": 200}
    cost_haiku = cost_usd("anthropic.claude-haiku-5-5", usage_haiku)
    # (1000 * 0.10 + 200 * 0.50) / 1,000,000 = (100 + 100) / 1,000,000 = 0.0002
    assert cost_haiku == 0.0002

    # Opus: $4.00/M in, $20.00/M out
    usage_opus = {"input_tokens": 1000, "output_tokens": 200}
    cost_opus = cost_usd("anthropic.claude-opus-5-5", usage_opus)
    # (1000 * 4.00 + 200 * 20.00) / 1,000,000 = (4000 + 4000) / 1,000,000 = 0.008
    assert cost_opus == 0.008


def test_lambda_handler_options():
    event = {"httpMethod": "OPTIONS"}
    resp = handler(event)
    assert resp["statusCode"] == 204


def test_lambda_handler_payload_too_large():
    event = {
        "headers": {"authorization": "Bearer valid-token"},
        "body": json.dumps({"text": "a" * 10001, "today": "2026-10-19"}),
    }
    with patch("app.ai.agenda_lambda.verify_cognito_token", return_value="user-123"):
        resp = handler(event)
        assert resp["statusCode"] == 413
        data = json.loads(resp["body"])
        assert "Payload Too Large" in data["error"]


def test_lambda_handler_empty_text():
    event = {
        "headers": {"authorization": "Bearer valid-token"},
        "body": json.dumps({"text": "   ", "today": "2026-10-19"}),
    }
    with patch("app.ai.agenda_lambda.verify_cognito_token", return_value="user-123"):
        resp = handler(event)
        assert resp["statusCode"] == 422


def test_lambda_handler_success():
    fake_agenda = ParsedAgenda(
        title="Quick Sync",
        items=[AgendaItem(topic="Intro", owner="Alice", minutes=10)],
        action_items=[],
        language="en",
    )
    fake_usage = {"input_tokens": 500, "output_tokens": 100}

    event = {
        "headers": {"authorization": "Bearer test-jwt"},
        "body": json.dumps({"text": "Quick sync with Alice", "today": "2026-10-19", "tz": "UTC"}),
    }

    with (
        patch("app.ai.agenda_lambda.verify_cognito_token", return_value="user-456"),
        patch("app.ai.agenda_lambda.parse_agenda", return_value=(fake_agenda, fake_usage)),
    ):
        resp = handler(event)
        assert resp["statusCode"] == 200
        body = json.loads(resp["body"])
        assert body["agenda"]["title"] == "Quick Sync"
        assert body["agenda"]["items"][0]["topic"] == "Intro"
        assert "model" in body
        assert "prompt_version" in body
