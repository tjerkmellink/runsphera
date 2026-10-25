"""Couch to 5K — the classic 9-week run/walk on-ramp for absolute beginners.

The canonical NHS Couch to 5K programme: three sessions a week, every
session bracketed by a 5-minute brisk warmup walk and a 5-minute cooldown
walk, ramping from 8×1-minute runs in week 1 to a continuous 30-minute
(~5 km) graduation run in week 9.

Design notes:
- **Time-based and paceless.** A beginner has no VDOT and no pace zones;
  every step is a duration with effort cues only. No `X:XX/km` idioms
  appear anywhere (titles, descriptions, structures), so pace recalibration
  is structurally a no-op — and the registry sets `uses_vdot_paces=False`
  so the service refuses it outright.
- **Not fixed-schedule.** The runner picks exactly 3 training days;
  session 3 (the week's biggest) sits on `long_run_day`. That anchor is
  load-bearing: without a race date, `create_plan` synthesizes the goal
  date on the final week's long-run day, so the graduation run must live
  there for the race overlay to land on it.
- **Full 9 weeks, no compression.** With a race date the plan anchors so
  week 9 is race week (starting later than the chosen start week when the
  race is further out — the Higdon behaviour). A window shorter than
  9 weeks raises: dropping the gentle opening weeks isn't safe for a
  first-time runner.
- `current_vdot` and `weekly_km_baseline` are ignored.
"""
from __future__ import annotations

from datetime import date, timedelta

from .methodology import Methodology, PlanParams, PlannedWorkout

_TOTAL_WEEKS = 9

# Session-day offsets from the long-run day: two days apart, so a beginner
# never runs back-to-back — C25K's cardinal rule (the rest day between every
# session is where the adaptation happens). With a Sunday anchor this reads
# Wed / Fri / Sun. Exported so the registry can hand it to the plan form as
# the default day picks — the form and the engine's own fallback (below)
# must never disagree.
PREFERRED_DAY_OFFSETS = [-4, -2, 0]

# Every session: 5-min brisk warmup walk + main block + 5-min cooldown walk.
_WU = 300
_CD = 300

_PHASE_FOR_WEEK = {
    1: "base", 2: "base", 3: "base",
    4: "build", 5: "build", 6: "build",
    7: "peak", 8: "peak",
    9: "taper",
}

_RUN_CUE = (
    "Run at a gentle jog — you should be able to speak in short sentences. "
    "Walk briskly to recover, don't stroll."
)
_CONTINUOUS_CUE = (
    "Run the whole block at a gentle, conversational effort. "
    "Slowing down is fine; stopping is what we're training away."
)


def _rw(reps: int, run_s: int, walk_s: int) -> list[tuple[str, int]]:
    """Uniform run/walk repeats, flattened to (kind, seconds) pairs."""
    return [("run", run_s), ("walk", walk_s)] * reps


def _mins(seconds: int) -> str:
    """'90 s' / '1 min' / '2½ min' style label for titles."""
    if seconds < 120 and seconds % 60:
        return f"{seconds} s"
    if seconds % 60 == 30:
        return f"{seconds // 60}½ min"
    return f"{seconds // 60} min"


# ---- Programme data (NHS Couch to 5K) -------------------------------------
# Each week: list of 3 sessions. A session is either
#   {"segments": [(kind, seconds), ...]}   — run/walk alternation
#   {"run_s": N}                            — continuous run
# plus optional "title" / "description" overrides. Weeks with one dict and
# `"x3": True` repeat the same session three times.

