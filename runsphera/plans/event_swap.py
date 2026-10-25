"""Splice a calendar race event into the active training plan.

The bridge between `race_events` (the /calendar catalogue) and
`plan_workouts` (the active schedule). A swap always places the race on the
plan row at the event's date — every calendar day has a row, rest days
included — and optionally converts one other session that week (typically
the long run the runner is giving up) into a rest day.

Both overwritten rows are snapshotted as JSON in `plan_event_swaps`, so the
whole operation is reversible with one action from the plan-workout modal.
See docs/event-swap.md.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date

from .. import race_calendar
from ..garmin_state import release_garmin_copy

# Everything a swap may overwrite — and therefore everything a revert restores.
_BACKUP_FIELDS = (
    "workout_type", "title", "description", "target_distance_km",
    "target_duration_s", "target_pace_s_per_km", "workout_structure",
)

# Sessions worth offering as "give this up for the race". Rest/cross carry no
# running load to trade; race rows (goal race or an earlier swap) are locked.
_SWAPPABLE_TYPES = ("easy", "tempo", "intervals", "long", "recovery")


# ---- reads -------------------------------------------------------------

def _swap_row(row: sqlite3.Row | None) -> dict | None:
    if not row:
        return None
    d = dict(row)
    for key in ("race_original_json", "displaced_original_json"):
        try:
            d[key.replace("_json", "")] = json.loads(d[key]) if d.get(key) else None
        except (TypeError, ValueError):
            d[key.replace("_json", "")] = None
    return d


def get_swap_for_event(conn: sqlite3.Connection, event_id: int, plan_id: int) -> dict | None:
    return _swap_row(conn.execute(
        "SELECT * FROM plan_event_swaps WHERE event_id = ? AND plan_id = ?",
        (event_id, plan_id),
    ).fetchone())


def get_swap_for_workout(conn: sqlite3.Connection, workout_id: int) -> dict | None:
    """The swap a plan row is involved in (as the race or as the freed-up
    session), joined with the event, for the plan-workout modal. Adds a
    `role` key: 'race' | 'displaced'."""
    swap = _swap_row(conn.execute(
        """SELECT s.*, re.name AS event_name, re.race_date AS event_date,
                  re.city AS event_city
           FROM plan_event_swaps s
           JOIN race_events re ON re.id = s.event_id
           WHERE s.race_workout_id = ? OR s.displaced_workout_id = ?""",
        (workout_id, workout_id),
    ).fetchone())
    if swap:
        swap["role"] = "race" if swap["race_workout_id"] == workout_id else "displaced"
    return swap


def _workout_ids_in_swaps(conn: sqlite3.Connection, plan_id: int) -> set[int]:
    rows = conn.execute(
        "SELECT race_workout_id, displaced_workout_id FROM plan_event_swaps WHERE plan_id = ?",
        (plan_id,),
    ).fetchall()
    ids: set[int] = set()
    for r in rows:
        ids.add(r["race_workout_id"])
        if r["displaced_workout_id"]:
            ids.add(r["displaced_workout_id"])
    return ids


def swap_context(
    conn: sqlite3.Connection,
    plan: dict | None,
    event: dict,
    today_iso: str | None = None,
) -> dict | None:
    """Eligibility + candidates for swapping `event` into `plan`.

    Returns None when there is no plan to swap into. Otherwise:
        {
          "swapped":  existing swap row for this event+plan, or None,
          "eligible": bool,
          "reason":   None | 'past' | 'outside_window' | 'goal_race_day'
                    | 'day_completed' | 'day_taken',
          "target":   the plan row on the event's date (the row the race
                      lands on), or None,
          "extra_candidates": same-week future sessions that could be freed
                      up in addition (excludes the target row),
          "proposed_extra_id": default pick for the candidates — that week's
                      long run — or None,
        }
    """
    if not plan:
        return None
    if today_iso is None:
        today_iso = date.today().isoformat()
    event_date = (event.get("race_date") or "")[:10]

    ctx: dict = {
        "swapped": get_swap_for_event(conn, event["id"], plan["id"]),
        "eligible": False,
        "reason": None,
        "target": None,
        "extra_candidates": [],
        "proposed_extra_id": None,
    }
    if ctx["swapped"]:
        return ctx

    if event_date < today_iso:
        ctx["reason"] = "past"
        return ctx
    if plan.get("race_date") and event_date == plan["race_date"]:
        ctx["reason"] = "goal_race_day"
        return ctx

    target = conn.execute(
        "SELECT * FROM plan_workouts WHERE plan_id = ? AND planned_date = ? "
        "ORDER BY id LIMIT 1",
        (plan["id"], event_date),
    ).fetchone()
    if not target:
        ctx["reason"] = "outside_window"
        return ctx
    target = dict(target)
    ctx["target"] = target

    if target.get("actual_activity_id"):
        ctx["reason"] = "day_completed"
        return ctx
    taken = _workout_ids_in_swaps(conn, plan["id"])
    if target["id"] in taken or target["workout_type"] == "race":
        ctx["reason"] = "day_taken"
        return ctx

    candidates = [dict(r) for r in conn.execute(
        f"""SELECT * FROM plan_workouts
            WHERE plan_id = ? AND week_number = ? AND id != ?
              AND planned_date >= ? AND actual_activity_id IS NULL
              AND workout_type IN ({','.join('?' * len(_SWAPPABLE_TYPES))})
            ORDER BY planned_date""",
        (plan["id"], target["week_number"], target["id"], today_iso,
         *_SWAPPABLE_TYPES),
    ).fetchall()]
    candidates = [c for c in candidates if c["id"] not in taken]
    ctx["extra_candidates"] = candidates
    # Propose freeing up the week's long run — unless the race already lands
    # on it (then the one-row swap is exactly what the runner asked for).
    if target["workout_type"] != "long":
        long_run = next((c for c in candidates if c["workout_type"] == "long"), None)
        if long_run:
            ctx["proposed_extra_id"] = long_run["id"]
    ctx["eligible"] = True
    return ctx


# ---- writes ------------------------------------------------------------

def _backup(row: dict) -> str:
    return json.dumps({f: row.get(f) for f in _BACKUP_FIELDS})


def _clear_and_collect_garmin(row: dict) -> int | None:
    """Garmin workout id to delete best-effort, if the row was pushed."""
    return row.get("garmin_workout_id") or None


def apply_swap(
    conn: sqlite3.Connection,
    client,
    *,
    event_id: int,
    distance_km: float,
    distance_label: str | None = None,
    displaced_workout_id: int | None = None,
) -> dict:
    """Place `event` on the active plan as a race workout.

    The plan row on the event's date becomes the race. When
    `displaced_workout_id` names another (future, uncompleted) session in the
    same week, that session becomes a rest day — "swap my long run for this
    event". Originals are snapshotted into `plan_event_swaps` for revert.

    Pushed-to-Garmin copies of the overwritten rows are deleted best-effort
    (`client` may be None). The event is also saved to the runner's calendar
    (`runner_races`) if it wasn't already.
    """
    from .service import get_active_plan  # local import — avoids cycle at module load

    event = race_calendar.get_event(conn, event_id)
    if not event:
        raise ValueError("event not found")
    plan = get_active_plan(conn)
    ctx = swap_context(conn, plan, event)
    if ctx is None:
        raise ValueError("no active plan to swap into")
    if ctx["swapped"]:
        raise ValueError("this event is already in the plan")
    if not ctx["eligible"]:
        reasons = {
            "past": "the event date is in the past",
            "goal_race_day": "that date is the plan's goal race day",
            "outside_window": "the event date falls outside the plan",
            "day_completed": "that day's workout is already completed",
            "day_taken": "that day already holds a race",
        }
        raise ValueError(reasons.get(ctx["reason"], "event can't be swapped into the plan"))

    target = ctx["target"]
    displaced = None
    if displaced_workout_id and displaced_workout_id != target["id"]:
        displaced = next(
            (c for c in ctx["extra_candidates"] if c["id"] == displaced_workout_id),
            None,
        )
        if not displaced:
            raise ValueError("the workout to give up is not a valid candidate")

    label = distance_label or f"{distance_km:g} km"
    title = f"🏁 {event['name']} — {label}"
    where = f" ({event['city']})" if event.get("city") else ""
    description = (
        f"Race event from your calendar: {event['name']}{where}, {label}. "
        f"Replaces: {target['title']}."
        + (f" Also freed up: {displaced['title']}." if displaced else "")
    )

    stale_garmin = [g for g in (
        _clear_and_collect_garmin(target),
        _clear_and_collect_garmin(displaced) if displaced else None,
    ) if g]

    # Release each Garmin copy *before* touching push state. Clearing the id
    # first — as this did — threw away the only handle to a workout still
    # scheduled on the watch, and the swap snapshots don't carry ids, so
    # neither revert nor any later cleanup could recover it.
    released_ids = {gid for gid in stale_garmin if release_garmin_copy(client, gid)}

    conn.execute(
        """UPDATE plan_workouts SET
              workout_type = 'race', title = ?, description = ?,
              target_distance_km = ?, target_duration_s = NULL,
              target_pace_s_per_km = NULL, workout_structure = NULL
           WHERE id = ?""",
        (title, description, distance_km, target["id"]),
    )
    if displaced:
        conn.execute(
            """UPDATE plan_workouts SET
                  workout_type = 'rest', title = 'Rest', description = ?,
                  target_distance_km = NULL, target_duration_s = NULL,
                  target_pace_s_per_km = NULL, workout_structure = NULL
               WHERE id = ?""",
            (f"Freed up for race: {event['name']}.", displaced["id"]),
        )

    # Clear push state only where Garmin confirmed the delete. A row that
    # kept its id still points at a real workout on the watch — and a
    # displaced long run left scheduled on what is now a rest day is exactly
    # the sort of thing the runner needs told about.
    for row in (target, displaced):
        if not row:
            continue
        gid = row.get("garmin_workout_id")
        if gid is None or gid in released_ids:
            conn.execute(
                "UPDATE plan_workouts SET garmin_workout_id = NULL, pushed_at = NULL "
                "WHERE id = ?",
                (row["id"],),
            )
        else:
            conn.execute(
                "UPDATE plan_workouts SET pushed_at = NULL WHERE id = ?",
                (row["id"],),
            )
    cur = conn.execute(
        """INSERT INTO plan_event_swaps
             (plan_id, event_id, race_workout_id, displaced_workout_id,
              race_original_json, displaced_original_json,
              chosen_distance_km, chosen_distance_label)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (plan["id"], event_id, target["id"],
         displaced["id"] if displaced else None,
         _backup(target), _backup(displaced) if displaced else None,
         distance_km, label),
    )
    swap_id = cur.lastrowid
    # Keep "Your races" on /calendar in sync. No plan_id on the row — the
    # plan link lives in plan_event_swaps; runner_races.plan_id is reserved
    # for the A-race that drives the dashboard countdown.
    if not race_calendar.is_favorited(conn, event_id):
        race_calendar.favorite(
            conn, event_id,
            chosen_distance_km=distance_km, chosen_distance_label=label,
        )
    conn.commit()

    return {
        "swapped": True,
        # Copies Garmin would not release: still on the watch, ids retained.
        "garmin_stale": len([g for g in stale_garmin if g not in released_ids]),
        "swap_id": swap_id,
        "race_workout_id": target["id"],
        "displaced_workout_id": displaced["id"] if displaced else None,
    }


