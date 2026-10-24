"""Persistence + read helpers for strength sessions.

Sits between the SQL tables (``strength_workouts``, ``plan_strength_sessions``)
and the web layer. The library seeder runs idempotently on first
``connect()`` so a fresh DB ships with the five canonical sessions.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from typing import Any

from . import library
from ..garmin_state import release_garmin_copy


def seed_library_if_empty(conn: sqlite3.Connection) -> int:
    """Populate ``strength_workouts`` from ``library.LIBRARY`` when the
    table is empty. Called once on connect — safe to re-run because of
    the empty-check + the ``UNIQUE`` constraint on ``slug``.

    Returns the number of rows inserted (0 on subsequent calls).
    """
    row = conn.execute("SELECT COUNT(*) AS n FROM strength_workouts").fetchone()
    if row and row["n"] > 0:
        return 0
    n = 0
    for w in library.LIBRARY:
        structure = json.dumps({"blocks": w["blocks"]})
        conn.execute(
            """INSERT OR IGNORE INTO strength_workouts
               (slug, title, category, duration_min_lo, duration_min_hi,
                equipment, notes, structure)
               VALUES (?, ?, ?, ?, ?, 'bodyweight', ?, ?)""",
            (
                w["slug"], w["title"], w["category"],
                w["duration_min_lo"], w["duration_min_hi"],
                w.get("notes"), structure,
            ),
        )
        n += 1
    conn.commit()
    return n


# ── plan_strength_sessions CRUD ───────────────────────────────────────

def sessions_for_plan(
    conn: sqlite3.Connection,
    plan_id: int,
) -> list[dict]:
    """Return all strength sessions attached to a plan, ordered by date.
    Joins to the library so callers see title/duration immediately."""
    rows = conn.execute(
        """SELECT pss.id AS session_id,
                  pss.plan_id, pss.planned_date, pss.completed_at, pss.notes,
                  sw.id AS workout_id, sw.slug, sw.title, sw.category,
                  sw.duration_min_lo, sw.duration_min_hi, sw.structure
           FROM plan_strength_sessions pss
           JOIN strength_workouts sw ON sw.id = pss.strength_workout_id
           WHERE pss.plan_id = ?
           ORDER BY pss.planned_date""",
        (plan_id,),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        try:
            d["structure"] = json.loads(d["structure"])
        except (json.JSONDecodeError, TypeError):
            d["structure"] = {"blocks": []}
        out.append(d)
    return out


def sessions_by_date_for_plan(
    conn: sqlite3.Connection,
    plan_id: int,
) -> dict[str, dict]:
    """Convenience: same as `sessions_for_plan` but keyed by
    `planned_date` so the week-card template can lookup in O(1)
    per day cell."""
    return {s["planned_date"]: s for s in sessions_for_plan(conn, plan_id)}


def get_session(conn: sqlite3.Connection, session_id: int) -> dict | None:
    """Return one strength session with the library workout fields + any
    matched-activity actuals (duration, avg HR, max HR, calories) joined
    via `actual_activity_id`. Actuals are None when no activity is
    matched yet."""
    rows = conn.execute(
        """SELECT pss.id AS session_id,
                  pss.plan_id, pss.planned_date, pss.completed_at, pss.notes,
                  pss.garmin_workout_id, pss.pushed_at, pss.actual_activity_id,
                  sw.id AS workout_id, sw.slug, sw.title, sw.category,
                  sw.duration_min_lo, sw.duration_min_hi, sw.structure,
                  a.duration_s       AS actual_duration_s,
                  a.distance_m       AS actual_distance_m,
                  a.avg_hr           AS actual_avg_hr,
                  a.max_hr           AS actual_max_hr,
                  a.calories         AS actual_calories,
                  a.training_load    AS actual_training_load,
                  a.start_time_local AS actual_start_local,
                  a.hr_zone_1_s, a.hr_zone_2_s, a.hr_zone_3_s,
                  a.hr_zone_4_s, a.hr_zone_5_s
           FROM plan_strength_sessions pss
           JOIN strength_workouts sw ON sw.id = pss.strength_workout_id
           LEFT JOIN activities a ON a.activity_id = pss.actual_activity_id
           WHERE pss.id = ?""",
        (session_id,),
    ).fetchall()
    if not rows:
        return None
    d = dict(rows[0])
    try:
        d["structure"] = json.loads(d["structure"])
    except (json.JSONDecodeError, TypeError):
        d["structure"] = {"blocks": []}
    return d


def todays_strength_session(conn: sqlite3.Connection) -> dict | None:
    """The active plan's strength session scheduled for today, if any.

    Returns the full `get_session` shape (library fields + matched-activity
    actuals + push state) so the dashboard flagship can render the card and
    flip to a done summary once the session is completed or matched. Returns
    None when no plan is active, optional strength is off, or today is a
    plain rest day with no session attached."""
    today = date.today().isoformat()
    row = conn.execute(
        """SELECT pss.id AS session_id
           FROM plan_strength_sessions pss
           JOIN plans p ON p.id = pss.plan_id
           WHERE p.status = 'active' AND pss.planned_date = ?
           LIMIT 1""",
        (today,),
    ).fetchone()
    if not row:
        return None
    return get_session(conn, row["session_id"])


def mark_complete(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute(
        "UPDATE plan_strength_sessions SET completed_at = datetime('now') "
        "WHERE id = ? AND completed_at IS NULL",
        (session_id,),
    )
    conn.commit()


def mark_incomplete(conn: sqlite3.Connection, session_id: int) -> None:
    """Toggle the other way — useful when the runner accidentally taps
    Complete or wants to re-do the session."""
    conn.execute(
        "UPDATE plan_strength_sessions SET completed_at = NULL WHERE id = ?",
        (session_id,),
    )
    conn.commit()


def clear_future_sessions(
    conn: sqlite3.Connection,
    plan_id: int,
    today_iso: str,
    client=None,
) -> dict:
    """Drop upcoming sessions when ``include_optional_strength`` goes OFF.

    Returns ``{"deleted": n, "kept_completed": n, "kept_pushed": n}``.

    Two things are never deleted:

    * **A completed session**, including one completed *today*. The old
      predicate was ``planned_date >= today`` with no ``completed_at`` check,
      so flipping the toggle off in the evening erased a session the runner
      had finished that morning. Training history is not regeneratable.
    * **A session still on the watch that Garmin won't release.** Deleting the
      row discards ``garmin_workout_id``, which is the only handle to that
      copy — it would stay scheduled on the watch forever, and re-enabling
      strength would push a second one onto the same day.

    Pass ``client`` to release pushed sessions from Garmin first. Without one,
    pushed rows are kept and reported so the caller can tell the runner.
    """
    rows = conn.execute(
        "SELECT id, garmin_workout_id, completed_at FROM plan_strength_sessions "
        "WHERE plan_id = ? AND planned_date >= ?",
        (plan_id, today_iso),
    ).fetchall()

    deleted = kept_completed = kept_pushed = 0
    for r in rows:
        if r["completed_at"]:
            kept_completed += 1
            continue
        if r["garmin_workout_id"] is not None:
            if not release_garmin_copy(client, r["garmin_workout_id"]):
                kept_pushed += 1
                continue
        conn.execute(
            "DELETE FROM plan_strength_sessions WHERE id = ?", (r["id"],)
        )
        deleted += 1
    conn.commit()
    return {
        "deleted": deleted,
        "kept_completed": kept_completed,
        "kept_pushed": kept_pushed,
    }


def upsert_session(
    conn: sqlite3.Connection,
    plan_id: int,
    planned_date: str,
    workout_slug: str,
) -> None:
    """Set or replace the strength session attached to one rest day.
    `(plan_id, planned_date)` is unique by schema, so we INSERT OR
    REPLACE to make the scheduler idempotent."""
    row = conn.execute(
        "SELECT id FROM strength_workouts WHERE slug = ?", (workout_slug,)
    ).fetchone()
    if not row:
        raise ValueError(f"unknown strength workout slug: {workout_slug}")
    conn.execute(
        """INSERT INTO plan_strength_sessions
           (plan_id, strength_workout_id, planned_date)
           VALUES (?, ?, ?)
           ON CONFLICT(plan_id, planned_date) DO UPDATE SET
               strength_workout_id = excluded.strength_workout_id""",
        (plan_id, row["id"], planned_date),
    )
    conn.commit()