_WEEKS: list[list[dict]] = [
    # Week 1 — 8 × (60 s run / 90 s walk)
    [{"segments": _rw(8, 60, 90)}] * 3,
    # Week 2 — 6 × (90 s run / 2 min walk)
    [{"segments": _rw(6, 90, 120)}] * 3,
    # Week 3 — 2 × (90 s run, 90 s walk, 3 min run, 3 min walk)
    [{"segments": [("run", 90), ("walk", 90), ("run", 180), ("walk", 180)] * 2,
      "title": "Run/walk 2×(1½ + 3 min runs)"}] * 3,
    # Week 4 — 3, 5, 3, 5 min runs with 90 s / 2½ min walks
    [{"segments": [("run", 180), ("walk", 90), ("run", 300), ("walk", 150),
                   ("run", 180), ("walk", 90), ("run", 300)],
      "title": "Run/walk 3-5-3-5 min runs"}] * 3,
    # Week 5 — three distinct sessions, ending in the first continuous 20 min
    [
        {"segments": [("run", 300), ("walk", 180), ("run", 300), ("walk", 180), ("run", 300)],
         "title": "Run/walk 3×5 min runs"},
        {"segments": [("run", 480), ("walk", 300), ("run", 480)],
         "title": "Run/walk 2×8 min runs"},
        {"run_s": 1200,
         "description": "Your first run without walk breaks — a milestone. "
                        + _CONTINUOUS_CUE},
    ],
    # Week 6 — last of the walk breaks, then 25 min continuous
    [
        {"segments": [("run", 300), ("walk", 180), ("run", 480), ("walk", 180), ("run", 300)],
         "title": "Run/walk 5-8-5 min runs"},
        {"segments": [("run", 600), ("walk", 180), ("run", 600)],
         "title": "Run/walk 2×10 min runs"},
        {"run_s": 1500,
         "description": "The walk breaks are behind you from here on. "
                        + _CONTINUOUS_CUE},
    ],
    # Weeks 7 / 8 / 9 — continuous 25 / 28 / 30 min
    [{"run_s": 1500}] * 3,
    [{"run_s": 1680}] * 3,
    [{"run_s": 1800}] * 3,
]

# Week 9 session 3 is the graduation run.
_GRADUATION = {
    "run_s": 1800,
    "title": "Graduation run 30 min (~5 km)",
    "description": (
        "The one it was all for: 30 minutes of continuous running — for most "
        "runners that's right around 5 km. Start gently, find your rhythm, "
        "and enjoy the last five minutes. You're a runner now."
    ),
}


def _session_title(session: dict) -> str:
    if "title" in session:
        return session["title"]
    if "run_s" in session:
        return f"Run {_mins(session['run_s'])}"
    segs = session["segments"]
    # Uniform repeats render as "Run/walk 8×(1 min run / 90 s walk)".
    reps = len(segs) // 2
    run_s, walk_s = segs[0][1], segs[1][1]
    return f"Run/walk {reps}×({_mins(run_s)} run / {_mins(walk_s)} walk)"


def _session_description(session: dict) -> str:
    if "description" in session:
        return session["description"]
    if "run_s" in session:
        return f"{_mins(session['run_s'])} of continuous running. " + _CONTINUOUS_CUE
    n_runs = sum(1 for kind, _ in session["segments"] if kind == "run")
    run_total = sum(s for kind, s in session["segments"] if kind == "run")
    return (
        f"Brisk 5-minute warmup walk, then {n_runs} blocks of running "
        f"({_mins(run_total)} running in total) with walking recoveries. "
        + _RUN_CUE
    )


def _session_structure(session: dict) -> dict:
    """Time-based steps, no pace targets anywhere — the same shapes the
    Garmin push already handles for the Foppen plan."""
    steps: list[dict] = [{"type": "warmup", "end": {"duration_s": _WU}}]
    if "run_s" in session:
        steps.append({"type": "active", "end": {"duration_s": session["run_s"]}})
    else:
        segs = session["segments"]
        reps = len(segs) // 2
        uniform = (
            reps >= 2
            and all(segs[i][1] == segs[0][1] for i in range(0, len(segs), 2))
            and all(segs[i][1] == segs[1][1] for i in range(1, len(segs), 2))
            and len(segs) % 2 == 0
        )
        if uniform:
            steps.append({"type": "repeat", "iterations": reps, "steps": [
                {"type": "active", "end": {"duration_s": segs[0][1]}},
                {"type": "recovery", "end": {"duration_s": segs[1][1]}},
            ]})
        else:
            for kind, secs in segs:
                steps.append({
                    "type": "active" if kind == "run" else "recovery",
                    "end": {"duration_s": secs},
                })
    steps.append({"type": "cooldown", "end": {"duration_s": _CD}})
    return {"steps": steps}


def _session_duration_s(session: dict) -> int:
    if "run_s" in session:
        main = session["run_s"]
    else:
        main = sum(secs for _, secs in session["segments"])
    return _WU + main + _CD


def _rest_workout(week: int, dow: int, planned_date: date) -> PlannedWorkout:
    return PlannedWorkout(
        week_number=week,
        week_phase=_PHASE_FOR_WEEK[week],
        day_of_week=dow,
        planned_date=planned_date,
        workout_type="rest",
        title="Rest",
        description=(
            "Rest day — this is where your body actually adapts. A walk or "
            "gentle stretching is fine; another run is not."
        ),
    )


