"""Persistence + orchestration for training plans.

Reads from the existing dashboard data (VO₂max, recent activity volume) to seed plan
generation, then writes plans + workouts atomically. Creating a new plan deactivates
the previous active plan in the same transaction.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from typing import Any

from . import get_methodology, get_methodology_info, list_methodologies
from . import coach as plan_coach
from . import swapper as plan_swapper
from ._structure import totals_from_structure as _totals_from_structure_shared
from ..garmin_state import push_lock, release_garmin_copy
from .garmin_sync import is_pushable, planned_to_garmin_workout, push_status
from .methodology import GOAL_DISTANCES_KM, GOAL_LABELS, GOAL_TYPES, PlanParams


def _garmin_vdot(conn: sqlite3.Connection) -> float | None:
    row = conn.execute(
        "SELECT vo2max_precise FROM training_status "
        "WHERE vo2max_precise IS NOT NULL ORDER BY calendar_date DESC LIMIT 1"
    ).fetchone()
    return float(row["vo2max_precise"]) if row else None


def _manual_baseline(conn: sqlite3.Connection) -> dict:
    from .. import settings as app_settings
    return app_settings.get_fitness_baseline(conn)


def _current_vdot(conn: sqlite3.Connection, default: float = 45.0) -> float:
    """Best-available VDOT: Garmin-measured → manually entered → default."""
    measured = _garmin_vdot(conn)
    if measured is not None:
        return measured
    manual = _manual_baseline(conn)["vdot"]
    return float(manual) if manual else default


def _garmin_weekly_km(conn: sqlite3.Connection) -> float:
    """Mean weekly running km over the last 4 complete weeks (0 when no data)."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    window_start = (monday - timedelta(weeks=4)).isoformat()
    window_end = monday.isoformat()
    row = conn.execute(
        """SELECT COALESCE(SUM(distance_m), 0) / 1000.0 / 4.0 AS avg_km
           FROM activities
           WHERE activity_type = 'running'
             AND date(start_time_local) >= ?
             AND date(start_time_local) <  ?""",
        (window_start, window_end),
    ).fetchone()
    return float(row["avg_km"] or 0)


def _weekly_km_baseline(conn: sqlite3.Connection, default: float = 25.0) -> float:
    """Weekly-volume seed: measured 4-week average when it's meaningful
    (≥5 km/wk), else the runner's self-reported volume, else the default."""
    avg = _garmin_weekly_km(conn)
    if avg >= 5:
        return avg
    manual = _manual_baseline(conn)["weekly_km"]
    if manual and manual >= 5:
        return float(manual)
    return default


def get_plan_seed(conn: sqlite3.Connection) -> dict:
    """What we know about the runner right now, used to pre-fill the create
    form and seed generation. Alongside each value, `*_source` says where it
    came from — 'garmin' (measured), 'manual' (runner-entered), or 'default'
    (a guess) — so the UI can be honest instead of presenting a hardcoded
    fallback as a measurement. `vdot_note` is the human basis of a manual
    VDOT ("10 km in 52:30")."""
    manual = _manual_baseline(conn)

    measured_vdot = _garmin_vdot(conn)
    if measured_vdot is not None:
        vdot, vdot_source = measured_vdot, "garmin"
    elif manual["vdot"]:
        vdot, vdot_source = float(manual["vdot"]), "manual"
    else:
        vdot, vdot_source = 45.0, "default"

    avg = _garmin_weekly_km(conn)
    if avg >= 5:
        weekly_km, weekly_km_source = avg, "garmin"
    elif manual["weekly_km"] and manual["weekly_km"] >= 5:
        weekly_km, weekly_km_source = float(manual["weekly_km"]), "manual"
    else:
        weekly_km, weekly_km_source = 25.0, "default"

    return {
        "current_vdot": vdot,
        "vdot_source": vdot_source,
        "vdot_note": manual["vdot_note"] if vdot_source == "manual" else None,
        "weekly_km_baseline": round(weekly_km, 1),
        "weekly_km_source": weekly_km_source,
    }


def _derive_fixed_schedule(
    workouts: list, race_date: date | None
) -> tuple[list[int] | None, int | None, int | None]:
    """For fixed-schedule methodologies: read the real weekly schedule off the
    generated workouts so the plans row never contradicts the plan_workouts.

    Returns (workout_days, days_per_week, long_run_day) — any element None
    when it can't be derived. The most common weekly run-day pattern wins;
    the long-run day is the race weekday (the anchor these engines build
    around)."""
    from collections import Counter
    week_days: dict[int, set[int]] = {}
    for w in workouts:
        if w.workout_type not in ("rest", "cross"):
            week_days.setdefault(w.week_number, set()).add(w.day_of_week)
    workout_days = days_per_week = None
    if week_days:
        pattern = Counter(frozenset(s) for s in week_days.values()).most_common(1)[0][0]
        workout_days = sorted(pattern)
        days_per_week = len(pattern)
    long_run_day = race_date.weekday() if race_date is not None else None
    return workout_days, days_per_week, long_run_day


def _baseline_from_notes(notes: str | None) -> float | None:
    """Recover the creation-time weekly-km baseline that create_plan bakes
    into the plan notes ("baseline 35.0 km/wk, VDOT 49.0"). Reshaping reuses
    it so future volumes stay on the plan's original trajectory instead of
    re-ramping from today's (possibly much higher) mileage."""
    if not notes:
        return None
    m = re.search(r"baseline\s+([\d.]+)\s*km/wk", notes)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def create_plan(
    conn: sqlite3.Connection,
    *,
    goal_type: str,
    methodology_id: str,
    race_date: date | None,
    target_time_s: int | None,
    days_per_week: int,
    long_run_day: int,
    workout_days: list[int] | None = None,
    title: str | None = None,
    variant: str | None = None,
    start_date: date | None = None,
) -> int:
    """Generate + persist a new plan. Deactivates the existing active plan in the same txn.

    `start_date` (a Monday; None ⇒ next Monday) lets the runner choose to
    start in the current week instead. Race goals no longer require a race
    date: without one, the plan runs the methodology's full default length
    from the start week and a goal date is synthesized on the final week's
    long-run day — the race-shaped finale stays, it's just not tied to a
    booked event yet."""
    if goal_type not in GOAL_TYPES:
        raise ValueError(f"unknown goal: {goal_type}")
    info = get_methodology_info(methodology_id)
    # Server-side enforcement of the methodology's declared allow-lists — the
    # form's goal-locking / variant pickers are JS-only and can be bypassed.
    if info.supported_goals and goal_type not in info.supported_goals:
        raise ValueError(
            f"the {info.name} methodology does not offer a '{goal_type}' plan"
        )
    if info.variants:
        valid_variants = {v[0] for v in info.variants}
        if variant is None:
            # Default to the first declared variant so the persisted label
            # always matches what the engine actually generates.
            variant = info.variants[0][0]
        elif variant not in valid_variants:
            raise ValueError(
                f"unknown {info.name} variant '{variant}' — "
                f"expected one of: {', '.join(sorted(valid_variants))}"
            )
    else:
        # Methodologies without variants never persist one (a no-JS form
        # submit can still POST the hidden picker's default).
        variant = None
    if info.fixed_schedule:
        # The methodology owns its schedule: ignore the submitted picks and
        # (after generation) persist what the engine actually produced, so the
        # plans row never contradicts the plan_workouts.
        workout_days = None
    else:
        if days_per_week not in (3, 4, 5, 6):
            raise ValueError("days_per_week must be 3-6")
        if long_run_day not in range(7):
            raise ValueError("long_run_day must be 0-6")
        if workout_days is not None:
            workout_days = sorted({int(d) for d in workout_days})
            if any(d not in range(7) for d in workout_days):
                raise ValueError("workout_days entries must be 0-6")
            if len(workout_days) != days_per_week:
                raise ValueError(
                    f"pick exactly {days_per_week} workout days (got {len(workout_days)})"
                )
            if long_run_day not in workout_days:
                raise ValueError("long run day must be one of the picked workout days")

    methodology = get_methodology(methodology_id)
    today = date.today()
    if start_date is None:
        start_date = today + timedelta(days=(7 - today.weekday()) % 7)  # next Monday
    start_monday = start_date - timedelta(days=start_date.weekday())

    if race_date is None and info.requires_race_date:
        raise ValueError(
            f"the {info.name} plan targets a specific race — a race date is required"
        )

    goal_date_synthesized = False
    if race_date is None and goal_type != "stay_fit":
        # No race booked: run the full default build and aim it at the final
        # week's long-run day. Persisted as the plan's race_date so pacing,
        # taper, and the race-day finale all work; the runner can swap in a
        # real event later (event-swap keeps the date honest).
        weeks = methodology.total_weeks(goal_type, None, start_date)
        race_date = start_monday + timedelta(weeks=weeks - 1, days=long_run_day)
        goal_date_synthesized = True

    seed = get_plan_seed(conn)
    params = PlanParams(
        goal_type=goal_type,
        start_date=start_date,
        race_date=race_date,
        target_time_s=target_time_s,
        days_per_week=days_per_week,
        long_run_day=long_run_day,
        current_vdot=seed["current_vdot"],
        weekly_km_baseline=seed["weekly_km_baseline"],
        workout_days=workout_days,
        variant=variant,
    )
    workouts = methodology.generate(params)

    if info.fixed_schedule:
        d_days, d_dpw, d_lrd = _derive_fixed_schedule(workouts, race_date)
        workout_days = d_days if d_days is not None else workout_days
        days_per_week = d_dpw if d_dpw is not None else days_per_week
        long_run_day = d_lrd if d_lrd is not None else long_run_day

    # Generate a default title
    if not title:
        if goal_type == "stay_fit":
            title = "Stay fit — rolling base"
        elif goal_date_synthesized:
            # No booked race — name the build by its length, not a date the
            # runner never picked.
            n_weeks = max(w.week_number for w in workouts)
            title = f"{GOAL_LABELS[goal_type]} · {n_weeks}-week build"
        elif race_date:
            title = f"{GOAL_LABELS[goal_type]} · {race_date.isoformat()}"
        else:
            title = GOAL_LABELS[goal_type]

    target_distance_km = GOAL_DISTANCES_KM.get(goal_type)

    try:
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE plans SET status = 'inactive', deactivated_at = datetime('now') "
            "WHERE status = 'active'"
        )
        workout_days_csv = (
            ",".join(str(d) for d in workout_days) if workout_days else None
        )
        cur = conn.execute(
            """INSERT INTO plans
               (goal_type, target_distance_km, race_date, target_time_s,
                methodology, days_per_week, long_run_day, workout_days,
                vdot_at_start, title, notes, variant, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                goal_type, target_distance_km,
                race_date.isoformat() if race_date else None,
                target_time_s, methodology_id, days_per_week, long_run_day,
                workout_days_csv,
                seed["current_vdot"], title,
                f"baseline {seed['weekly_km_baseline']:.1f} km/wk, VDOT {seed['current_vdot']:.1f}",
                variant,
            ),
        )
        plan_id = cur.lastrowid

        conn.executemany(
            """INSERT INTO plan_workouts
               (plan_id, week_number, week_phase, day_of_week, planned_date,
                workout_type, title, description,
                target_distance_km, target_duration_s, target_pace_s_per_km,
                workout_structure)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    plan_id, w.week_number, w.week_phase, w.day_of_week,
                    w.planned_date.isoformat(), w.workout_type, w.title, w.description,
                    w.target_distance_km, w.target_duration_s, w.target_pace_s_per_km,
                    json.dumps(w.workout_structure) if w.workout_structure else None,
                )
                for w in workouts
            ],
        )
        conn.execute("COMMIT")
        return plan_id
    except Exception:
        conn.execute("ROLLBACK")
        raise


