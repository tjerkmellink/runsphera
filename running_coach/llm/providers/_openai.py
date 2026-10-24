"""OpenAI provider for the coach voice.

Wraps the official `openai` SDK. Reads the API key from
`OPENAI_API_KEY` (the settings save step mirrors the DB value into the
env on every render).

Prompt layout — the same three-block "layered prompt" shape the
Anthropic provider uses, but combined into a single user message
(OpenAI doesn't have inline cache control; profile/request just
concatenate). Cost stays low because the coach call fires at most
twice per day per runner.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

from ._base import LLMResult

log = logging.getLogger(__name__)

# `gpt-4o-mini` is the cheapest-capable OpenAI model that still nails the
# "weave specific data into a coherent line" task. After OpenAI's $5
# starter credit it costs ~€0.10/year at one call/day.
DEFAULT_MODEL = "gpt-4o-mini"


def is_available() -> bool:
    load_dotenv()
    return bool(os.getenv("OPENAI_API_KEY"))


def _client():
    """Lazy-import the SDK so the dispatcher stays usable even when
    the openai package is missing."""
    import openai
    load_dotenv()
    return openai.OpenAI()  # picks up OPENAI_API_KEY from env


def coach_message(
    system: str,
    profile: str,
    request: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    effort: str = "medium",  # noqa: ARG001 — accepted for signature parity
) -> LLMResult | None:
    if not is_available():
        return None
    try:
        client = _client()
        # OpenAI doesn't have multi-block content with cache hints the
        # way Anthropic does, so we concatenate profile + request into
        # one user turn. System message stays separate.
        resp = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"{profile}\n\n{request}"},
            ],
        )
    except Exception as exc:  # noqa: BLE001 — defensive: never crash the dashboard
        # The SDK raises a variety of typed errors (AuthenticationError,
        # RateLimitError, APIError, BadRequestError, etc.); the
        # downstream caller treats `None` the same regardless of cause.
        log.warning("OpenAI call failed: %s: %s", type(exc).__name__, exc)
        return None

    text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not text:
        return None

    usage: dict[str, Any] = {}
    if getattr(resp, "usage", None):
        try:
            usage = json.loads(resp.usage.model_dump_json())
        except Exception:  # noqa: BLE001
            usage = {}

    return LLMResult(text=text, model=resp.model or model, usage=usage)
