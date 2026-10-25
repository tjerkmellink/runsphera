"""Google Gemini provider for the coach voice.

Wraps the new `google-genai` SDK (the replacement for the legacy
`google-generativeai` package). Reads the API key from
`GEMINI_API_KEY` (the settings save step mirrors the DB value into
the env on every render).

Gemini's free tier on AI Studio is the only ongoing-free option among
the three providers — Flash models give 1500 req/day at no cost, which
is plenty for a once-per-day coach call.

Prompt shape: the SDK accepts a single `contents` text plus a
`system_instruction`, so we collapse profile + request into one user
turn (same as the OpenAI provider).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv

from ._base import LLMResult

log = logging.getLogger(__name__)

# `gemini-2.5-flash` is on the free tier and capable enough for the
# coach use case. If the user wants a sharper voice they can switch
# the provider tab to Anthropic — Gemini Pro is also possible but its
# free-tier quota (50 req/day) is too slim to be the default.
DEFAULT_MODEL = "gemini-2.5-flash"


def is_available() -> bool:
    load_dotenv()
    return bool(os.getenv("GEMINI_API_KEY"))


def _client():
    """Lazy-import the SDK so the dispatcher stays usable even when
    the google-genai package is missing."""
    from google import genai
    load_dotenv()
    # The new SDK pulls `GEMINI_API_KEY` automatically; passing
    # explicitly keeps it obvious which env var matters.
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


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
        from google.genai import types
        client = _client()
        # `max_output_tokens` is a TOTAL cap on Gemini's response budget,
        # and Gemini 2.5 Flash has dynamic "thinking" on by default —
        # internal reasoning tokens count against that cap. With thinking
        # consuming ~1000 tokens of a 1024 budget, the visible coach line
        # would truncate mid-sentence ("...flink boven het gepl"). Disable
        # thinking entirely for this use case: short factual debriefs
        # don't benefit from extended reasoning, and we want the full
        # token budget to go to the visible reply.
        thinking_config = None
        try:
            thinking_config = types.ThinkingConfig(thinking_budget=0)
        except (AttributeError, TypeError):
            # ThinkingConfig is only on 2.5-series; if it's missing on an
            # older SDK / different model the request still works without it.
            pass
        resp = client.models.generate_content(
            model=model,
            contents=f"{profile}\n\n{request}",
            config=types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=max_tokens,
                thinking_config=thinking_config,
            ),
        )
    except Exception as exc:  # noqa: BLE001 — defensive: never crash the dashboard
        log.warning("Gemini call failed: %s: %s", type(exc).__name__, exc)
        return None

    text = (resp.text or "").strip()
    if not text:
        return None

    # Gemini's usage object exposes `prompt_token_count`, `candidates_token_count`,
    # `total_token_count`. Flatten into our usage dict shape.
    usage: dict[str, Any] = {}
    um = getattr(resp, "usage_metadata", None)
    if um is not None:
        for k in ("prompt_token_count", "candidates_token_count", "total_token_count"):
            v = getattr(um, k, None)
            if v is not None:
                usage[k] = v

    return LLMResult(text=text, model=model, usage=usage)
