"""Public entry point for the LLM coach layer.

Single function: `daily_coach_message(conn, recommendation, todays_workout)`.
Returns the cached message if one exists for today, otherwise calls Claude
and stores the result. Returns None when the LLM is unavailable or the call
fails — callers fall back to the rules-based headline.

Cache key is `daily_coach:<YYYY-MM-DD>`. Invalidated explicitly by the sync
job and the swap-apply path so today's message stays in sync with the data.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timezone
from typing import Any

from .. import settings as app_settings
from . import connector, context, prompts

log = logging.getLogger(__name__)


def _cache_key(today: date | None = None) -> str:
    today = today or date.today()
    return f"daily_coach:{today.isoformat()}"


def _read_cache(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT content FROM llm_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    return row["content"] if row else None


def _write_cache(
    conn: sqlite3.Connection,
    key: str,
    content: str,
    model: str,
    usage: dict[str, Any],
) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO llm_cache (cache_key, content, model, created_at, usage_json)
           VALUES (?, ?, ?, datetime('now'), ?)""",
        (key, content, model, json.dumps(usage) if usage else None),
    )
    conn.commit()


def invalidate_today(conn: sqlite3.Connection, today: date | None = None) -> None:
    """Drop today's cached coach message so the next dashboard render regenerates it."""
    conn.execute("DELETE FROM llm_cache WHERE cache_key = ?", (_cache_key(today),))
    conn.commit()


def invalidate_all_coach(conn: sqlite3.Connection) -> int:
    """Drop *every* cached coach message (daily, weekly recap, all run
    reactions). Called when the runner switches UI language so the next
    render produces output in the new locale instead of serving stale
    English (or stale Dutch) text. Returns the row count cleared."""
    cur = conn.execute("DELETE FROM llm_cache")
    conn.commit()
    return cur.rowcount or 0


def _cache_row_local_hhmm(conn: sqlite3.Connection, key: str) -> str | None:
    """SQLite `datetime('now')` is UTC; render the cache row's creation time
    as local HH:MM for the editorial byline. Returns None when there's no
    row or parsing fails."""
    row = conn.execute(
        "SELECT created_at FROM llm_cache WHERE cache_key = ?", (key,)
    ).fetchone()
    if not row or not row["created_at"]:
        return None
    try:
        dt = datetime.fromisoformat(row["created_at"]).replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%H:%M")
    except Exception:  # noqa: BLE001
        return None


def daily_coach_generated_at(
    conn: sqlite3.Connection, today: date | None = None
) -> str | None:
    """Local HH:MM the daily coach message was generated."""
    return _cache_row_local_hhmm(conn, _cache_key(today))


def weekly_recap_generated_at(
    conn: sqlite3.Connection, today: date | None = None
) -> str | None:
    """Local HH:MM the current week's recap was generated. Targets the same
    Mon-Sun window as `weekly_recap()`."""
    _, _, week_key = context.target_recap_week(today)
    return _cache_row_local_hhmm(conn, _weekly_recap_key(week_key))


def run_reaction_generated_at(
    conn: sqlite3.Connection, activity_id: int
) -> str | None:
    """Local HH:MM the coach's debrief for one activity was generated."""
    return _cache_row_local_hhmm(conn, _run_reaction_key(activity_id))


def _run_reaction_key(activity_id: int) -> str:
    return f"run_reaction:{activity_id}"


def _weekly_recap_key(week_key: str) -> str:
    return f"weekly_recap:{week_key}"


def invalidate_weekly_recap(conn: sqlite3.Connection, today: date | None = None) -> None:
    """Drop the cached recap for the *currently-targeted* week. Called on
    Garmin sync and diary edits — anything that changes what the recap should
    say about the most-recently-completed week."""
    _, _, week_key = context.target_recap_week(today)
    conn.execute(
        "DELETE FROM llm_cache WHERE cache_key = ?",
        (_weekly_recap_key(week_key),),
    )
    conn.commit()


def invalidate_run_reaction(conn: sqlite3.Connection, activity_id: int) -> None:
    """Drop the cached coach reaction for one activity. Called on diary edit
    and on Garmin feel/RPE refresh so the next modal open regenerates with
    the updated context."""
    conn.execute(
        "DELETE FROM llm_cache WHERE cache_key = ?",
        (_run_reaction_key(activity_id),),
    )
    conn.commit()