class C25KPlan(Methodology):
    """NHS Couch to 5K: 9 weeks × 3 run/walk sessions, effort-based."""
    name = "c25k"

    def total_weeks(self, goal_type: str, race_date: date | None, start_date: date) -> int:
        return _TOTAL_WEEKS

    def generate(self, params: PlanParams) -> list[PlannedWorkout]:
        if params.goal_type != "5k":
            raise ValueError(
                "Couch to 5K builds toward exactly one thing — set the goal "
                "to '5k' to use this methodology."
            )
        if params.days_per_week != 3:
            raise ValueError(
                "Couch to 5K runs three sessions a week — pick exactly 3 "
                "training days."
            )

        # Session days: session 3 (the week's biggest) on long_run_day, the
        # other two picked days in week order. Without explicit picks, fall
        # back to two-days-apart spacing behind the long-run day.
        lrd = params.long_run_day
        if params.workout_days is not None:
            picked = sorted(set(params.workout_days))
            if lrd not in picked or len(picked) != 3:
                raise ValueError(
                    "pick exactly 3 training days including the long-run day"
                )
            others = [d for d in picked if d != lrd]
        else:
            others = sorted({(lrd + o) % 7 for o in PREFERRED_DAY_OFFSETS if o != 0})

        start_monday = params.start_date - timedelta(days=params.start_date.weekday())
        race_wd: int | None = None
        if params.race_date is not None:
            # Anchor so week 9 is race week; a shorter window is refused —
            # this programme has no weeks to spare for a brand-new runner.
            race_week_monday = params.race_date - timedelta(days=params.race_date.weekday())
            available = (race_week_monday - start_monday).days // 7 + 1
            if available < _TOTAL_WEEKS:
                raise ValueError(
                    "Couch to 5K needs its full 9 weeks — dropping the gentle "
                    "opening weeks isn't safe for a first-time runner. Pick a "
                    "race at least 9 weeks out."
                )
            start_monday = race_week_monday - timedelta(weeks=_TOTAL_WEEKS - 1)
            race_wd = params.race_date.weekday()

        workouts: list[PlannedWorkout] = []
        for week_idx, week_sessions in enumerate(_WEEKS):
            week_number = week_idx + 1
            week_start = start_monday + timedelta(weeks=week_idx)
            is_final = week_number == _TOTAL_WEEKS

            sessions = list(week_sessions)
            if is_final:
                sessions[2] = _GRADUATION

            # Final week: session 3 follows the race weekday so the race
            # overlay always lands on the graduation slot. If that collides
            # with one of the other picked days, the freed long-run day takes
            # its place so the week still holds three sessions.
            s3_day = race_wd if (is_final and race_wd is not None) else lrd
            remaining = sorted(({*others, lrd} - {s3_day}))[:2]
            session_by_dow = {s3_day: sessions[2]}
            for d, s in zip(remaining, sessions[:2]):
                session_by_dow[d] = s

            for dow in range(7):
                planned_date = week_start + timedelta(days=dow)
                session = session_by_dow.get(dow)
                if session is None:
                    workouts.append(_rest_workout(week_number, dow, planned_date))
                    continue
                is_continuous = "run_s" in session
                workouts.append(PlannedWorkout(
                    week_number=week_number,
                    week_phase=_PHASE_FOR_WEEK[week_number],
                    day_of_week=dow,
                    planned_date=planned_date,
                    workout_type="easy" if is_continuous else "intervals",
                    title=_session_title(session),
                    description=_session_description(session),
                    target_distance_km=None,   # a beginner's pace is unknown — no fake distances
                    target_duration_s=_session_duration_s(session),
                    target_pace_s_per_km=None,
                    workout_structure=_session_structure(session),
                ))

        # Race overlay: the goal date (booked race or synthesized graduation
        # day) replaces whatever sits on it.
        if params.race_date is not None:
            target_pace = None
            if params.target_time_s:
                target_pace = int(params.target_time_s / 5.0)
            for w in workouts:
                if w.planned_date == params.race_date:
                    w.workout_type = "race"
                    w.title = "🏁 Race day — 5 km"
                    w.description = (
                        "Graduation day: 5 kilometres, nine weeks in the "
                        "making. Start at the gentle effort you know; if "
                        "there's something left in the final kilometre, use it."
                    )
                    w.target_distance_km = 5.0
                    w.target_duration_s = params.target_time_s
                    w.target_pace_s_per_km = target_pace
                    w.workout_structure = None
                    break

        return workouts
