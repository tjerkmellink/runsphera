"""Rotation scheduler for optional strength sessions.

Walks a plan's rest days and assigns one strength session per day, in a
fixed rotation across the four "active" library entries (Core+Hamstrings,
Full Body, Hip Stability, Plyo). Recovery & Mobility is *not* in the
default rotation — it gets pulled forward whenever yesterday was a
quality session (tempo / intervals / long / race), so the day after
hard running stays light.

Idempotent: re-running with the same `(plan_id, today_iso)` produces
the same assignments. The service layer uses
`INSERT OR REPLACE ON CONFLICT(plan_id, planned_date)` so previous
assignments for the same day get overwritten cleanly.
"""
from __future__ import annotations

import sqlite3
from datetime import date

from . import library, service


# Workout types that trigger a "recovery & mobility" override on the
# *next* rest day. Anything else (easy, recovery-run, etc.) lets the
# normal rotation continue.
_QUALITY_TYPES = frozenset({"tempo", "intervals", "long", "race"})


def assign_for_plan(
    conn: sqlite3.Connection,
    plan_id: int,
    *,
    today_iso: str | None = None,
    overwrite_future: bool = True,
) -> int:
    """Walk every *future* rest day of the plan and stamp a strength
    session onto it, in rotation. When the previous-day workout was a
    quality session (tempo / intervals / long / race), the rest day
    gets ``recovery_mobility`` instead — that's the "easy day after
    hard day" coaching rule.

    Set ``overwrite_future=False`` to only fill empty days (don't
    replace sessions the runner already swapped manually).

    Returns the number of sessions written.
    """
    today_iso = today_iso or date.today().isoformat()

    rows = conn.execute(
        """SELECT pw.id, pw.planned_date, pw.workout_type
           FROM plan_workouts pw
           WHERE pw.plan_id = ?
             AND pw.planned_date >= ?
           ORDER BY pw.planned_date, pw.day_of_week""",
        (plan_id, today_iso),
    ).fetchall()
    workouts = [dict(r) for r in rows]
    if not workouts:
        return 0

    # We need yesterday's workout type to decide on the recovery override
    # for the FIRST future rest day, so reach back one day past today.
    prev_row = conn.execute(
        """SELECT workout_type FROM plan_workouts
           WHERE plan_id = ? AND planned_date < ?
           ORDER BY planned_date DESC LIMIT 1""",
        (plan_id, today_iso),
    ).fetchone()
    prev_type = prev_row["workout_type"] if prev_row else None

    # Existing assignments (so we can honor overwrite_future=False).
    existing_dates = (
        set()
        if overwrite_future
        else {
            r["planned_date"]
            for r in conn.execute(
                "SELECT planned_date FROM plan_strength_sessions "
                "WHERE plan_id = ? AND planned_date >= ?",
                (plan_id, today_iso),
            ).fetchall()
        }
    )

    rotation = library.ROTATION_SLUGS
    rotation_i = _initial_rotation_offset(conn, plan_id, today_iso, rotation)
    n_written = 0

    for w in workouts:
        if w["workout_type"] != "rest":
            prev_type = w["workout_type"]
            continue
        if w["planned_date"] in existing_dates:
            # User-customized this day — leave it.
            prev_type = w["workout_type"]
            continue

        if prev_type in _QUALITY_TYPES:
            slug = library.RECOVERY_SLUG
        else:
            slug = rotation[rotation_i % len(rotation)]
            rotation_i += 1

        service.upsert_session(conn, plan_id, w["planned_date"], slug)
        n_written += 1
        prev_type = w["workout_type"]

    return n_written


def _initial_rotation_offset(
    conn: sqlite3.Connection,
    plan_id: int,
    today_iso: str,
    rotation: list[str],
) -> int:
    """Pick up where the previous rotation left off so re-running the
    scheduler doesn't reset the cycle every time. Looks at the most
    recent past session in the rotation; if found, starts at the next
    slug. Otherwise starts at 0.
    """
    row = conn.execute(
        """SELECT sw.slug
           FROM plan_strength_sessions pss
           JOIN strength_workouts sw ON sw.id = pss.strength_workout_id
           WHERE pss.plan_id = ? AND pss.planned_date < ?
             AND sw.slug != ?
           ORDER BY pss.planned_date DESC LIMIT 1""",
        (plan_id, today_iso, library.RECOVERY_SLUG),
    ).fetchone()
    if not row:
        return 0
    try:
        last_i = rotation.index(row["slug"])
        return (last_i + 1) % len(rotation)
    except ValueError:
        return 0
