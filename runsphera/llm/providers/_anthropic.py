"""Anthropic Claude provider for the coach voice.

Wraps the official `anthropic` SDK. Reads the API key from
`ANTHROPIC_API_KEY` (the settings save step mirrors the DB value into
the env on every render, so this stays a single source of truth at
call time).

Prompt-caching layout (`system` then `messages`):
- system  — persona/scope/format. Stable across all calls → cached.
- profile — runner identity + recent history. Stable per session → cached.
- request — today's specific context. Varies per call → not cached.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import anthropic
from dotenv import load_dotenv

from ._base import LLMResult

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-4-7"


def is_available() -> bool:
    load_dotenv()
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _client() -> anthropic.Anthropic:
    load_dotenv()
    return anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY from env


def coach_message(
    system: str,
    profile: str,
    request: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    effort: str = "medium",
) -> LLMResult | None:
    if not is_available():
        return None
    try:
        client = _client()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": profile,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": request},
                    ],
                }
            ],
        )
    except anthropic.AuthenticationError:
        log.warning("Anthropic auth failed — set ANTHROPIC_API_KEY correctly")
        return None
    except anthropic.RateLimitError as exc:
        log.warning("Anthropic rate limited: %s", exc)
        return None
    except anthropic.APIError as exc:
        log.warning("Anthropic API error: %s", exc)
        return None
    except Exception as exc:  # noqa: BLE001 — defensive: never crash the dashboard
        log.exception("Unexpected error calling Claude: %s", exc)
        return None

    text = next((b.text for b in response.content if b.type == "text"), "").strip()
    if not text:
        return None

    usage: dict[str, Any] = {}
    if response.usage:
        try:
            usage = json.loads(response.usage.model_dump_json())
        except Exception:  # noqa: BLE001
            usage = {}

    return LLMResult(text=text, model=response.model, usage=usage)