def peek_run_reaction(conn: sqlite3.Connection, activity_id: int) -> str | None:
    """Cache-only lookup — never makes an LLM call. Used by the run-detail
    route so the modal can render fast on cached views, and show a spinner
    placeholder that lazy-loads the real call on first view."""
    return _read_cache(conn, _run_reaction_key(activity_id))


def daily_coach_message(
    conn: sqlite3.Connection,
    recommendation: dict[str, Any] | None,
    todays_workout: dict[str, Any] | None,
    *,
    force_refresh: bool = False,
) -> str | None:
    """Return today's personalized coach banner, or None on any failure.

    Caches per calendar day. Pass force_refresh=True to bypass and regenerate.
    The coach is "always present" — it speaks even when there's no workout or
    recommendation today, drawing on recent runs, diary, readiness, and the
    active plan. Returns None only when there's genuinely nothing to talk
    about (no plan, no recent runs, no diary entries) or when the call fails.
    """
    key = _cache_key()

    if not force_refresh:
        cached = _read_cache(conn, key)
        if cached:
            return cached

    if not connector.is_available():
        return None

    try:
        profile_kwargs = context.build_profile_context(conn)
        request_kwargs = context.build_request_context(conn, recommendation, todays_workout)
    except Exception:  # noqa: BLE001 — defensive: never break the dashboard
        log.exception("Failed to build LLM context")
        return None

    # Skip the LLM if there's truly nothing to anchor on — fresh user, empty DB.
    if (
        not recommendation
        and not profile_kwargs.get("plan")
        and not profile_kwargs.get("recent_runs")
        and not profile_kwargs.get("recent_diary")
    ):
        return None

    try:
        profile_text = prompts.profile_block(**profile_kwargs)
        request_text = prompts.request_block(**request_kwargs)
    except Exception:  # noqa: BLE001
        log.exception("Failed to render LLM prompts")
        return None

    locale = app_settings.get_language(conn)
    result = connector.coach_message(
        system_prompt=prompts.system_prompt_for(prompts.SYSTEM_PROMPT, locale),
        profile_block=profile_text,
        request_block=request_text,
    )
    if result is None:
        return None

    try:
        _write_cache(conn, key, result.text, result.model, result.usage)
    except Exception:  # noqa: BLE001 — caching is best-effort
        log.exception("Failed to write LLM cache")

    return result.text


def run_reaction(
    conn: sqlite3.Connection,
    activity_id: int,
    *,
    force_refresh: bool = False,
) -> str | None:
    """Return the coach's short debrief on one completed activity, or None on
    any failure (LLM unavailable, activity not found, network blip — caller
    just renders without the reaction).

    Cached per-activity in `llm_cache` under `run_reaction:{activity_id}`.
    Invalidate on diary edit or feel/RPE refresh via `invalidate_run_reaction`.
    """
    key = _run_reaction_key(activity_id)

    if not force_refresh:
        cached = _read_cache(conn, key)
        if cached:
            return cached

    if not connector.is_available():
        return None

    try:
        profile_kwargs = context.build_profile_context(conn)
        run_kwargs = context.build_run_reaction_context(conn, activity_id)
    except Exception:  # noqa: BLE001
        log.exception("Failed to build run-reaction context")
        return None

    if run_kwargs is None:
        return None

    try:
        profile_text = prompts.profile_block(**profile_kwargs)
        request_text = prompts.run_reaction_request_block(**run_kwargs)
    except Exception:  # noqa: BLE001
        log.exception("Failed to render run-reaction prompts")
        return None

    locale = app_settings.get_language(conn)
    result = connector.coach_message(
        system_prompt=prompts.system_prompt_for(prompts.RUN_REACTION_SYSTEM_PROMPT, locale),
        profile_block=profile_text,
        request_block=request_text,
    )
    if result is None:
        return None

    try:
        _write_cache(conn, key, result.text, result.model, result.usage)
    except Exception:  # noqa: BLE001
        log.exception("Failed to write run-reaction cache")

    return result.text


