"""Provider-agnostic LLM dispatcher.

Single seam between the rest of the app (`commentary.py`) and the
specific LLM providers under `providers/`. The dispatcher:

- Resolves the active provider via the runner's settings (DB-backed),
  falling back to Anthropic when none is configured yet.
- Hands the (system, profile, request) prompt to that provider with its
  per-provider default model + any caller overrides.
- Returns a uniform `LLMResult` regardless of provider, so caching and
  fallback logic upstream don't need to branch.

`is_available()` checks the **active provider's** credentials, not any
provider's — so the dashboard's coach banner gracefully degrades if the
runner switched to a provider they haven't set up yet.

Adding a new provider: drop `providers/_<name>.py` implementing
`is_available()` + `coach_message(...)`, register it in `_PROVIDERS`
below, then wire its storage column + UI tab in settings.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from typing import Any

from .providers import _anthropic, _gemini, _openai
from .providers._base import LLMResult

# Re-export so existing callers `from runsphera.llm.connector import LLMResult`
# keep working without touching imports.
__all__ = ["LLMResult", "is_available", "coach_message", "active_provider", "DEFAULT_MODEL"]

log = logging.getLogger(__name__)

# Provider registry. Keys are the stable identifiers persisted in
# `app_settings.llm_provider`. Add new providers by appending here.
_PROVIDERS = {
    "anthropic": _anthropic,
    "openai":    _openai,
    "gemini":    _gemini,
}

# Per-provider default model (used when the caller doesn't override and
# the user hasn't picked one in settings). Tuned for the coach use case:
# capable enough to weave specific data points into a coherent line,
# while keeping cost / free-tier limits sensible:
#   anthropic — Opus 4.7 for the sharpest voice (paid after $5 credit)
#   openai    — gpt-4o-mini, cheap-but-capable (paid after $5 credit)
#   gemini    — 2.5 Flash, truly free (1500 req/day on AI Studio)
_DEFAULT_MODELS = {
    "anthropic": _anthropic.DEFAULT_MODEL,
    "openai":    _openai.DEFAULT_MODEL,
    "gemini":    _gemini.DEFAULT_MODEL,
}

# Backward-compat: existing callers import `connector.DEFAULT_MODEL`.
DEFAULT_MODEL = _anthropic.DEFAULT_MODEL


def active_provider() -> str:
    """Resolve which provider the runner has currently selected.

    Reads `app_settings.llm_provider` lazily on each call (one indexed
    row — same pattern as `_current_language()` in
    web/app.py). Falls back to 'anthropic' before the column exists or
    when no row is set.
    """
    try:
        from runsphera.db import connect
        from runsphera import settings as app_settings
        with closing(connect()) as conn:
            return app_settings.get_llm_provider(conn) or "anthropic"
    except (sqlite3.OperationalError, AttributeError, Exception):  # noqa: BLE001
        # Pre-migration / pre-helper state — default to Anthropic so
        # the existing flow keeps working through the schema rollout.
        return "anthropic"


def _resolve(name: str | None = None):
    """Return the provider module for `name`, defaulting to active +
    falling back to Anthropic if the chosen provider isn't registered."""
    key = (name or active_provider()).lower()
    return _PROVIDERS.get(key) or _PROVIDERS["anthropic"]


# Map of provider name → env var the provider SDK reads. Used by
# `_sync_provider_env` to mirror DB-stored keys into the process env
# at call time, as a safety net when the startup hook missed them
# (e.g. key was saved after server boot, or env got cleared).
_PROVIDER_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "gemini":    "GEMINI_API_KEY",
}


def _sync_provider_env(name: str) -> None:
    """Ensure the active provider's API-key env var is populated from
    the DB. Idempotent and cheap (single indexed row read). The
    web-app startup hook also mirrors keys to env, but does so once
    at boot — this lazy sync catches the case where the key was
    saved after boot or the env got cleared somehow."""
    env_var = _PROVIDER_ENV_VARS.get(name)
    if not env_var or os.getenv(env_var):
        return
    try:
        from runsphera.db import connect
        from runsphera import settings as app_settings
        key_getter = {
            "anthropic": app_settings.get_anthropic_key,
            "openai":    app_settings.get_openai_key,
            "gemini":    app_settings.get_gemini_key,
        }.get(name)
        if not key_getter:
            return
        with closing(connect()) as conn:
            key = key_getter(conn)
        if key:
            os.environ[env_var] = key
    except Exception:  # noqa: BLE001 — env-sync failure shouldn't blow up the LLM call
        pass


def is_available() -> bool:
    """Cheap check: is the **active** provider's API key set?

    Mirrors the original boolean contract — callers fall back to the
    rules-based coach line when this returns False.
    """
    name = active_provider()
    _sync_provider_env(name)
    return _resolve(name).is_available()


def coach_message(
    system_prompt: str,
    profile_block: str,
    request_block: str,
    *,
    model: str | None = None,
    max_tokens: int = 1024,
    effort: str = "medium",
) -> LLMResult | None:
    """Single coach-line call, dispatched to the active provider.

    `model=None` (the default) means "use the active provider's
    default" — important because callers currently rely on the
    dispatcher to pick the right model for whoever the user chose.
    Passing an explicit `model` will be sent through verbatim; the
    provider may reject it if it doesn't recognize the name.

    `effort` is Anthropic-specific (extended-thinking budget hint);
    other providers safely ignore it.
    """
    provider_name = active_provider()
    _sync_provider_env(provider_name)
    provider = _PROVIDERS.get(provider_name) or _PROVIDERS["anthropic"]
    resolved_model = model or _DEFAULT_MODELS.get(provider_name) or DEFAULT_MODEL
    return provider.coach_message(
        system_prompt,
        profile_block,
        request_block,
        model=resolved_model,
        max_tokens=max_tokens,
        effort=effort,
    )