def revert_swap(conn: sqlite3.Connection, client, swap_id: int) -> dict:
    """Undo a swap: restore both plan rows from their snapshots and delete
    the swap record. Refused when the race has already been run (the matched
    activity is the source of truth). A completed displaced row (the runner
    logged something on the freed day anyway) is left as-is."""
    swap = _swap_row(conn.execute(
        "SELECT * FROM plan_event_swaps WHERE id = ?", (swap_id,)
    ).fetchone())
    if not swap:
        raise ValueError("swap not found")

    race_row = conn.execute(
        "SELECT * FROM plan_workouts WHERE id = ?", (swap["race_workout_id"],)
    ).fetchone()
    restored: list[int] = []
    stale_garmin: list[int] = []

    def _restore(row: sqlite3.Row | None, original: dict | None) -> None:
        if row is None or not original:
            return
        row = dict(row)
        if row.get("actual_activity_id"):
            return  # completed — never rewrite history
        # Same rule as apply_swap: confirm the delete before discarding the
        # handle, or the restored row claims a clean watch while the swapped
        # shape is still scheduled on it.
        gid = row.get("garmin_workout_id")
        released = release_garmin_copy(client, gid) if gid else True
        if gid and not released:
            stale_garmin.append(gid)
        conn.execute(
            """UPDATE plan_workouts SET
                  workout_type = ?, title = ?, description = ?,
                  target_distance_km = ?, target_duration_s = ?,
                  target_pace_s_per_km = ?, workout_structure = ?
               WHERE id = ?""",
            (*(original.get(f) for f in _BACKUP_FIELDS), row["id"]),
        )
        if released:
            conn.execute(
                "UPDATE plan_workouts SET garmin_workout_id = NULL, pushed_at = NULL "
                "WHERE id = ?",
                (row["id"],),
            )
        else:
            conn.execute(
                "UPDATE plan_workouts SET pushed_at = NULL WHERE id = ?",
                (row["id"],),
            )
        restored.append(row["id"])

    if race_row and dict(race_row).get("actual_activity_id"):
        raise ValueError("the race is already completed — restoring is not possible")
    _restore(race_row, swap["race_original"])
    if swap["displaced_workout_id"]:
        displaced_row = conn.execute(
            "SELECT * FROM plan_workouts WHERE id = ?", (swap["displaced_workout_id"],)
        ).fetchone()
        _restore(displaced_row, swap["displaced_original"])

    conn.execute("DELETE FROM plan_event_swaps WHERE id = ?", (swap_id,))
    conn.commit()

    return {
        "reverted": True,
        "restored_workout_ids": restored,
        # Copies Garmin would not release; their ids are retained on the rows.
        "garmin_stale": len(stale_garmin),
    }