def weekly_recap(
    conn: sqlite3.Connection,
    *,
    force_refresh: bool = False,
    today: date | None = None,
) -> dict | None:
    """Return {text, week_label, week_start_iso, week_end_iso} for the most-
    recently-completed Mon-Sun week, or None when there's nothing to talk about
    (no plan, no runs, no diary) or the LLM call fails. Cached per ISO week."""
    today = today or date.today()
    mon, sun, week_key = context.target_recap_week(today)
    cache_key = _weekly_recap_key(week_key)

    if not force_refresh:
        cached = _read_cache(conn, cache_key)
        if cached:
            return {
                "text": cached,
                "week_label": f"Mon {mon.strftime('%d %b')} – Sun {sun.strftime('%d %b %Y')}",
                "week_start_iso": mon.isoformat(),
                "week_end_iso": sun.isoformat(),
                "week_key": week_key,
            }

    if not connector.is_available():
        return None

    try:
        profile_kwargs = context.build_profile_context(conn)
        recap_kwargs = context.build_weekly_recap_context(conn, today=today)
    except Exception:  # noqa: BLE001
        log.exception("Failed to build weekly-recap context")
        return None

    if recap_kwargs is None:
        return None  # truly nothing happened that week — stay silent

    try:
        profile_text = prompts.profile_block(**profile_kwargs)
        request_text = prompts.weekly_recap_request_block(**recap_kwargs)
    except Exception:  # noqa: BLE001
        log.exception("Failed to render weekly-recap prompts")
        return None

    locale = app_settings.get_language(conn)
    result = connector.coach_message(
        system_prompt=prompts.system_prompt_for(prompts.WEEKLY_RECAP_SYSTEM_PROMPT, locale),
        profile_block=profile_text,
        request_block=request_text,
    )
    if result is None:
        return None

    try:
        _write_cache(conn, cache_key, result.text, result.model, result.usage)
    except Exception:  # noqa: BLE001
        log.exception("Failed to write weekly-recap cache")

    return {
        "text": result.text,
        "week_label": recap_kwargs["week_label"],
        "week_start_iso": recap_kwargs["week_start_iso"],
        "week_end_iso": recap_kwargs["week_end_iso"],
        "week_key": week_key,
    }


def _week_wrapped_key(plan_id: int, week_number: int, sessions_done: int) -> str:
    # `sessions_done` is part of the key so the celebration regenerates if the
    # completion state ever changes (a late-matched run, a re-sync). In practice
    # we only ever call the LLM once a week is fully done, so the key is stable.
    return f"week_wrapped:{plan_id}:{week_number}:{sessions_done}"


def week_wrapped_generated_at(conn: sqlite3.Connection, plan_id: int, stats: dict) -> str | None:
    """Local HH:MM the celebration line for this completed week was generated."""
    return _cache_row_local_hhmm(
        conn, _week_wrapped_key(plan_id, stats["week_number"], stats["sessions_done"])
    )


def peek_week_wrapped(conn: sqlite3.Connection, plan_id: int, stats: dict) -> str | None:
    """Cache-only lookup — never calls the LLM."""
    return _read_cache(
        conn, _week_wrapped_key(plan_id, stats["week_number"], stats["sessions_done"])
    )


def week_wrapped(
    conn: sqlite3.Connection,
    plan_id: int,
    stats: dict,
    *,
    force_refresh: bool = False,
) -> str | None:
    """A one/two-sentence celebration line for a fully-completed training week,
    or None when the LLM is unavailable or the call fails (the caller then falls
    back to the rules-based line rendered in _week_wrapped.html).

    Cached per plan+week+completion under `week_wrapped:{plan}:{week}:{done}`.
    Only ever called once a week is complete — mid-week the dashboard renders
    the instant rules-based line and never touches the LLM.
    """
    key = _week_wrapped_key(plan_id, stats["week_number"], stats["sessions_done"])

    if not force_refresh:
        cached = _read_cache(conn, key)
        if cached:
            return cached

    if not connector.is_available():
        return None

    try:
        profile_kwargs = context.build_profile_context(conn)
        profile_text = prompts.profile_block(**profile_kwargs)
        request_text = prompts.week_wrapped_request_block(
            stats, first_name=profile_kwargs.get("first_name")
        )
    except Exception:  # noqa: BLE001
        log.exception("Failed to build week-wrapped context")
        return None

    locale = app_settings.get_language(conn)
    result = connector.coach_message(
        system_prompt=prompts.system_prompt_for(prompts.WEEK_WRAPPED_SYSTEM_PROMPT, locale),
        profile_block=profile_text,
        request_block=request_text,
    )
    if result is None:
        return None

    try:
        _write_cache(conn, key, result.text, result.model, result.usage)
    except Exception:  # noqa: BLE001
        log.exception("Failed to write week-wrapped cache")

    return result.text
