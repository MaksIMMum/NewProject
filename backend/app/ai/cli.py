"""CLI helpers for make llm-hello and make parse."""

import json
import os
import sys
from datetime import date

from anthropic import AnthropicBedrockMantle

from app.ai.agenda import parse_agenda
from app.config import settings


def hello() -> None:
    client = AnthropicBedrockMantle(aws_region=settings.aws_region)
    msg = client.messages.create(
        model=settings.parser_model,
        max_tokens=1024,
        output_config={"effort": "low"},
        messages=[{"role": "user", "content": "In one sentence: what is an ISO week?"}],
    )
    print(next(b.text for b in msg.content if b.type == "text"))
    print(
        f"stop_reason: {msg.stop_reason} "
        f"input_tokens: {msg.usage.input_tokens} "
        f"output_tokens: {msg.usage.output_tokens}"
    )


def parse() -> None:
    text = os.environ.get("TEXT") or (" ".join(sys.argv[2:]) if len(sys.argv) > 2 else "")
    if not text.strip():
        print('Usage: make parse TEXT="..."')
        sys.exit(1)
    agenda, usage = parse_agenda(text, date.today(), "Europe/Kyiv")
    print(json.dumps(agenda.model_dump(mode="json"), indent=2, ensure_ascii=False))
    print("Usage:", usage)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "hello"
    if cmd == "hello":
        hello()
    elif cmd == "parse":
        parse()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
