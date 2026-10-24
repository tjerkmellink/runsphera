"""Daily readiness-aware coaching.

Pure rules. Reads recent training_readiness, training_status, and today's planned
workout, and emits a recommendation (GO / CAUTION / EASY / REST) with the
signals that drove it. No LLM, no DB writes.

The dashboard renders this above the Today's workout card.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from . import service as plan_service


# Readiness score thresholds (Garmin's 0-100 composite).
_READINESS_LOW = 50
_READINESS_MOD = 65

# ACWR (acute:chronic workload ratio) thresholds — injury-risk zones.
_ACWR_HIGH_CAUTION = 1.3
_ACWR_HIGH_RED = 1.5
_ACWR_LOW = 0.7  # well below — fitness drifting down

_HARD_WORKOUT_TYPES = frozenset({"tempo", "intervals", "race"})
_MODERATE_WORKOUT_TYPES = frozenset({"long"})


def _latest_readiness(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM training_readiness ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def _latest_training_status(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM training_status ORDER BY calendar_date DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def _readiness_signal(rdy: dict | None) -> tuple[str, str | None]:
    """Return (color, reason_or_None) — color is 'green'/'yellow'/'red'."""
    if not rdy or rdy.get("score") is None:
        return ("green", None)  # no signal — don't penalize
    score = int(rdy["score"])
    level = rdy.get("level") or ""
    if score < _READINESS_LOW or level == "LOW":
        return ("red", f"Readiness {score} ({level or 'low'})")
    if score < _READINESS_MOD or level == "MODERATE":
        return ("yellow", f"Readiness {score} ({level or 'moderate'})")
    return ("green", None)


def _acwr_signal(ts: dict | None) -> tuple[str, str | None]:
    if not ts or ts.get("acwr_ratio") is None:
        return ("green", None)
    ratio = float(ts["acwr_ratio"])
    if ratio >= _ACWR_HIGH_RED:
        return ("red", f"ACWR {ratio:.2f} (overreaching)")
    if ratio >= _ACWR_HIGH_CAUTION:
        return ("yellow", f"ACWR {ratio:.2f} (drifting high)")
    if ratio < _ACWR_LOW:
        return ("yellow", f"ACWR {ratio:.2f} (training load low)")
    return ("green", None)


def _swap_suggestion(workout_type: str, severity: str) -> str | None:
    """When CAUTION or EASY, suggest a sensible swap for today's planned workout."""
    if workout_type in _HARD_WORKOUT_TYPES:
        if severity == "easy":
            return "Swap today's quality session for an easy run, or rest entirely."
        return "Consider easing the quality session — drop intervals, run tempo at the easy end of the zone."
    if workout_type in _MODERATE_WORKOUT_TYPES:
        if severity == "easy":
            return "Cut the long run by 30–40% and keep it strictly conversational."
        return "Keep the long run at the easy end — no marathon-pace surges."
    # Easy/recovery already low intensity
    if severity == "easy":
        return "Even today's easy run is optional — consider taking the rest instead."
    return None


def _combine(severities: list[str]) -> str:
    """Combine signal colors into an overall status."""
    if "red" in severities:
        return "easy"
    if "yellow" in severities:
        return "caution"
    return "go"


def _signals(rdy: dict | None, ts: dict | None) -> dict[str, Any]:
    """The raw numbers behind the decision — same shape for every status."""
    return {
        "readiness": rdy.get("score") if rdy else None,
        "readiness_level": rdy.get("level") if rdy else None,
        "acwr": ts.get("acwr_ratio") if ts else None,
    }


def _state_reasons(rdy: dict | None, ts: dict | None) -> list[str]:
    """Readiness + ACWR as plain chips, regardless of whether they tripped a
    threshold. Used by the statuses that report state rather than warn about
    it (GO, DONE) — the CAUTION/EASY path uses the signal reasons instead,
    which only speak up when something is actually off."""
    out = []
    if rdy and rdy.get("score") is not None:
        out.append(f"Readiness {rdy['score']} ({(rdy.get('level') or '').lower()})")
    if ts and ts.get("acwr_ratio") is not None:
        out.append(f"ACWR {ts['acwr_ratio']:.2f} ({(ts.get('acwr_status') or '').lower()})")
    return out


def daily_recommendation(
    conn: sqlite3.Connection,
    today: date | None = None,
) -> dict[str, Any] | None:
    """Build today's coaching recommendation, or None if there's no active plan
    or no planned workout for today."""
    today = today or date.today()
    today_iso = today.isoformat()

    todays_workout = plan_service.todays_workout(conn)
    if not todays_workout:
        return None

    rdy = _latest_readiness(conn)
    ts = _latest_training_status(conn)

    rdy_color, rdy_reason = _readiness_signal(rdy)
    acwr_color, acwr_reason = _acwr_signal(ts)

    wtype = todays_workout["workout_type"]

    if wtype in ("rest", "cross"):
        return {
            "status": "rest",
            "headline": "Rest day — recovery is part of the plan.",
            "reasons": [],
            "suggestion": None,
            "signals": _signals(rdy, ts),
        }

    # Already run. Readiness and ACWR now reflect the *cost* of the session
    # that just happened — a hard interval day tanks readiness and spikes the
    # acute load by design. Feeding those into the swap rules produces the
    # absurd "swap today's quality session for an easy run" on a session
    # that's already in the log, which is both too late to act on and reads
    # as though the run belonged to some earlier day. Report the state, drop
    # the prescription.
    if todays_workout.get("actual_activity_id"):
        return {
            "status": "done",
            # "session" keeps the agreement right for the plural types
            # ("today's intervals session", not "today's intervals is").
            "headline": f"Today's {wtype} session is logged — recovery from here.",
            "reasons": _state_reasons(rdy, ts),
            "suggestion": None,
            "signals": _signals(rdy, ts),
        }

    overall = _combine([rdy_color, acwr_color])

    reasons = [r for r in (rdy_reason, acwr_reason) if r]

    if overall == "go":
        if rdy and rdy.get("score", 0) >= 75:
            headline = f"Well recovered — go execute today's {wtype}."
        else:
            headline = f"Cleared for today's {wtype}."
        return {
            "status": "go",
            "headline": headline,
            "reasons": _state_reasons(rdy, ts),
            "suggestion": None,
            "signals": _signals(rdy, ts),
        }

    # CAUTION or EASY
    headline = (
        "Take it easy today." if overall == "easy"
        else f"Caution on today's {wtype}."
    )
    return {
        "status": overall,
        "headline": headline,
        "reasons": reasons,
        "suggestion": _swap_suggestion(wtype, overall),
        "signals": _signals(rdy, ts),
    }