def reshape_plan(
    conn: sqlite3.Connection,
    client,
    plan_id: int,
    *,
    race_date: date | None = None,
    days_per_week: int | None = None,
    long_run_day: int | None = None,
    workout_days: list[int] | None = None,
    today_iso: str | None = None,
) -> dict:
    """Change a plan's training days, long-run day, and/or race date by
    regenerating the plan and splicing the result into the future.

    The plan is regenerated in full (same methodology, same start week, the
    plan's own VDOT and creation-time baseline) with the new schedule params,
    then spliced by date: rows before today — and any already-completed rows —
    stay exactly as they are (history is never rewritten); everything from
    today onward is replaced. Previously pushed future workouts are deleted
    from Garmin best-effort (re-push the weeks you want on the watch).

    Args left as None keep the plan's current value. For fixed-schedule
    methodologies only the race date applies; the persisted schedule is
    re-derived from the generated workouts.

    Returns {"n_removed", "n_added", "n_kept_done", "garmin_cleaned",
    "garmin_failed", "total_weeks"}. Raises ValueError with a user-facing
    message when the new shape is invalid.
    """
    today_iso = today_iso or date.today().isoformat()
    plan = get_plan(conn, plan_id)
    if not plan:
        raise ValueError("plan not found")
    info = get_methodology_info(plan["methodology"])

    new_race = race_date if race_date is not None else (
        date.fromisoformat(plan["race_date"]) if plan["race_date"] else None
    )
    if plan["goal_type"] != "stay_fit" and new_race is None:
        raise ValueError("this goal needs a race date")
    if new_race is not None and new_race.isoformat() <= today_iso:
        raise ValueError("race date must be in the future")

    if info.fixed_schedule:
        # The methodology owns its schedule — only the race date can move.
        new_dpw = int(plan["days_per_week"])
        new_lrd = int(plan["long_run_day"])
        new_wdays = None
    else:
        new_dpw = int(days_per_week) if days_per_week is not None else int(plan["days_per_week"])
        new_lrd = int(long_run_day) if long_run_day is not None else int(plan["long_run_day"])
        if workout_days is not None:
            new_wdays = sorted({int(d) for d in workout_days})
        elif plan.get("workout_days"):
            new_wdays = sorted(int(d) for d in str(plan["workout_days"]).split(","))
        else:
            new_wdays = None
        if new_dpw not in (3, 4, 5, 6):
            raise ValueError("days_per_week must be 3-6")
        if new_lrd not in range(7):
            raise ValueError("long_run_day must be 0-6")
        if new_wdays is not None:
            if any(d not in range(7) for d in new_wdays):
                raise ValueError("workout_days entries must be 0-6")
            if len(new_wdays) != new_dpw:
                raise ValueError(
                    f"pick exactly {new_dpw} workout days (got {len(new_wdays)})"
                )
            if new_lrd not in new_wdays:
                raise ValueError("long run day must be one of the picked workout days")

    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM plan_workouts WHERE plan_id = ? ORDER BY planned_date",
        (plan_id,),
    ).fetchall()]
    if not rows:
        raise ValueError("plan has no workouts to reshape")
    first_date = date.fromisoformat(rows[0]["planned_date"])
    plan_start_monday = first_date - timedelta(days=first_date.weekday())

    seed = get_plan_seed(conn)
    baseline = _baseline_from_notes(plan.get("notes")) or seed["weekly_km_baseline"]
    vdot = float(plan["vdot_at_start"] or 0) or seed["current_vdot"]

    params = PlanParams(
        goal_type=plan["goal_type"],
        start_date=plan_start_monday,
        race_date=new_race,
        target_time_s=plan["target_time_s"],
        days_per_week=new_dpw,
        long_run_day=new_lrd,
        current_vdot=vdot,
        weekly_km_baseline=baseline,
        workout_days=new_wdays,
        variant=plan.get("variant"),
    )
    methodology = get_methodology(plan["methodology"])
    new_workouts = methodology.generate(params)

    # The splice relies on old and new plans sharing week-1's Monday: week
    # numbers then agree by construction. A race date far enough out that a
    # capped-length methodology would start later breaks that — refuse.
    new_first = min(w.planned_date for w in new_workouts)
    new_start_monday = new_first - timedelta(days=new_first.weekday())
    if new_start_monday != plan_start_monday:
        raise ValueError(
            "the new race date would shift the plan's start week — "
            "create a new plan instead"
        )
    if new_race is not None and not any(
        w.planned_date == new_race for w in new_workouts
    ):
        raise ValueError(
            "the race date falls outside this plan's span — create a new plan instead"
        )

    # Splice by date: history (and anything already completed) is untouchable.
    keep_done_dates: set[str] = set()
    to_delete: list[dict] = []
    for r in rows:
        if r["planned_date"] < today_iso:
            continue
        if r.get("actual_activity_id"):
            keep_done_dates.add(r["planned_date"])
            continue
        to_delete.append(r)

    # Reshape deletes these rows outright, so unlike edit/move/swap there is
    # no row left to hold the id — a failed delete is a permanent orphan on
    # Garmin. Count them so the route can tell the runner.
    garmin_cleaned = garmin_failed = 0
    for r in to_delete:
        gid = r.get("garmin_workout_id")
        if not gid:
            continue
        if release_garmin_copy(client, gid):
            garmin_cleaned += 1
        else:
            garmin_failed += 1

    inserts = [
        w for w in new_workouts
        if w.planned_date.isoformat() >= today_iso
        and w.planned_date.isoformat() not in keep_done_dates
    ]

    if info.fixed_schedule:
        d_days, d_dpw, d_lrd = _derive_fixed_schedule(new_workouts, new_race)
        new_wdays = d_days if d_days is not None else new_wdays
        new_dpw = d_dpw if d_dpw is not None else new_dpw
        new_lrd = d_lrd if d_lrd is not None else new_lrd

    try:
        conn.execute("BEGIN")
        conn.executemany(
            "DELETE FROM plan_workouts WHERE id = ?",
            [(r["id"],) for r in to_delete],
        )
        conn.executemany(
            """INSERT INTO plan_workouts
               (plan_id, week_number, week_phase, day_of_week, planned_date,
                workout_type, title, description,
                target_distance_km, target_duration_s, target_pace_s_per_km,
                workout_structure)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    plan_id, w.week_number, w.week_phase, w.day_of_week,
                    w.planned_date.isoformat(), w.workout_type, w.title, w.description,
                    w.target_distance_km, w.target_duration_s, w.target_pace_s_per_km,
                    json.dumps(w.workout_structure) if w.workout_structure else None,
                )
                for w in inserts
            ],
        )
        conn.execute(
            "UPDATE plans SET race_date = ?, days_per_week = ?, "
            "long_run_day = ?, workout_days = ? WHERE id = ?",
            (
                new_race.isoformat() if new_race else None,
                new_dpw, new_lrd,
                ",".join(str(d) for d in new_wdays) if new_wdays else None,
                plan_id,
            ),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # Rest days moved — re-stamp the optional strength rotation onto the new
    # future rest days (and clear sessions stranded on now-running days).
    if plan.get("include_optional_strength"):
        from running_coach.strength import scheduler as _sched
        from running_coach.strength import service as _strength_service
        # Pass the client: a pushed strength session has to come off Garmin
        # before its row goes, or it stays scheduled on the watch with nothing
        # left pointing at it.
        strength_cleared = _strength_service.clear_future_sessions(
            conn, plan_id, today_iso, client=client
        )
        garmin_failed += strength_cleared["kept_pushed"]
        _sched.assign_for_plan(conn, plan_id, today_iso=today_iso)

    total_weeks = max(w.week_number for w in new_workouts)
    return {
        "n_removed": len(to_delete),
        "n_added": len(inserts),
        "n_kept_done": len(keep_done_dates),
        "garmin_cleaned": garmin_cleaned,
        "garmin_failed": garmin_failed,
        "total_weeks": total_weeks,
    }


def deactivate_plan(conn: sqlite3.Connection, plan_id: int) -> None:
    conn.execute(
        "UPDATE plans SET status = 'inactive', deactivated_at = datetime('now') WHERE id = ?",
        (plan_id,),
    )
    conn.commit()


def reactivate_plan(conn: sqlite3.Connection, plan_id: int) -> None:
    """Make an archived plan the active one, swapping out any current active
    plan in the same transaction. Mirrors create()'s "only one active plan"
    invariant: every currently-active plan is demoted to inactive, then the
    target is promoted and its deactivated_at cleared.

    No data is touched beyond the status/deactivated_at columns — the swap is
    fully reversible.
    """
    try:
        conn.execute("BEGIN")
        conn.execute(
            "UPDATE plans SET status = 'inactive', deactivated_at = datetime('now') "
            "WHERE status = 'active' AND id != ?",
            (plan_id,),
        )
        conn.execute(
            "UPDATE plans SET status = 'active', deactivated_at = NULL WHERE id = ?",
            (plan_id,),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _zone_for_workout(workout: dict) -> str | None:
    """Map a workout to its canonical Daniels pace zone (E/M/T/I/R).

    Returns None for rest/cross days (no pace applies) and for race days —
    a race's target pace comes from the runner's goal time or race effort
    (Pfitzinger tune-ups are authored at T), not from a zone, so the
    recalibrator must leave it alone. Title-based overrides handle the
    engines' special variants — "Marathon-pace" tempos (Daniels) and the
    "Race-pace tune" dress rehearsal (Pfitzinger) run at M pace (not T),
    and taper "Strides" workouts run at R pace (not I). Without these
    overrides the recalibrator would silently shift those sessions into
    the wrong zone.
    """
    wtype = workout["workout_type"]
    if wtype in ("rest", "cross", "race"):
        return None
    title = (workout.get("title") or "").lower()
    if wtype == "intervals":
        # "Repetitions N×…" sessions (Daniels 5K speed work) run at R, like strides.
        return "R" if ("stride" in title or "repetition" in title) else "I"
    if wtype == "tempo":
        return "M" if ("marathon-pace" in title or "race-pace" in title) else "T"
    # easy, long, recovery
    return "E"


# Public alias. `plans.narrative` needs the *same* zone vocabulary the
# recalibrator uses — if the prose and the pace rewriter ever disagreed about
# what zone a session is, the modal would describe a workout the watch isn't
# running. One function, two readers.
zone_for_workout = _zone_for_workout


def _require_vdot_paces(methodology_id: str | None) -> None:
    """Refuse pace-rewriting operations on effort-based plans.

    Foppen and Couch-to-5K sessions are prescribed by duration and effort
    cues; stamping VDOT zone paces onto them would corrupt the plan.
    Unknown/legacy methodology ids are assumed pace-based (the historical
    behaviour) so old plans keep working.
    """
    if not methodology_id:
        return
    try:
        info = get_methodology_info(methodology_id)
    except ValueError:
        return
    if not info.uses_vdot_paces:
        raise ValueError(
            f"{info.name} plans are effort-based — their sessions carry no "
            "VDOT paces to recalibrate."
        )


_PACE_REFRESH_RE = re.compile(
    r"(?P<zlabel>\b(?P<zone>[EMTIR]) pace \(\d+:\d{2}/km\))"
    r"|(?P<zparen>\((?P<zone2>[EMTIR]), \d+:\d{2}/km\))"
    r"|(?P<paren>\(\d+:\d{2}/km\))"
    r"|(?P<bare>\b\d+:\d{2}/km\b)"
)


def _refresh_description_paces(
    description: str | None,
    paces: dict[str, int],
) -> str | None:
    """Rewrite stale pace numbers inside a workout's description text.

    The Daniels engine bakes the current pace into the description as plain
    text ("3 km @ T pace (4:11/km)", "Conversational aerobic, 5:21/km."). After
    a recalibrate or VDOT update, the numeric `target_pace_s_per_km` is
    refreshed but the description string keeps the old numbers — which then
    leaks into the LLM coach context and produces contradictory advice. We
    rewrite three patterns:

    - `E/M/T/I/R pace (X:XX/km)` — zone-labelled; rewrites to the current
      pace for that zone.
    - `(Z, X:XX/km)` — Pfitzinger's zone-labelled idiom ("lactate-threshold
      pace (T, 4:20/km)"); rewrites against the labelled zone.
    - `(X:XX/km)` — parenthesised, unlabelled; treated as easy/E pace
      (matches the engine's "First half easy (5:21/km), …" idiom).
    - `X:XX/km` — bare standalone; treated as easy/E pace.

    Returns the input unchanged when there's nothing to substitute or
    `description` is empty/None.
    """
    if not description:
        return description

    def _fmt(zone: str) -> str:
        s = paces.get(zone)
        return f"{s // 60}:{s % 60:02d}/km" if s else ""

    def _sub(m: re.Match) -> str:
        if m.group("zlabel"):
            zone = m.group("zone")
            new = _fmt(zone)
            return f"{zone} pace ({new})" if new else m.group(0)
        if m.group("zparen"):
            zone = m.group("zone2")
            new = _fmt(zone)
            return f"({zone}, {new})" if new else m.group(0)
        new_e = _fmt("E")
        if not new_e:
            return m.group(0)
        return f"({new_e})" if m.group("paren") else new_e

    return _PACE_REFRESH_RE.sub(_sub, description)


def _rewrite_structure_pace(
    structure: dict | None,
    new_pace_s: int,
    paces: dict[str, int] | None = None,
) -> dict | None:
    """Walk a workout_structure JSON and rewrite every `pace_s_per_km` field
    on active steps. Tempo has one active step; intervals has active steps
    nested inside a repeat block.

    Steps may carry a `zone` tag (E/M/T/I/R) for mixed-pace workouts — the
    peak-marathon long run has an E segment and an M segment, taper strides
    have E warm-up/cool-down around R reps. When `paces` is supplied, a tagged
    step is rewritten against its own zone; untagged steps fall back to the
    workout-level `new_pace_s` (pre-tag structures keep working unchanged)."""
    if not structure:
        return None

    def _pace_for(step: dict) -> int:
        zone = step.get("zone")
        if zone and paces and zone in paces:
            return paces[zone]
        return new_pace_s

    # Shallow-copy via re-serialisation to avoid mutating the caller's dict.
    import copy
    out = copy.deepcopy(structure)
    for step in out.get("steps", []):
        if step.get("type") == "repeat":
            for inner in step.get("steps", []):
                if "pace_s_per_km" in inner:
                    inner["pace_s_per_km"] = _pace_for(inner)
        elif "pace_s_per_km" in step:
            # Any paced step, not just `active`: taper strides pace their easy
            # warm-up and cool-down at E, and those must track a VDOT change
            # too. Classic tempo/interval warm-ups carry no pace at all, so
            # they stay untouched.
            step["pace_s_per_km"] = _pace_for(step)
    return out


def preview_recalibrate_paces(
    conn: sqlite3.Connection,
    plan_id: int,
    today_iso: str | None = None,
) -> dict:
    """Return what `recalibrate_paces` would change without writing.

    Returns:
        {
            "vdot": float, "new_paces": {"E", "M", "T", "I", "R"},
            "n_to_update": int, "n_skip_done": int, "n_skip_rest": int,
            "n_skip_past": int, "n_total": int,
            "examples": [{"date", "title", "zone", "old_pace_s", "new_pace_s"}, ...],
        }
    """
    from . import daniels as _daniels
    today_iso = today_iso or date.today().isoformat()

    plan_row = conn.execute(
        "SELECT vdot_at_start, methodology FROM plans WHERE id = ?", (plan_id,)
    ).fetchone()
    if not plan_row:
        raise ValueError("plan not found")
    _require_vdot_paces(plan_row["methodology"])
    vdot = float(plan_row["vdot_at_start"] or 0)
    new_paces = _daniels._paces_for_vdot(vdot) if vdot else {}

    rows = conn.execute(
        "SELECT id, planned_date, workout_type, title, description, "
        "       target_pace_s_per_km, target_distance_km, actual_activity_id "
        "FROM plan_workouts WHERE plan_id = ? ORDER BY planned_date", (plan_id,)
    ).fetchall()

    n_skip_done = n_skip_rest = n_skip_past = n_to_update = n_desc_only = 0
    examples: list[dict] = []
    for r in rows:
        w = dict(r)
        if w["actual_activity_id"]:
            n_skip_done += 1
            continue
        if w["planned_date"] < today_iso:
            n_skip_past += 1
            continue
        zone = _zone_for_workout(w)
        if zone is None:
            n_skip_rest += 1
            continue
        new_pace = new_paces.get(zone)
        if new_pace is None:
            continue
        pace_changed = w["target_pace_s_per_km"] != new_pace
        new_description = _refresh_description_paces(w["description"], new_paces)
        desc_changed = new_description != w["description"]
        if not pace_changed and not desc_changed:
            continue  # already in sync
        if pace_changed:
            n_to_update += 1
        else:
            n_desc_only += 1
        if len(examples) < 4:
            examples.append({
                "date": w["planned_date"],
                "title": w["title"],
                "zone": zone,
                "old_pace_s": w["target_pace_s_per_km"],
                "new_pace_s": new_pace,
                "desc_only": not pace_changed,
            })

    return {
        "vdot": vdot,
        "new_paces": new_paces,
        "n_total": len(rows),
        "n_to_update": n_to_update,
        "n_desc_only": n_desc_only,
        "n_skip_done": n_skip_done,
        "n_skip_rest": n_skip_rest,
        "n_skip_past": n_skip_past,
        "examples": examples,
    }


def recalibrate_paces(
    conn: sqlite3.Connection,
    client,
    plan_id: int,
    today_iso: str | None = None,
) -> dict:
    """Rewrite pace targets on every future, non-completed workout in the
    plan from the runner's current VDOT against the canonical pace table.

    Skips workouts that are in the past (`planned_date < today`), already
    completed (`actual_activity_id` set), or have no pace (rest/cross).
    Updates `target_pace_s_per_km`, `target_duration_s` (= distance × pace),
    and the embedded `pace_s_per_km` inside `workout_structure`. Re-pushes
    to Garmin best-effort when a workout was previously pushed.

    Returns counts matching `preview_recalibrate_paces` plus `re_pushed`.
    """
    from . import daniels as _daniels
    today_iso = today_iso or date.today().isoformat()

    plan_row = conn.execute(
        "SELECT vdot_at_start, methodology FROM plans WHERE id = ?", (plan_id,)
    ).fetchone()
    if not plan_row:
        raise ValueError("plan not found")
    _require_vdot_paces(plan_row["methodology"])
    vdot = float(plan_row["vdot_at_start"] or 0)
    if not vdot:
        raise ValueError("plan has no VDOT to recalibrate from")
    new_paces = _daniels._paces_for_vdot(vdot)

    rows = conn.execute(
        "SELECT * FROM plan_workouts WHERE plan_id = ? ORDER BY planned_date",
        (plan_id,),
    ).fetchall()

    n_updated = n_skip_done = n_skip_rest = n_skip_past = 0
    n_desc_healed = 0
    n_garmin_stale = 0  # old Garmin copies we could not delete
    re_pushed_ids: list[int] = []

    for r in rows:
        w = dict(r)
        if w["actual_activity_id"]:
            n_skip_done += 1
            continue
        if w["planned_date"] < today_iso:
            n_skip_past += 1
            continue
        zone = _zone_for_workout(w)
        if zone is None:
            n_skip_rest += 1
            continue
        new_pace = new_paces[zone]
        pace_changed = w["target_pace_s_per_km"] != new_pace
        new_description = _refresh_description_paces(w["description"], new_paces)
        desc_changed = new_description != w["description"]

        if not pace_changed and not desc_changed:
            continue  # already in sync

        if not pace_changed:
            # Heal-only path: description text was stale (e.g. lingering "4:11/km"
            # left over from a pre-bugfix recalibration). Touch only the
            # description so we don't churn pushed-to-Garmin state.
            conn.execute(
                "UPDATE plan_workouts SET description = ? WHERE id = ?",
                (new_description, w["id"]),
            )
            n_desc_healed += 1
            continue

        # Rebuild the structure JSON with the new pace on active steps
        # (zone-tagged steps rewrite against their own zone).
        structure_raw = w.get("workout_structure")
        if isinstance(structure_raw, str):
            try:
                parsed = json.loads(structure_raw)
            except Exception:  # noqa: BLE001
                parsed = None
        else:
            parsed = structure_raw
        new_structure = _rewrite_structure_pace(parsed, new_pace, new_paces)
        structure_json = json.dumps(new_structure) if new_structure else None

        # Recompute duration: from the structure when it fully times itself
        # (mixed-pace long runs — distance × headline pace would overestimate),
        # else distance × pace.
        new_duration = _daniels._structure_duration_s(new_structure)
        if new_duration is None:
            new_duration = (
                int(w["target_distance_km"] * new_pace)
                if w.get("target_distance_km") else w.get("target_duration_s")
            )

        was_pushed = bool(w.get("garmin_workout_id"))
        old_garmin_id = w.get("garmin_workout_id")

        # Confirm the old copy is off the watch before dropping its id.
        released = release_garmin_copy(client, old_garmin_id) if was_pushed else True

        conn.execute(
            """UPDATE plan_workouts SET
                  target_pace_s_per_km = ?,
                  target_duration_s = ?,
                  workout_structure = ?,
                  description = ?
               WHERE id = ?""",
            (new_pace, new_duration, structure_json, new_description, w["id"]),
        )
        if released:
            conn.execute(
                "UPDATE plan_workouts SET garmin_workout_id = NULL, pushed_at = NULL "
                "WHERE id = ?",
                (w["id"],),
            )
        else:
            # Keep the id — it is the handle to the copy still on the watch — but
            # drop pushed_at: the watch holds the *old* prescription, so this row
            # must not read as synchronised. The next push releases that copy and
            # uploads the recalibrated shape via the stranded-upload path.
            conn.execute(
                "UPDATE plan_workouts SET pushed_at = NULL WHERE id = ?",
                (w["id"],),
            )
            n_garmin_stale += 1
        n_updated += 1

        # Best-effort Garmin re-push — only when the old copy is confirmed
        # gone, so a failed delete cannot leave two shapes on the same day.
        if was_pushed and client is not None and released:
            if is_pushable(w["workout_type"], new_structure):
                try:
                    push_workout_to_garmin(conn, client, w["id"])
                    re_pushed_ids.append(w["id"])
                except Exception:  # noqa: BLE001
                    pass

    conn.commit()
    return {
        "vdot": vdot,
        "new_paces": new_paces,
        "n_updated": n_updated,
        "n_desc_healed": n_desc_healed,
        "n_skip_done": n_skip_done,
        "n_skip_rest": n_skip_rest,
        "n_skip_past": n_skip_past,
        "re_pushed": re_pushed_ids,
        # Rows whose old Garmin copy survived the delete: still on the watch
        # at the pre-recalibration pace, and the row kept its id to retry.
        "n_garmin_stale": n_garmin_stale,
    }


def estimate_vdot_from_race(distance_m: float, time_s: float) -> float:
    """Estimate VDOT from a race performance using Daniels' canonical formula.

    Inputs:
      distance_m: race distance in meters (e.g. 21097.5 for HM)
      time_s:     race time in seconds

    The model: VO2 cost of running follows a quadratic in velocity, and the
    %VO2max sustainable for the race duration follows a sum of two
    exponentials. VDOT = VO2 / %VO2max. Reference: Daniels' Running Formula
    4th ed., Appendix.
    """
    import math as _math
    if distance_m <= 0 or time_s <= 0:
        raise ValueError("distance and time must be positive")
    time_min = time_s / 60.0
    velocity = distance_m / time_min  # m/min
    vo2 = -4.60 + 0.182258 * velocity + 0.000104 * velocity * velocity
    pct_max = (
        0.8
        + 0.1894393 * _math.exp(-0.012778 * time_min)
        + 0.2989558 * _math.exp(-0.1932605 * time_min)
    )
    return round(vo2 / pct_max, 1)


def predict_race_time(distance_m: float, vdot: float, tol_s: float = 0.5) -> float:
    """Predict race time in seconds for a given distance + VDOT.

    Numerically inverts `estimate_vdot_from_race`: we know VDOT and want
    the time. Bisects in [60s, 10h], halving until the implied VDOT
    matches the target within `tol_s` precision. Convergence is fast
    (~20-30 iterations) because the VDOT-time relationship is monotonic
    and smooth.

    The prediction shares all of `estimate_vdot_from_race`'s assumptions:
    flat course, sea level, reasonable weather, well-trained runner for
    the distance. Marathons in particular run optimistic if the runner
    hasn't done specific long-distance training — Daniels' formula
    assumes the runner has the endurance to hold race pace for the full
    distance, which mid-VDOT amateurs often don't have for the full
    marathon. Caller is responsible for any disclaimer phrasing.
    """
    import math as _math
    if distance_m <= 0 or vdot <= 0:
        raise ValueError("distance and vdot must be positive")

    def _vdot_for(time_s: float) -> float:
        time_min = time_s / 60.0
        velocity = distance_m / time_min
        vo2 = -4.60 + 0.182258 * velocity + 0.000104 * velocity * velocity
        pct_max = (
            0.8
            + 0.1894393 * _math.exp(-0.012778 * time_min)
            + 0.2989558 * _math.exp(-0.1932605 * time_min)
        )
        return vo2 / pct_max

    # Faster time → higher implied VDOT (and vice versa), so bisect with
    # the comparison inverted from a standard sorted-ascending search.
    lo, hi = 60.0, 10 * 3600.0  # 1 min to 10 hours
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if _vdot_for(mid) > vdot:
            # mid time is "too fast" for this VDOT → predicted time must be slower
            lo = mid
        else:
            hi = mid
        if hi - lo < tol_s:
            break
    return (lo + hi) / 2.0


def garmin_race_prediction(
    distance_km: float,
    training_status: dict | None,
    tolerance_km: float = 0.5,
) -> int | None:
    """Pick Garmin's race-time prediction for `distance_km` from a
    training_status row, when the distance is close enough to one of
    Garmin's four canonical distances (5k / 10k / half / marathon).

    Returns the predicted time in seconds, or None when:
      - training_status payload is missing / not synced
      - the runner's race distance doesn't match a canonical distance
        within `tolerance_km`
    In the None case the caller should fall back to Daniels' formula
    (which handles arbitrary distances).
    """
    if not training_status:
        return None
    canonical = (
        ( 5.0,     "race_pred_5k_s"),
        (10.0,     "race_pred_10k_s"),
        (21.0975,  "race_pred_half_s"),
        (42.195,   "race_pred_marathon_s"),
    )
    for d_km, col in canonical:
        if abs(distance_km - d_km) <= tolerance_km:
            t = training_status.get(col)
            if t and t > 0:
                return int(t)
            return None
    return None


def update_plan_vdot(
    conn: sqlite3.Connection,
    plan_id: int,
    new_vdot: float,
) -> dict:
    """Set the plan's `vdot_at_start` to a runner-supplied value. Does NOT
    auto-recalibrate paces — the caller should redirect into the recalibrate
    flow so the runner sees the deltas before committing.

    Returns {"old", "new"} for the banner to show.
    """
    if not (25.0 <= new_vdot <= 80.0):
        raise ValueError(f"VDOT must be in the range 25-80 (got {new_vdot})")
    row = conn.execute(
        "SELECT vdot_at_start FROM plans WHERE id = ?", (plan_id,)
    ).fetchone()
    if not row:
        raise ValueError("plan not found")
    old = float(row["vdot_at_start"] or 0)
    conn.execute(
        "UPDATE plans SET vdot_at_start = ? WHERE id = ?",
        (new_vdot, plan_id),
    )
    conn.commit()
    return {"old": old, "new": new_vdot}


def update_plan_metadata(
    conn: sqlite3.Connection,
    plan_id: int,
    *,
    title: str | None = None,
    notes: str | None = None,
) -> dict:
    """Tier-1 plan edit — title and notes only. Touches no workouts, no
    targets, no schedule. Pass `None` for a field to leave it unchanged;
    pass an empty string to clear it (notes only — title can't be empty).

    Returns the refreshed plan row dict. Raises ValueError on bad input."""
    row = conn.execute("SELECT id, title, notes FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if not row:
        raise ValueError("plan not found")

    new_title = row["title"]
    new_notes = row["notes"]

    if title is not None:
        title = title.strip()
        if not title:
            raise ValueError("title cannot be empty")
        new_title = title[:200]
    if notes is not None:
        new_notes = (notes.strip() or None)
        if new_notes:
            new_notes = new_notes[:2000]

    conn.execute(
        "UPDATE plans SET title = ?, notes = ? WHERE id = ?",
        (new_title, new_notes, plan_id),
    )
    conn.commit()
    refreshed = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return dict(refreshed)


def delete_plan(conn: sqlite3.Connection, plan_id: int) -> dict:
    """Hard-delete an inactive plan and all its workouts.

    Refuses to delete an active plan — must be deactivated first. The FK on
    plan_workouts has ON DELETE CASCADE so workout rows go with it.
    """
    row = conn.execute("SELECT id, title, status FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if not row:
        raise ValueError("plan not found")
    if row["status"] == "active":
        raise ValueError("cannot delete an active plan — deactivate it first")

    title = row["title"]
    conn.execute("DELETE FROM plans WHERE id = ?", (plan_id,))
    conn.commit()
    return {"deleted_id": plan_id, "title": title}


def list_plans(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        rows = conn.execute("SELECT * FROM plans WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM plans ORDER BY status = 'active' DESC, id DESC").fetchall()
    return [dict(r) for r in rows]


def get_active_plan(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM plans WHERE status = 'active' ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def get_plan(conn: sqlite3.Connection, plan_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return dict(row) if row else None


def get_plan_workouts(conn: sqlite3.Connection, plan_id: int) -> list[dict]:
    """Plan workouts joined with the matched activity's headline stats and,
    on done rows, an `execution_score` dict (None when the score doesn't
    apply — rest days, unmatched workouts, no target pace/distance).
    """
    rows = conn.execute(
        """SELECT pw.*,
                  a.activity_id      AS actual_id,
                  a.distance_m       AS actual_distance_m,
                  a.duration_s       AS actual_duration_s,
                  a.avg_hr           AS actual_avg_hr,
                  a.activity_name    AS actual_name,
                  a.start_time_local AS actual_start_local,
                  a.hr_zone_1_s, a.hr_zone_2_s, a.hr_zone_3_s,
                  a.hr_zone_4_s, a.hr_zone_5_s
           FROM plan_workouts pw
           LEFT JOIN activities a ON a.activity_id = pw.actual_activity_id
           WHERE pw.plan_id = ?
           ORDER BY pw.planned_date, pw.day_of_week""",
        (plan_id,),
    ).fetchall()
    from .. import execution_score as _es
    out: list[dict] = []
    for r in rows:
        w = dict(r)
        if w.get("actual_activity_id"):
            activity = {
                "activity_id": w["actual_id"],
                "distance_m":  w["actual_distance_m"],
                "duration_s":  w["actual_duration_s"],
                "avg_hr":      w["actual_avg_hr"],
                "hr_zone_1_s": w.get("hr_zone_1_s"),
                "hr_zone_2_s": w.get("hr_zone_2_s"),
                "hr_zone_3_s": w.get("hr_zone_3_s"),
                "hr_zone_4_s": w.get("hr_zone_4_s"),
                "hr_zone_5_s": w.get("hr_zone_5_s"),
            }
            w["execution_score"] = _es.compute(conn, w, activity)
        else:
            w["execution_score"] = None
        out.append(w)
    return out


def workout_status(workout: dict, today_iso: str) -> str:
    """Status pill for a planned workout: future | today | done | missed | rest."""
    if workout["workout_type"] in ("rest", "cross"):
        return "rest"
    if workout.get("actual_activity_id"):
        return "done"
    pd = workout["planned_date"]
    if pd > today_iso:
        return "future"
    if pd == today_iso:
        return "today"
    return "missed"


def plan_adherence(conn: sqlite3.Connection, plan_id: int, today_iso: str) -> dict:
    """Aggregate adherence stats for a plan: total / done / missed / due so far."""
    row = conn.execute(
        """SELECT
              SUM(CASE WHEN workout_type NOT IN ('rest','cross') THEN 1 ELSE 0 END)             AS total_sessions,
              SUM(CASE WHEN workout_type NOT IN ('rest','cross') AND planned_date <= ?
                       THEN 1 ELSE 0 END)                                                       AS due_so_far,
              SUM(CASE WHEN actual_activity_id IS NOT NULL THEN 1 ELSE 0 END)                   AS done_count,
              SUM(CASE WHEN workout_type NOT IN ('rest','cross') AND planned_date < ?
                       AND actual_activity_id IS NULL THEN 1 ELSE 0 END)                        AS missed_count
           FROM plan_workouts
           WHERE plan_id = ?""",
        (today_iso, today_iso, plan_id),
    ).fetchone()
    total = row["total_sessions"] or 0
    due = row["due_so_far"] or 0
    done = row["done_count"] or 0
    missed = row["missed_count"] or 0
    pct = (done / due * 100) if due > 0 else 0.0
    return {
        "total_sessions": total,
        "due_so_far": due,
        "done": done,
        "missed": missed,
        "completion_pct": round(pct),
    }


def get_plan_week(conn: sqlite3.Connection, plan_id: int, week_number: int) -> dict | None:
    """One week's data, same shape as items returned by get_plan_weeks."""
    for w in get_plan_weeks(conn, plan_id):
        if w["week_number"] == week_number:
            return w
    return None


def week_has_pushable(week: dict) -> bool:
    """True if at least one workout in this week is pushable, unpushed,
    AND scheduled for today or later. Past workouts never need a push —
    nothing to send to the watch retroactively. Today's not-yet-done
    workout still qualifies (the runner might want it on the wrist)."""
    today_iso = date.today().isoformat()
    for w in week["workouts"]:
        if w.get("pushed_at"):
            continue
        if w.get("planned_date", "") < today_iso:
            continue
        if is_pushable(w["workout_type"], w.get("workout_structure")):
            return True
    return False


def week_adherence(week: dict, today_iso: str) -> dict:
    """Per-week adherence counts. Matches the conventions in `plan_adherence` and
    `workout_status` — rest/cross days don't count as sessions; "missed" is
    strictly past dates (today's not-yet-done workout is still on the books).

    Returns: planned, done, due, missed.
    """
    planned = done = due = missed = 0
    for w in week["workouts"]:
        if w["workout_type"] in ("rest", "cross"):
            continue
        planned += 1
        if w.get("actual_activity_id"):
            done += 1
        if w["planned_date"] <= today_iso:
            due += 1
            if not w.get("actual_activity_id") and w["planned_date"] < today_iso:
                missed += 1
    return {"planned": planned, "done": done, "due": due, "missed": missed}


def get_plan_weeks(conn: sqlite3.Connection, plan_id: int) -> list[dict]:
    """Workouts grouped into week dicts: {week_number, week_phase, week_start, total_km, workouts}."""
    workouts = get_plan_workouts(conn, plan_id)
    weeks: dict[int, dict] = {}
    for w in workouts:
        wn = w["week_number"]
        if wn not in weeks:
            weeks[wn] = {
                "week_number": wn,
                "week_phase": w["week_phase"],
                "week_start": w["planned_date"],
                "workouts": [],
                "total_km": 0.0,
                "n_sessions": 0,
            }
        weeks[wn]["workouts"].append(w)
        if w["target_distance_km"]:
            weeks[wn]["total_km"] += w["target_distance_km"]
        if w["workout_type"] not in ("rest",):
            weeks[wn]["n_sessions"] += 1
    return [weeks[k] for k in sorted(weeks.keys())]


# A week keeps a training streak alive at ≥80% of its qualifying sessions —
# forgiving enough that a single missed easy run (or a legitimately cut-back
# week) doesn't wipe out weeks of consistency, strict enough to still mean
# something. Used by `week_stats` for the "This week" dashboard block.
STREAK_MIN_ADHERENCE = 0.8


def week_end_iso(week: dict) -> str:
    """Last planned date in a week (the week dicts from get_plan_weeks are
    ordered earliest-first). Falls back to week_start for an empty week."""
    if week.get("workouts"):
        return week["workouts"][-1]["planned_date"]
    return week["week_start"]


def current_plan_week(weeks: list[dict], today_iso: str) -> dict | None:
    """The week whose date span contains today, or None (between plans, or
    today falls in a gap). `weeks` is a get_plan_weeks() list."""
    for w in weeks:
        if w["week_start"] <= today_iso <= week_end_iso(w):
            return w
    return None


def _week_qualifies_for_streak(week: dict, today_iso: str) -> bool | None:
    """Does this week clear the streak threshold? Returns None for a week with
    no qualifying sessions (all rest/cross) — such a week is transparent: it
    neither counts toward nor breaks the streak."""
    adh = week_adherence(week, today_iso)
    if adh["planned"] == 0:
        return None
    return (adh["done"] / adh["planned"]) >= STREAK_MIN_ADHERENCE


def streak_weeks(weeks: list[dict], current_week_number: int, today_iso: str) -> int:
    """Consecutive weeks (ending at the current one) that cleared ≥80%
    adherence. Strictly-prior weeks are fully elapsed so their ratio is final;
    the *current* week joins the streak only once it clears the threshold, so
    mid-week the counter shows the runner's prior run and ticks up when they
    complete enough of this week. All-rest weeks are skipped transparently."""
    by_num = {w["week_number"]: w for w in weeks}
    streak = 0
    n = current_week_number - 1
    while n in by_num:
        q = _week_qualifies_for_streak(by_num[n], today_iso)
        if q is None:
            n -= 1
            continue
        if q:
            streak += 1
            n -= 1
        else:
            break
    cur = by_num.get(current_week_number)
    if cur is not None and _week_qualifies_for_streak(cur, today_iso):
        streak += 1
    return streak


def week_stats(
    conn: sqlite3.Connection,
    plan_id: int,
    weeks: list[dict],
    week: dict,
    today_iso: str,
) -> dict:
    """Rich stats for one plan week, powering the "This week" dashboard block.

    Numbers are the runner's *actual* banked work (matched runs), not the
    plan's prescription — this is a "look what you did" surface. `plan_distance_km`
    is cumulative actual km across the whole plan so far (progress toward the
    goal), and `streak_weeks` is the forgiving consistency streak.
    """
    adh = week_adherence(week, today_iso)
    wn = week["week_number"]

    # Actual totals for this week — join matched activities for the fields the
    # workout dicts don't carry (load, elevation).
    row = conn.execute(
        """SELECT COUNT(*)                              AS n,
                  COALESCE(SUM(a.distance_m), 0)        AS dist_m,
                  COALESCE(SUM(a.duration_s), 0)        AS time_s,
                  COALESCE(SUM(a.training_load), 0)     AS load,
                  COALESCE(SUM(a.elevation_gain_m), 0)  AS climb_m,
                  COALESCE(MAX(a.distance_m), 0)        AS longest_m
           FROM plan_workouts pw
           JOIN activities a ON a.activity_id = pw.actual_activity_id
           WHERE pw.plan_id = ? AND pw.week_number = ?""",
        (plan_id, wn),
    ).fetchone()

    # Cumulative actual distance across the whole plan (total banked so far).
    cum = conn.execute(
        """SELECT COUNT(*)                       AS n,
                  COALESCE(SUM(a.distance_m), 0) AS dist_m
           FROM plan_workouts pw
           JOIN activities a ON a.activity_id = pw.actual_activity_id
           WHERE pw.plan_id = ?""",
        (plan_id,),
    ).fetchone()

    # Prescription quality — how many scored sessions landed "green".
    targets_total = targets_hit = 0
    for w in week["workouts"]:
        es = w.get("execution_score")
        if es:
            targets_total += 1
            if es.get("color") == "green":
                targets_hit += 1

    complete = adh["planned"] > 0 and adh["done"] >= adh["planned"]
    return {
        "week_number": wn,
        "week_phase": week["week_phase"],
        "week_start": week["week_start"],
        "week_end": week_end_iso(week),
        "sessions_done": adh["done"],
        "sessions_planned": adh["planned"],
        "sessions_due": adh["due"],
        "missed": adh["missed"],
        "complete": complete,
        "pct": round(100 * adh["done"] / adh["planned"]) if adh["planned"] else 0,
        "distance_km": (row["dist_m"] or 0) / 1000.0,
        "moving_time_s": int(row["time_s"] or 0),
        "load": round(row["load"]) if row["load"] else None,
        "climb_m": round(row["climb_m"]) if row["climb_m"] else None,
        "longest_run_km": (row["longest_m"] or 0) / 1000.0,
        "plan_distance_km": (cum["dist_m"] or 0) / 1000.0,
        "plan_runs_done": cum["n"] or 0,
        "targets_hit": targets_hit,
        "targets_total": targets_total,
        "streak_weeks": streak_weeks(weeks, wn, today_iso),
    }


def todays_workout(conn: sqlite3.Connection) -> dict | None:
    """Today's workout from the active plan, if any.

    When the day's run has been matched (`actual_activity_id` set on sync),
    the row also carries the matched activity's headline stats
    (`actual_distance_m`, `actual_duration_s`, `actual_avg_hr`) so the
    dashboard flagship can flip from prescription → post-run summary.
    """
    today = date.today().isoformat()
    row = conn.execute(
        """SELECT pw.*,
                  a.distance_m AS actual_distance_m,
                  a.duration_s AS actual_duration_s,
                  a.avg_hr     AS actual_avg_hr
           FROM plan_workouts pw
           JOIN plans p ON p.id = pw.plan_id
           LEFT JOIN activities a ON a.activity_id = pw.actual_activity_id
           WHERE p.status = 'active' AND pw.planned_date = ?
           ORDER BY pw.day_of_week LIMIT 1""",
        (today,),
    ).fetchone()
    return dict(row) if row else None


def apply_workout_swap(
    conn: sqlite3.Connection,
    client,
    plan_workout_id: int,
) -> dict:
    """Soften today's planned workout based on the current coach recommendation.

    1. Looks up the workout + its plan's starting VDOT.
    2. Asks the coach for today's severity.
    3. Calls the swapper to get the softened shape.
    4. Updates plan_workouts in place.
    5. If the workout was already pushed to Garmin: best-effort delete the old
       Garmin workout + push the new shape.

    Returns {"swapped": bool, "from": str, "to": str, "re_pushed": bool}.
    """
    row = conn.execute(
        "SELECT * FROM plan_workouts WHERE id = ?", (plan_workout_id,)
    ).fetchone()
    if not row:
        raise ValueError("workout not found")
    pw = dict(row)

    if pw.get("actual_activity_id"):
        raise ValueError("workout is already completed — nothing to swap")

    plan = conn.execute(
        "SELECT vdot_at_start, methodology FROM plans WHERE id = ?", (pw["plan_id"],)
    ).fetchone()
    vdot = plan["vdot_at_start"] if plan else None
    if plan:
        try:
            _require_vdot_paces(plan["methodology"])
        except ValueError:
            raise ValueError(
                "this plan is already at beginner effort — take the session "
                "gently or rest instead of swapping it"
            )

    rec = plan_coach.daily_recommendation(conn)
    if not rec or rec["status"] not in ("caution", "easy"):
        raise ValueError("no swap available — coach status is not caution/easy")

    if not plan_swapper.can_swap(pw["workout_type"], rec["status"]):
        raise ValueError(f"no swap rule for {pw['workout_type']} + {rec['status']}")

    new_shape = plan_swapper.soft_swap(pw, rec["status"], vdot)
    original_title = pw["title"]
    was_pushed = bool(pw.get("garmin_workout_id"))
    old_garmin_id = pw.get("garmin_workout_id")

    # Release the old Garmin copy first. If it can't be confirmed gone the
    # row keeps its id, so the swap still applies locally but the watch is
    # not falsely reported clean.
    released = release_garmin_copy(client, old_garmin_id) if was_pushed else True

    # Update the row (push state is cleared below, only if released)
    conn.execute(
        """UPDATE plan_workouts SET
              workout_type = ?,
              title = ?,
              description = ?,
              target_distance_km = ?,
              target_duration_s = ?,
              target_pace_s_per_km = ?,
              workout_structure = ?
           WHERE id = ?""",
        (
            new_shape["workout_type"],
            new_shape["title"],
            new_shape["description"],
            new_shape.get("target_distance_km"),
            new_shape.get("target_duration_s"),
            new_shape.get("target_pace_s_per_km"),
            json.dumps(new_shape["workout_structure"]) if new_shape.get("workout_structure") else None,
            plan_workout_id,
        ),
    )
    if released:
        conn.execute(
            "UPDATE plan_workouts SET garmin_workout_id = NULL, pushed_at = NULL "
            "WHERE id = ?",
            (plan_workout_id,),
        )
    else:
        # Keep the id — it is the handle to the copy still on the watch — but
        # drop pushed_at: the watch holds the *old* prescription, so this row
        # must not read as synchronised. The next push releases that copy and
        # uploads the edited shape via the stranded-upload path.
        conn.execute(
            "UPDATE plan_workouts SET pushed_at = NULL WHERE id = ?",
            (plan_workout_id,),
        )
    conn.commit()

    # Re-push only once the old copy is confirmed gone, so a failed delete
    # cannot leave the pre-swap and post-swap shapes on the same day.
    re_pushed = False
    if was_pushed and released:
        # Only re-push if the new shape is still pushable (not 'rest').
        if is_pushable(new_shape["workout_type"], new_shape.get("workout_structure")):
            try:
                push_workout_to_garmin(conn, client, plan_workout_id)
                re_pushed = True
            except Exception:  # noqa: BLE001
                pass

    return {
        "swapped": True,
        "from": original_title,
        "to": new_shape["title"],
        "re_pushed": re_pushed,
    }


ALLOWED_WORKOUT_TYPES = frozenset({
    "easy", "tempo", "intervals", "long", "recovery", "rest", "cross", "race",
})
_STRUCTURED_TYPES = frozenset({"tempo", "intervals"})
_SIMPLE_TYPES = frozenset({"easy", "long", "recovery", "race"})


def _derive_title(
    workout_type: str,
    target_distance_km: float | None,
    structure: dict | None = None,
    current_title: str | None = None,
) -> str:
    """Generate the canonical title for a workout shape.

    Used after manual edits so the title doesn't get stuck at the old shape
    (e.g. "Easy 7 km" still showing after the runner bumps the distance to
    11 km). Mirrors the title formats the Daniels engine emits at plan
    generation time.

    `current_title` (the pre-edit title, passed only when the workout type
    didn't change) lets tempo rows keep their pace vocabulary: the
    recalibrator zones tempo workouts off title tokens ("Marathon-pace",
    "Race-pace" → M, else T), so re-deriving a generic "Tempo N km" would
    silently flip an M-pace session to threshold on the next recalibrate.
    """
    km = target_distance_km or 0

    if workout_type == "tempo" and current_title:
        # Preserve the engine's wording ("Marathon-pace run", "Race-pace
        # tune", "Lactate threshold", …), refreshing only the distance.
        m = re.match(r"^(.+?)\s+\d+(?:[.,]\d+)?\s*km\b", current_title)
        if m:
            return f"{m.group(1)} {km:.0f} km" if km else m.group(1)

    if workout_type == "rest":
        return "Rest"
    if workout_type == "cross":
        return "Cross-training"
    if workout_type == "race":
        return f"Race {km:.0f} km" if km else "Race"

    if workout_type == "intervals" and structure:
        # Extract reps + rep-distance from the structure's `repeat` block.
        for step in structure.get("steps", []):
            if step.get("type") == "repeat":
                iters = int(step.get("iterations") or 0)
                inner = step.get("steps", [])
                work = next((s for s in inner if s.get("type") == "active"), None)
                if work and work.get("end", {}).get("distance_m"):
                    rep_m = int(work["end"]["distance_m"])
                    # Same trap as the tempo branch above, one zone down.
                    # `_zone_for_workout` reads R vs I off the title token
                    # ("Repetitions"/"Strides" → R, else I), so a generic
                    # "Intervals N×M m" silently demotes a VDOT-50 6×400 m
                    # repetition session from R (232 s/km) to I (250 s/km) on
                    # the next recalibrate. Take the noun from the step's own
                    # zone tag, which is the authority, and keep "Strides"
                    # when that is what this session already was.
                    noun = "Intervals"
                    if (work.get("zone") or "").upper() == "R":
                        noun = (
                            "Strides"
                            if "stride" in (current_title or "").lower()
                            else "Repetitions"
                        )
                    return f"{noun} {iters}×{rep_m} m"
                if work and work.get("end", {}).get("duration_s"):
                    # Time-based run/walk repeats (Couch to 5K) — mirror the
                    # engine's title vocabulary.
                    from .c25k import _mins
                    work_lbl = _mins(int(work["end"]["duration_s"]))
                    rec = next((s for s in inner if s.get("type") == "recovery"), None)
                    rec_s = ((rec or {}).get("end") or {}).get("duration_s")
                    if rec_s:
                        return f"Run/walk {iters}×({work_lbl} run / {_mins(int(rec_s))} walk)"
                    return f"Run/walk {iters}×{work_lbl}"
                break
        return f"Intervals {km:.0f} km"

    if workout_type in ("easy", "long", "recovery") and structure and not km:
        # Time-based continuous run (Couch to 5K, Foppen): no distance, the
        # active step(s) carry durations.
        total_active_s = sum(
            int(s["end"]["duration_s"])
            for s in structure.get("steps", [])
            if s.get("type") == "active" and (s.get("end") or {}).get("duration_s")
        )
        if total_active_s:
            from .c25k import _mins
            return f"Run {_mins(total_active_s)}"

    if workout_type == "long" and structure:
        # Mixed-pace long run (peak marathon): keep the M-pace part in the title.
        m_km = sum(
            (s.get("end", {}).get("distance_m") or 0) / 1000.0
            for s in structure.get("steps", [])
            if s.get("zone") == "M"
        )
        if m_km:
            return f"Long {km:.0f} km incl. {m_km:.0f} km @ M pace"

    # Simple types + tempo without structure-specific naming.
    label = {
        "easy":     "Easy",
        "long":     "Long",
        "recovery": "Recovery",
        "tempo":    "Tempo",
        "intervals":"Intervals",
    }.get(workout_type, workout_type.capitalize())
    return f"{label} {km:.0f} km" if km else label


def _build_tempo_structure(
    warmup_km: float,
    active_km: float,
    active_pace_s_per_km: int,
    cooldown_km: float,
) -> dict:
    """JSON shape that planned_to_garmin_workout consumes — matches the format
    daniels._tempo_structure() emits at plan generation time."""
    return {
        "steps": [
            {"type": "warmup", "end": {"distance_m": int(warmup_km * 1000)}},
            {"type": "active", "end": {"distance_m": int(active_km * 1000)},
             "pace_s_per_km": active_pace_s_per_km},
            {"type": "cooldown", "end": {"distance_m": int(cooldown_km * 1000)}},
        ]
    }


def _build_intervals_structure(
    warmup_km: float,
    iterations: int,
    work_km: float,
    work_pace_s_per_km: int,
    recovery_s: int,
    cooldown_km: float,
) -> dict:
    """Matches daniels._interval_structure()."""
    return {
        "steps": [
            {"type": "warmup", "end": {"distance_m": int(warmup_km * 1000)}},
            {"type": "repeat", "iterations": iterations, "steps": [
                {"type": "active", "end": {"distance_m": int(work_km * 1000)},
                 "pace_s_per_km": work_pace_s_per_km},
                {"type": "recovery", "end": {"duration_s": int(recovery_s)}},
            ]},
            {"type": "cooldown", "end": {"distance_m": int(cooldown_km * 1000)}},
        ]
    }


def _build_time_intervals_structure(
    warmup_s: int,
    iterations: int,
    work_s: int,
    recovery_s: int,
    cooldown_s: int,
) -> dict:
    """Time-based run/walk repeats (Couch to 5K, Foppen) — durations only,
    no paces anywhere. Matches the shapes c25k._session_structure emits."""
    steps: list[dict] = []
    if warmup_s:
        steps.append({"type": "warmup", "end": {"duration_s": int(warmup_s)}})
    repeat_steps: list[dict] = [{"type": "active", "end": {"duration_s": int(work_s)}}]
    if recovery_s:
        repeat_steps.append({"type": "recovery", "end": {"duration_s": int(recovery_s)}})
    steps.append({"type": "repeat", "iterations": int(iterations), "steps": repeat_steps})
    if cooldown_s:
        steps.append({"type": "cooldown", "end": {"duration_s": int(cooldown_s)}})
    return {"steps": steps}


def _build_progression_structure(segments: list[dict]) -> dict:
    """Multi-pace continuous run — an ordered list of distance-based `active`
    segments, each at its own pace (e.g. Daniels' peak marathon long run: an
    easy block then an M-pace finish). Each segment keeps its `zone` tag so the
    pace recalibrator can rewrite it against the right zone. Mirrors the shape
    daniels._long_run_workout() emits. Segments without a distance are dropped."""
    steps: list[dict] = []
    for seg in segments:
        km = seg.get("km")
        if not km:
            continue
        step: dict = {"type": "active", "end": {"distance_m": int(round(km * 1000))}}
        if seg.get("zone"):
            step["zone"] = seg["zone"]
        if seg.get("pace_s_per_km"):
            step["pace_s_per_km"] = int(seg["pace_s_per_km"])
        steps.append(step)
    return {"steps": steps}


def _build_time_simple_structure(warmup_s: int, active_s: int, cooldown_s: int) -> dict:
    """Time-based continuous run bracketed by optional warmup/cooldown walks."""
    steps: list[dict] = []
    if warmup_s:
        steps.append({"type": "warmup", "end": {"duration_s": int(warmup_s)}})
    steps.append({"type": "active", "end": {"duration_s": int(active_s)}})
    if cooldown_s:
        steps.append({"type": "cooldown", "end": {"duration_s": int(cooldown_s)}})
    return {"steps": steps}


# Totals now live in plans/_structure.py so the engines can derive the same
# headline numbers at generation time that an edit derives here. Aliased to
# keep this module's existing call sites unchanged.
_totals_from_structure = _totals_from_structure_shared


def edit_workout(
    conn: sqlite3.Connection,
    client,
    plan_workout_id: int,
    *,
    workout_type: str,
    # Flat fields (simple types or cross-family fallback)
    target_distance_km: float | None = None,
    target_pace_s_per_km: int | None = None,
    # Tempo fields
    tempo_warmup_km: float | None = None,
    tempo_active_km: float | None = None,
    tempo_active_pace_s: int | None = None,
    tempo_cooldown_km: float | None = None,
    # Intervals fields
    intervals_warmup_km: float | None = None,
    intervals_iterations: int | None = None,
    intervals_work_km: float | None = None,
    intervals_work_pace_s: int | None = None,
    intervals_recovery_s: int | None = None,
    intervals_cooldown_km: float | None = None,
    # Progression fields (multi-pace continuous run — one dict per segment with
    # km / pace_s_per_km / zone). Rebuilds the multi-segment `long` structure.
    segments: list[dict] | None = None,
    # Time-based fields (paceless run/walk sessions — Couch to 5K, Foppen)
    intervals_warmup_s: int | None = None,
    intervals_work_s: int | None = None,
    intervals_cooldown_s: int | None = None,
    simple_warmup_s: int | None = None,
    simple_run_s: int | None = None,
    simple_cooldown_s: int | None = None,
) -> dict:
    """Manual edit from the planned-workout modal. Three paths:

    - **Simple types** (easy/long/recovery/race) — provide `target_distance_km`
      + `target_pace_s_per_km`. Duration is computed (`dist × pace`).
    - **Structured types** (tempo/intervals) — provide per-step fields. The
      `workout_structure` JSON is rebuilt from scratch; totals (distance,
      headline pace, duration) are derived from the structure.
    - **Time-based sessions** (paceless run/walk plans) — provide the `*_s`
      duration fields instead. The rebuilt structure stays duration-only and
      the workout keeps no distance/pace targets, preserving the paceless
      contract.

    Cross-family type changes fall back to whatever the user provided in the
    matching set — if they're missing, the structure is cleared and the
    workout becomes whatever the simple fields describe.

    Pushed-to-Garmin workouts are deleted and re-pushed best-effort.
    """
    if workout_type not in ALLOWED_WORKOUT_TYPES:
        raise ValueError(f"unknown workout_type: {workout_type!r}")

    row = conn.execute(
        "SELECT * FROM plan_workouts WHERE id = ?", (plan_workout_id,)
    ).fetchone()
    if not row:
        raise ValueError("workout not found")
    pw = dict(row)
    if pw.get("actual_activity_id"):
        raise ValueError("workout is already completed — edits are not allowed")

    prev = {
        "workout_type": pw["workout_type"],
        "target_distance_km": pw["target_distance_km"],
        "target_pace_s_per_km": pw["target_pace_s_per_km"],
        "target_duration_s": pw["target_duration_s"],
    }
    was_pushed = bool(pw.get("garmin_workout_id"))
    old_garmin_id = pw.get("garmin_workout_id")

    new_structure: dict | None = None

    if workout_type in ("rest", "cross"):
        # No quantitative targets on rest/cross.
        target_distance_km = None
        target_pace_s_per_km = None
        target_duration_s = None

    elif workout_type == "tempo" and tempo_active_km is not None and tempo_active_pace_s:
        new_structure = _build_tempo_structure(
            warmup_km=tempo_warmup_km or 0.0,
            active_km=tempo_active_km,
            active_pace_s_per_km=tempo_active_pace_s,
            cooldown_km=tempo_cooldown_km or 0.0,
        )
        totals = _totals_from_structure(new_structure)
        target_distance_km = totals["total_km"]
        target_pace_s_per_km = totals["headline_pace_s"]
        target_duration_s = totals["total_duration_s"]

    elif workout_type == "intervals" and intervals_work_km and intervals_work_pace_s and intervals_iterations:
        new_structure = _build_intervals_structure(
            warmup_km=intervals_warmup_km or 0.0,
            iterations=intervals_iterations,
            work_km=intervals_work_km,
            work_pace_s_per_km=intervals_work_pace_s,
            recovery_s=intervals_recovery_s or 0,
            cooldown_km=intervals_cooldown_km or 0.0,
        )
        totals = _totals_from_structure(new_structure)
        target_distance_km = totals["total_km"]
        target_pace_s_per_km = totals["headline_pace_s"]
        target_duration_s = totals["total_duration_s"]

    elif workout_type == "intervals" and intervals_work_s and intervals_iterations:
        # Time-based run/walk repeats — stays paceless and distance-free.
        new_structure = _build_time_intervals_structure(
            warmup_s=intervals_warmup_s or 0,
            iterations=intervals_iterations,
            work_s=intervals_work_s,
            recovery_s=intervals_recovery_s or 0,
            cooldown_s=intervals_cooldown_s or 0,
        )
        target_distance_km = None
        target_pace_s_per_km = None
        target_duration_s = _totals_from_structure(new_structure)["total_duration_s"]

    elif workout_type in ("easy", "long", "recovery") and simple_run_s:
        # Time-based continuous run — stays paceless and distance-free.
        new_structure = _build_time_simple_structure(
            warmup_s=simple_warmup_s or 0,
            active_s=simple_run_s,
            cooldown_s=simple_cooldown_s or 0,
        )
        target_distance_km = None
        target_pace_s_per_km = None
        target_duration_s = _totals_from_structure(new_structure)["total_duration_s"]

    elif (
        workout_type in ("easy", "long", "recovery")
        and segments
        and len([s for s in segments if s.get("km")]) >= 2
    ):
        # Multi-pace continuous run (peak marathon long run: E block + M finish).
        # Rebuild the segmented structure; totals derive from it. Headline pace
        # is the first segment's (the easy lead-in), matching the engine.
        new_structure = _build_progression_structure(segments)
        totals = _totals_from_structure(
            new_structure, fallback_pace=pw["target_pace_s_per_km"]
        )
        target_distance_km = totals["total_km"]
        target_pace_s_per_km = totals["headline_pace_s"]
        target_duration_s = totals["total_duration_s"]

    else:
        # Simple path — easy/long/recovery/race, or a structured type the user
        # changed *to* without providing per-step fields (cross-family fallback).
        # Compute duration from distance × pace when both are present.
        if target_distance_km and target_pace_s_per_km:
            target_duration_s = int(target_distance_km * target_pace_s_per_km)
        else:
            target_duration_s = None
        # Preserve existing structure only on same-type simple edits where the
        # shape didn't change — never carry a structured shape forward when the
        # type changed, and drop it when distance/pace moved (a peak long run's
        # E+M steps would silently disagree with the edited totals).
        shape_unchanged = (
            abs((target_distance_km or 0) - (pw["target_distance_km"] or 0)) < 0.05
            and (target_pace_s_per_km or None) == (pw["target_pace_s_per_km"] or None)
        )
        if workout_type == pw["workout_type"] and shape_unchanged:
            new_structure = (
                json.loads(pw["workout_structure"])
                if isinstance(pw.get("workout_structure"), str)
                else pw.get("workout_structure")
            )

    structure_json = json.dumps(new_structure) if new_structure else None

    # Regenerate the cosmetic title so it doesn't drift from the new shape.
    # Without this, "Easy 7 km" stays at the old name after the runner edits
    # the distance to 11 km — see the bug report from 2026-05-28. The old
    # title is only passed on same-type edits (its vocabulary is wrong for a
    # changed type).
    new_title = _derive_title(
        workout_type, target_distance_km, new_structure,
        current_title=pw["title"] if workout_type == pw["workout_type"] else None,
    )

    # Release the old Garmin copy *before* touching local push state. If the
    # delete can't be confirmed, the id has to survive the edit — it is the
    # only handle left to retry, and dropping it would strand the old workout
    # on the watch while a replacement upload added a second one.
    released = release_garmin_copy(client, old_garmin_id) if was_pushed else True

    conn.execute(
        """UPDATE plan_workouts SET
              workout_type = ?,
              title = ?,
              target_distance_km = ?,
              target_pace_s_per_km = ?,
              target_duration_s = ?,
              workout_structure = ?
           WHERE id = ?""",
        (
            workout_type,
            new_title,
            target_distance_km,
            target_pace_s_per_km,
            target_duration_s,
            structure_json,
            plan_workout_id,
        ),
    )
    if released:
        conn.execute(
            "UPDATE plan_workouts SET garmin_workout_id = NULL, pushed_at = NULL "
            "WHERE id = ?",
            (plan_workout_id,),
        )
    else:
        # Keep the id — it is the handle to the copy still on the watch — but
        # drop pushed_at: the watch holds the *old* prescription, so this row
        # must not read as synchronised. The next push releases that copy and
        # uploads the edited shape via the stranded-upload path.
        conn.execute(
            "UPDATE plan_workouts SET pushed_at = NULL WHERE id = ?",
            (plan_workout_id,),
        )
    conn.commit()

    re_pushed = False
    # Only re-push once the old copy is confirmed gone; otherwise the runner
    # ends up with both shapes on the same day.
    if was_pushed and client is not None and released:
        if is_pushable(workout_type, structure_json):
            try:
                push_workout_to_garmin(conn, client, plan_workout_id)
                re_pushed = True
            except Exception:  # noqa: BLE001 — surface via UI, don't bail the edit
                pass

    refreshed = conn.execute(
        "SELECT * FROM plan_workouts WHERE id = ?", (plan_workout_id,)
    ).fetchone()
    return {
        "edited": True,
        "from": prev,
        "to": dict(refreshed),
        "re_pushed": re_pushed,
        "was_pushed": was_pushed,
        # True when the old Garmin copy could not be deleted: it is still on
        # the watch showing the pre-edit shape, and the row kept its id so a
        # later push can replace it.
        "garmin_stale": bool(was_pushed and not released),
    }


def move_workout(
    conn: sqlite3.Connection,
    client,
    plan_workout_id: int,
    new_date: str,
) -> dict:
    """Reschedule a planned workout to `new_date` (ISO YYYY-MM-DD). If another
    workout in the same plan already occupies `new_date`, the two swap dates.
    Pushed-to-Garmin workouts are re-pushed best-effort on the new date.

    Returns {"moved": bool, "swapped_with_id": int | None, "re_pushed_ids": [int, ...]}.
    Raises ValueError when the workout is missing, already completed, or the
    new date is outside the plan window or in a different plan.
    """
    try:
        new_date_d = date.fromisoformat(new_date)
    except ValueError as exc:
        raise ValueError(f"invalid date: {new_date!r}") from exc

    row = conn.execute(
        "SELECT * FROM plan_workouts WHERE id = ?", (plan_workout_id,)
    ).fetchone()
    if not row:
        raise ValueError("workout not found")
    pw = dict(row)
    if pw.get("actual_activity_id"):
        raise ValueError("workout is already completed — cannot be moved")
    if pw["planned_date"] == new_date:
        return {"moved": False, "swapped_with_id": None, "re_pushed_ids": []}

    # Constrain to the plan window so we never push a workout into the void.
    plan_window = conn.execute(
        "SELECT MIN(planned_date) AS lo, MAX(planned_date) AS hi "
        "FROM plan_workouts WHERE plan_id = ?",
        (pw["plan_id"],),
    ).fetchone()
    if not plan_window or not plan_window["lo"]:
        raise ValueError("plan has no scheduled workouts")
    if new_date < plan_window["lo"] or new_date > plan_window["hi"]:
        raise ValueError(
            f"date {new_date} is outside the plan window "
            f"({plan_window['lo']} – {plan_window['hi']})"
        )

    # Anyone else on that date? If yes, swap.
    other = conn.execute(
        "SELECT * FROM plan_workouts "
        "WHERE plan_id = ? AND planned_date = ? AND id != ?",
        (pw["plan_id"], new_date, plan_workout_id),
    ).fetchone()
    other_pw = dict(other) if other else None

    if other_pw and other_pw.get("actual_activity_id"):
        # Target day already has a completed run — don't clobber it.
        raise ValueError("destination day already has a completed workout")

    old_date = pw["planned_date"]
    old_dow = pw["day_of_week"]
    new_dow = new_date_d.weekday()  # Mon=0..Sun=6 — matches plan generator

    # Clear push state on both rows — re-push the new dates below.
    was_pushed_self = bool(pw.get("garmin_workout_id"))
    old_garmin_id_self = pw.get("garmin_workout_id")
    was_pushed_other = bool(other_pw and other_pw.get("garmin_workout_id"))
    old_garmin_id_other = other_pw.get("garmin_workout_id") if other_pw else None

    # Release both Garmin copies before clearing either row's push state. A
    # move changes the date, so a copy left behind sits on the *old* day — the
    # runner would see the session twice, on two dates.
    released_self = release_garmin_copy(client, old_garmin_id_self) if was_pushed_self else True
    released_other = release_garmin_copy(client, old_garmin_id_other) if was_pushed_other else True

    conn.execute(
        "UPDATE plan_workouts SET planned_date = ?, day_of_week = ? WHERE id = ?",
        (new_date, new_dow, plan_workout_id),
    )
    # A move changes the date, so an unreleased copy sits on the *old* day.
    # Keep its id as the handle, drop pushed_at so the row doesn't claim the
    # new date is on the watch.
    if released_self:
        conn.execute(
            "UPDATE plan_workouts SET garmin_workout_id = NULL, pushed_at = NULL "
            "WHERE id = ?",
            (plan_workout_id,),
        )
    else:
        conn.execute(
            "UPDATE plan_workouts SET pushed_at = NULL WHERE id = ?",
            (plan_workout_id,),
        )
    if other_pw:
        conn.execute(
            "UPDATE plan_workouts SET planned_date = ?, day_of_week = ? WHERE id = ?",
            (old_date, old_dow, other_pw["id"]),
        )
        if released_other:
            conn.execute(
                "UPDATE plan_workouts SET garmin_workout_id = NULL, pushed_at = NULL "
                "WHERE id = ?",
                (other_pw["id"],),
            )
        else:
            conn.execute(
                "UPDATE plan_workouts SET pushed_at = NULL WHERE id = ?",
                (other_pw["id"],),
            )
    conn.commit()

    re_pushed_ids: list[int] = []
    if client is not None:
        for (was_pushed, released, pw_id) in (
            (was_pushed_self, released_self, plan_workout_id),
            (was_pushed_other, released_other, other_pw["id"] if other_pw else None),
        ):
            if not was_pushed or pw_id is None:
                continue
            if not released:
                # Old copy still on Garmin at the old date; a re-push here
                # would add a second one rather than move it.
                continue
            refreshed = conn.execute(
                "SELECT workout_type, workout_structure FROM plan_workouts WHERE id = ?",
                (pw_id,),
            ).fetchone()
            if refreshed and is_pushable(refreshed["workout_type"], refreshed["workout_structure"]):
                try:
                    push_workout_to_garmin(conn, client, pw_id)
                    re_pushed_ids.append(pw_id)
                except Exception:  # noqa: BLE001
                    pass

    return {
        "moved": True,
        "swapped_with_id": other_pw["id"] if other_pw else None,
        "re_pushed_ids": re_pushed_ids,
    }


def cleanup_pushed_workouts(conn: sqlite3.Connection, client, plan_id: int) -> dict:
    """Best-effort: delete every Garmin workout previously pushed for this plan.

    Returns {"cleaned": int, "failed": int}. Per-call errors are swallowed so
    one bad row cannot abort the sweep, but the push state is cleared **only
    for workouts Garmin confirmed gone**.

    `garmin_workout_id` and `pushed_at` *are* the push state (architecture
    decision #4). Clearing them for a delete that failed would report "not on
    watch" for a workout still sitting on the watch, and throw away the only
    identifier that could retry the delete — so a later re-push would add a
    duplicate rather than replace it. Rows that failed keep their id; the
    caller is expected to surface `failed`.
    """
    rows = conn.execute(
        "SELECT id, garmin_workout_id FROM plan_workouts "
        "WHERE plan_id = ? AND garmin_workout_id IS NOT NULL",
        (plan_id,),
    ).fetchall()

    cleaned = 0
    failed = 0
    for r in rows:
        wid = r["garmin_workout_id"]
        try:
            client.delete_workout(wid)
        except Exception:  # noqa: BLE001 — best-effort, one bad row must not abort the sweep
            # Keep the id: the workout is still on the watch and this is the
            # only handle left to retry deleting it.
            failed += 1
            continue
        cleaned += 1
        conn.execute(
            "UPDATE plan_workouts SET garmin_workout_id = NULL, pushed_at = NULL WHERE id = ?",
            (r["id"],),
        )
    conn.commit()
    return {"cleaned": cleaned, "failed": failed}


def push_week_to_garmin(
    conn: sqlite3.Connection,
    client,
    plan_id: int,
    week_number: int,
) -> dict:
    """Push every pushable, not-yet-pushed workout in one week. Best-effort.

    Returns {"pushed": N, "skipped": M, "failed": [{"id":, "title":, "error":}], "week": <week_dict>}
    """
    rows = conn.execute(
        "SELECT * FROM plan_workouts "
        "WHERE plan_id = ? AND week_number = ? "
        "ORDER BY day_of_week",
        (plan_id, week_number),
    ).fetchall()

    today_iso = date.today().isoformat()
    pushed = 0
    skipped = 0
    failed: list[dict] = []
    for r in rows:
        pw = dict(r)
        if pw.get("pushed_at"):
            skipped += 1
            continue
        if pw.get("planned_date", "") < today_iso:
            # No value pushing yesterday's workout to the watch. Defensive
            # — the button is already gated by week_has_pushable, but
            # someone could hit this URL directly.
            skipped += 1
            continue
        if not is_pushable(pw["workout_type"], pw.get("workout_structure")):
            skipped += 1
            continue
        try:
            push_workout_to_garmin(conn, client, pw["id"])
            pushed += 1
        except Exception as exc:  # noqa: BLE001
            failed.append({"id": pw["id"], "title": pw["title"], "error": f"{type(exc).__name__}: {exc}"})
    return {"pushed": pushed, "skipped": skipped, "failed": failed}


def push_workout_to_garmin(conn: sqlite3.Connection, client, plan_workout_id: int) -> dict:
    """Upload one planned workout to Garmin and schedule it on its planned date.

    Upload and scheduling are separate Garmin gates, recorded separately:
    ``garmin_workout_id`` lands as soon as the upload succeeds, ``pushed_at``
    only once the schedule is confirmed. A row with an id but no ``pushed_at``
    is therefore a stranded upload from a failed schedule — this function
    clears it before uploading again, so a retry replaces that copy instead of
    leaving a second one behind.

    Returns the updated plan_workout row dict. Raises if the workout type isn't
    pushable in Stage 1, or if Garmin rejects the upload or the scheduling.
    """
    # Serialise per workout: "Push week" and an individual Push can otherwise
    # both read this row as unpushed, both upload, and the second DB write
    # overwrites the first id — leaving a duplicate on Garmin that no later
    # cleanup can find. Re-read inside the lock so the loser of the race sees
    # the winner's state and takes the replay no-op below.
    with push_lock("workout", plan_workout_id):
        return _push_workout_locked(conn, client, plan_workout_id)


def _push_workout_locked(conn: sqlite3.Connection, client, plan_workout_id: int) -> dict:
    row = conn.execute(
        "SELECT * FROM plan_workouts WHERE id = ?", (plan_workout_id,)
    ).fetchone()
    if not row:
        raise ValueError("workout not found")
    pw = dict(row)

    if not is_pushable(pw["workout_type"], pw.get("workout_structure")):
        msg = push_status(pw["workout_type"], pw.get("workout_structure")) or "not pushable"
        raise ValueError(msg)

    existing_id = pw.get("garmin_workout_id")

    # Already fully pushed: this is a replayed POST — a stale tab, a lost
    # response, or an individual push racing the bulk one. Uploading again
    # would add a second copy on Garmin *and* overwrite the id, orphaning the
    # first beyond the reach of any later cleanup. Treat it as a no-op.
    if existing_id is not None and pw.get("pushed_at"):
        return dict(pw)

    # Stranded upload from a previous failed schedule: release it before
    # adding another. If Garmin won't let go, don't pile a second copy on top.
    if existing_id is not None:
        if not release_garmin_copy(client, existing_id):
            raise RuntimeError(
                f"a previous upload (Garmin id {existing_id}) is still on "
                f"Garmin and could not be removed — remove it in Garmin "
                f"Connect, then push again"
            )
        conn.execute(
            "UPDATE plan_workouts SET garmin_workout_id = NULL WHERE id = ?",
            (plan_workout_id,),
        )
        conn.commit()

    workout_obj = planned_to_garmin_workout(pw)
    upload_resp = client.upload_running_workout(workout_obj)
    workout_id = upload_resp.get("workoutId")
    if not workout_id:
        raise RuntimeError(f"Garmin did not return a workout_id (resp keys: {list(upload_resp.keys())})")

    # Upload and scheduling are two separate Garmin gates. Record the id the
    # moment the upload lands: if scheduling then fails and we had saved
    # nothing, the uploaded copy would be stranded on Garmin with no local
    # handle, and a retry would upload a second one.
    conn.execute(
        "UPDATE plan_workouts SET garmin_workout_id = ? WHERE id = ?",
        (workout_id, plan_workout_id),
    )
    conn.commit()

    client.schedule_workout(workout_id, pw["planned_date"])

    # Only now is it on the calendar for the planned date, which is what
    # pushed_at asserts.
    conn.execute(
        "UPDATE plan_workouts SET pushed_at = datetime('now') WHERE id = ?",
        (plan_workout_id,),
    )
    conn.commit()

    refreshed = conn.execute(
        "SELECT * FROM plan_workouts WHERE id = ?", (plan_workout_id,)
    ).fetchone()
    return dict(refreshed)


def _methodology_label(mid: str) -> str:
    for info in list_methodologies():
        if info.id == mid:
            return info.name
    return mid
