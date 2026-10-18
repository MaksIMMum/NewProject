"""AWS Lambda handler for the agenda-parser function.

Runs outside the VPC with direct internet access to Amazon Bedrock.
Verifies Cognito JWT, validates text payload length (<= 10,000 characters),
calls parse_agenda, logs JSON telemetry line, and returns structured JSON.
"""

import json
import logging
import os
import sys
import time
from datetime import date
from typing import Any

from app.ai.agenda import PROMPT_VERSION, AgendaParseError, cost_usd, parse_agenda
from app.auth import InvalidTokenError, TokenVerifier
from app.config import settings

# Configure logger
logger = logging.getLogger("agenda-parser-lambda")
if not logger.handlers:
    handler_stdout = logging.StreamHandler(sys.stdout)
    handler_stdout.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.addHandler(handler_stdout)
logger.setLevel(logging.INFO)

# Token verifier cached across Lambda invocations
_verifier: TokenVerifier | None = None


def get_token_verifier() -> TokenVerifier | None:
    global _verifier
    if _verifier is None:
        user_pool_id = os.environ.get("COGNITO_USER_POOL_ID") or settings.cognito_user_pool_id
        client_id = os.environ.get("COGNITO_CLIENT_ID") or settings.cognito_client_id
        jwks = os.environ.get("COGNITO_JWKS") or settings.cognito_jwks
        if user_pool_id and client_id:
            _verifier = TokenVerifier(user_pool_id, client_id, jwks)
    return _verifier


def verify_cognito_token(auth_header: str) -> str:
    """Verify Cognito ID token from header and return user sub identifier."""
    verifier = get_token_verifier()
    if verifier is None:
        # Local development without Cognito configured: fallback to demo sub
        return "local-dev-user"

    if not auth_header:
        raise InvalidTokenError("Missing Authorization header")

    token = auth_header.replace("Bearer ", "").strip()
    if not token:
        raise InvalidTokenError("Empty bearer token")

    # verify is an async method on TokenVerifier
    import asyncio

    claims = asyncio.run(verifier.verify(token))
    return str(claims["sub"])


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Lambda entry point for agenda-parser Function URL."""
    http_method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "POST"
    )

    # Handle CORS OPTIONS preflight
    if http_method.upper() == "OPTIONS":
        return {
            "statusCode": 204,
            "headers": {
                "access-control-allow-origin": "*",
                "access-control-allow-methods": "POST, OPTIONS",
                "access-control-allow-headers": "Content-Type, Authorization",
            },
        }

    # 1. Authentication: verify Cognito token
    headers = event.get("headers") or {}
    auth_header = headers.get("authorization") or headers.get("Authorization") or ""
    try:
        user_sub = verify_cognito_token(auth_header)
    except InvalidTokenError as e:
        return {
            "statusCode": 401,
            "headers": {
                "content-type": "application/json",
                "access-control-allow-origin": "*",
            },
            "body": json.dumps({"error": f"Unauthorized: {e}"}),
        }

    # 2. Parse request body
    try:
        raw_body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            import base64

            raw_body = base64.b64decode(raw_body).decode("utf-8")
        body = json.loads(raw_body)
    except Exception as e:
        return {
            "statusCode": 400,
            "headers": {
                "content-type": "application/json",
                "access-control-allow-origin": "*",
            },
            "body": json.dumps({"error": f"Invalid JSON payload: {e}"}),
        }

    text = body.get("text", "")
    today_str = body.get("today")
    tz = body.get("tz", "UTC")

    # 3. Payload length limits: reject text > 10,000 characters
    if len(text) > 10000:
        return {
            "statusCode": 413,
            "headers": {
                "content-type": "application/json",
                "access-control-allow-origin": "*",
            },
            "body": json.dumps({"error": "Payload Too Large: text exceeds 10,000 characters"}),
        }

    if not text.strip():
        return {
            "statusCode": 422,
            "headers": {
                "content-type": "application/json",
                "access-control-allow-origin": "*",
            },
            "body": json.dumps({"error": "text cannot be empty"}),
        }

    try:
        today = date.fromisoformat(today_str) if today_str else date.today()
    except ValueError:
        return {
            "statusCode": 400,
            "headers": {
                "content-type": "application/json",
                "access-control-allow-origin": "*",
            },
            "body": json.dumps({"error": "Invalid date format for 'today' (expected YYYY-MM-DD)"}),
        }

    # 4. Invoke domain parser
    started = time.monotonic()
    try:
        agenda, usage = parse_agenda(text, today, tz)
    except AgendaParseError as e:
        return {
            "statusCode": 422,
            "headers": {
                "content-type": "application/json",
                "access-control-allow-origin": "*",
            },
            "body": json.dumps({"error": str(e)}),
        }
    except Exception as e:
        logger.error("Unexpected error during parsing: %s", e, exc_info=True)
        return {
            "statusCode": 500,
            "headers": {
                "content-type": "application/json",
                "access-control-allow-origin": "*",
            },
            "body": json.dumps({"error": "Internal server error during agenda parsing"}),
        }

    latency_ms = int((time.monotonic() - started) * 1000)
    calculated_cost = cost_usd(settings.parser_model, usage)

    # 5. One structured JSON CloudWatch log line
    log_payload = {
        "event": "agenda_parsed",
        "user": user_sub,
        "model": settings.parser_model,
        "prompt_version": PROMPT_VERSION,
        **usage,
        "latency_ms": latency_ms,
        "cost_usd": calculated_cost,
    }
    logger.info(json.dumps(log_payload))

    # 6. Return structured response
    return {
        "statusCode": 200,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": "*",
        },
        "body": json.dumps(
            {
                "agenda": agenda.model_dump(mode="json"),
                "model": settings.parser_model,
                "prompt_version": PROMPT_VERSION,
            }
        ),
    }
