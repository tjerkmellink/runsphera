"""Mike Foppen — Overleef de Heuvels, Gevorderden 15 km.

11-week imported plan for the **NN Zevenheuvelenloop** (15 km hilly race in
Nijmegen), authored by Mike Foppen (Olympic 5000m athlete).

Source: Mike Foppen's published "Overleef de Heuvels" 15 km training plan for the
2025 NN Zevenheuvelenloop. The plan's *structure* (week count, session cadence,
effort cues, progression) is reimplemented here; the original text is not
redistributed with this project.

Design notes:
- **Time-based, not distance-based.** Every step is a duration. No VDOT pace
  calibration — the plan is effort-based (RD / DT / INT cues, not pace zones).
- **3 sessions/week.** Default placement: Day 1 = Tue, Day 2 = Thu, Day 3 = Sat.
  **Race week (W11)** shifts to Day 1 = Mon, Day 2 = Wed, Day 3 = Sun (race).
- **Race day** is the only distance-based step (15 km = 15000 m).
- `days_per_week` and `long_run_day` from PlanParams are **ignored** — the
  plan has its own fixed schedule. `current_vdot` and `weekly_km_baseline`
  are also ignored.
- Only `race_date` (must be a Sunday) is consulted from PlanParams.
"""
from __future__ import annotations

from datetime import date, timedelta

from .methodology import (
    GOAL_DISTANCES_KM,
    Methodology,
    PlanParams,
    PlannedWorkout,
)

# Default weekday placement for sessions (0=Mon ... 6=Sun)
_DEFAULT_DAYS = (1, 3, 5)         # Tue, Thu, Sat
_RACE_WEEK_DAYS = (0, 2, 6)       # Mon, Wed, Sun(race)

# Run-day offsets from the long-run anchor (= race weekday, always Sunday) —
# the registry hands these to the plan form so the dimmed day pickers mirror
# the plan's real Tue/Thu/Sat pattern instead of the runner's stale picks.
RUN_DAY_OFFSETS = sorted((d - 6) % 7 for d in _DEFAULT_DAYS)

# Standard warmup + cooldown durations for interval sessions (seconds)
_WU = 600   # 10 min easy + dynamic drills
_CD = 300   # 5 min easy

# Phase mapping per week (used for the colored badge on the weekly card)
_PHASE_FOR_WEEK = {
    1: "base", 2: "base", 3: "base",
    4: "build", 5: "build", 6: "build",
    7: "peak", 8: "peak",
    9: "taper", 10: "taper", 11: "taper",
}


def _simple_step(duration_s: int, step_type: str = "active") -> dict:
    """A single time-based step with no pace target."""
    return {"type": step_type, "end": {"duration_s": duration_s}}


def _interval_structure(reps: int, active_s: int, recovery_s: int) -> dict:
    """Warmup + N × [active + recovery] + cooldown. All effort-based, no paces."""
    return {
        "steps": [
            {"type": "warmup", "end": {"duration_s": _WU}},
            {"type": "repeat", "iterations": reps, "steps": [
                {"type": "active", "end": {"duration_s": active_s}},
                {"type": "recovery", "end": {"duration_s": recovery_s}},
            ]},
            {"type": "cooldown", "end": {"duration_s": _CD}},
        ]
    }


def _simple_structure(duration_s: int) -> dict:
    return {"steps": [_simple_step(duration_s)]}


# Race-day Mike Foppen tips, embedded in the race workout description.
_RACE_TIPS = (
    "Mike's race-day tips:\n"
    "1) Divide the 15 km mentally into thirds (km 1-5, 6-10, 11-15) for "
    "deliberate pacing.\n"
    "2) The first kilometres climb (vals plat) — start a touch slower than "
    "your ideal race pace; most runners go out too hard here.\n"
    "3) Shorten your stride on climbs; on descents stay relaxed and let "
    "gravity help — don't brake with the quads.\n"
    "4) When fatigue hits in the last km, narrow focus to one step at a time."
)

# Course context shown on the race day card.
_RACE_COURSE = (
    "Course: first 7 km climb most of the elevation gain; km 7-10 on the "
    "Zevenheuvelenweg has the toughest remaining climbs; the last stretch is "
    "mostly downhill or flat — if you've paced well, lift the tempo there."
)


# ---- Weekly data ---------------------------------------------------------
# Each week is a list of 3 sessions (Day 1, Day 2, Day 3).
# weekly_challenge_text: appended to the description of the day where the
# challenge naturally fits (Day 1 unless otherwise specified by the source).
#
# Each session dict:
#   workout_type, title, description, duration_minutes,
#   workout_structure (optional, omit for simple workouts that fall back
#                      to a single time-based step from duration_minutes),
#   weekly_challenge_text (optional, attached to the description if present)

_WEEKS_DATA: list[list[dict]] = [
    # ----- Week 1 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 40 min",
            "description": "Forty minutes easy. Conversational pace, small light steps. Maintenance run — supports recovery and lays the base for the rest of the week. No warmup needed.",
            "duration_minutes": 40,
            "weekly_challenge_text": "Run one of this week's three sessions in the shape of the digit 7 (Strava/Garmin screenshot, tag @nnzevenheuvelenloop).",
        },
        {
            "workout_type": "tempo",
            "title": "DT 50 min",
            "description": "Fifty minutes at duurloop tempo. Above easy jog: full sentences yes, sustained conversation no. Trains endurance effectively without overload.",
            "duration_minutes": 50,
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 15 × 1 min / 1 min RD",
            "description": "Warmup, then 15 reps of 1 min interval pace / 1 min easy jog recovery. Word-by-word breathing during the hard minute. Sustainable pace across all 15; first 10 manageable, last 5 hard. Slow down if the early reps are already too hard.",
            "duration_minutes": 45,
            "workout_structure": _interval_structure(15, 60, 60),
        },
    ],
    # ----- Week 2 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 45 min",
            "description": "Forty-five minutes easy jog. Conversational. Builds base fitness and endurance foundation.",
            "duration_minutes": 45,
        },
        {
            "workout_type": "tempo",
            "title": "DT 50 min + sprint challenge",
            "description": "Fifty minutes at steady DT. Above easy jog — full sentences only. Finish with the sprint challenge.",
            "duration_minutes": 50,
            "weekly_challenge_text": "Sprint challenge: 40 seconds at full sprint at the end of this run. Only if you're used to sprinting. Screenshot the 40-sec peak speed.",
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 12 × 2 min / 1 min RD",
            "description": "Warmup, then 12 reps of 2 min interval pace / 1 min easy jog recovery. Heavy breathing, loose-word talking. First 8 manageable, last 4 hard. Pick a sustainable pace.",
            "duration_minutes": 55,
            "workout_structure": _interval_structure(12, 120, 60),
        },
    ],
    # ----- Week 3 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 45 min hilly",
            "description": "Forty-five minutes easy on hilly terrain. Keep the tempo relaxed — the hills add the stimulus, you don't need to push. Builds base + leg strength.",
            "duration_minutes": 45,
            "weekly_challenge_text": "Weak-point challenge: 40 reps or 40 sec of a strengthening exercise for your weakest area (calves, abs, glutes). E.g. 40 squats, 40 calf raises, 40-sec plank. Video/photo, tag @nnzevenheuvelenloop.",
        },
        {
            "workout_type": "tempo",
            "title": "DT 60 min progressive (last 15 min faster)",
            "description": "First 45 min at steady DT (full sentences). Last 15 min at firmer DT (short sentences only). Teaches you to lift the pace late and distribute energy.",
            "duration_minutes": 60,
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 10 × 3 min / 1 min RD",
            "description": "Warmup, then 10 reps of 3 min interval pace / 1 min easy jog. Higher breathing, loose-word talking. First 8 manageable, last 2 hard. Builds tempo capacity.",
            "duration_minutes": 55,
            "workout_structure": _interval_structure(10, 180, 60),
        },
    ],
    # ----- Week 4 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 40 min hilly",
            "description": "Forty minutes easy on hilly terrain. Conversational. Strengthens legs and accommodates elevation changes. Slow down if the hills make it uncomfortable.",
            "duration_minutes": 40,
            "weekly_challenge_text": "40,000 steps challenge: hit 40,000+ steps over the week (watch, phone or pedometer). Share total on Sunday with @nnzevenheuvelenloop.",
        },
        {
            "workout_type": "tempo",
            "title": "DT 60 min",
            "description": "Sixty minutes at steady DT. Full sentences yes, full conversation no. Continues building endurance.",
            "duration_minutes": 60,
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 20 × 1 min hill sprint / RD jog down",
            "description": "Warmup, then 20 hill sprints of 1 min uphill at hard pace; easy jog back down between reps. Strength, explosivity, speed on short climbs. Heavy breathing, word-by-word. Pick a sustainable pace across all 20. If the first 5-10 already feel too hard, slow down.",
            "duration_minutes": 55,
            "workout_structure": _interval_structure(20, 60, 60),
        },
    ],
    # ----- Week 5 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 45 min",
            "description": "Forty-five minutes easy. Conversational. Recovery + base maintenance.",
            "duration_minutes": 45,
        },
        {
            "workout_type": "tempo",
            "title": "DT 60 min progressive",
            "description": "Start the hour easy (full sentences). Build pace gradually. End at firmer DT (short sentences only). Trains pace-building across longer efforts.",
            "duration_minutes": 60,
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 40 min '40 stappen' rotation",
            "description": "Warmup, then 40 minutes of the 40-step rotation: 40 paces slow (RD), 40 paces normal (DT, full sentences), 40 paces fast (word-by-word breathing). Repeat for the full 40 minutes. Pick a sustainable fast pace.",
            "duration_minutes": 50,
            "workout_structure": {
                "steps": [
                    {"type": "warmup", "end": {"duration_s": _WU}},
                    {"type": "active", "end": {"duration_s": 2400}},
                    {"type": "cooldown", "end": {"duration_s": _CD}},
                ]
            },
            "weekly_challenge_text": "40 stappen challenge: today's Day 3 IS the challenge. Video showing the slow/normal/fast variation, tag @nnzevenheuvelenloop.",
        },
    ],
    # ----- Week 6 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 50 min with ≥7 hills",
            "description": "Fifty minutes hilly easy jog — include at least seven hills. Small steps just above walking pace uphill. Slow down if it gets uncomfortable.",
            "duration_minutes": 50,
            "weekly_challenge_text": "7 heuvels challenge: hit ≥7 hills in today's Day 1 run. Screenshot route + elevation from Strava/Garmin showing the hills.",
        },
        {
            "workout_type": "tempo",
            "title": "DT 70 min",
            "description": "Seventy minutes at steady DT. Comfortable but challenging — training endurance toward 15 km. Full sentences yes, full conversation no.",
            "duration_minutes": 70,
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 10 × 4 min / 90 sec RD",
            "description": "Warmup, then 10 reps of 4 min interval pace / 90 sec easy jog recovery. Heavy breathing, loose-word talking. First 8 manageable, last 2 hard. (In 2025 this Sunday session is run with the Nimma Running Club on Oct 12.)",
            "duration_minutes": 65,
            "workout_structure": _interval_structure(10, 240, 90),
        },
    ],
    # ----- Week 7 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 40 min",
            "description": "Forty minutes easy. Supports recovery, maintains base fitness so the body is ready for the harder sessions later in the week.",
            "duration_minutes": 40,
            "weekly_challenge_text": "Local Legend challenge: pick a short Strava segment and rack up 40 reps this week. Screenshot from Strava.",
        },
        {
            "workout_type": "tempo",
            "title": "DT 80 min",
            "description": "Eighty minutes at DT. Comfortable but firm — deeper breathing, full sentences only. Long tempo run building endurance toward 15 km. Teaches efficient energy use.",
            "duration_minutes": 80,
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 8 × 5 min / 90 sec RD",
            "description": "Warmup, then 8 reps of 5 min interval pace / 90 sec easy jog recovery. Heavy breathing, loose-word talking. Builds tempo-endurance — ability to hold race pace for longer stretches.",
            "duration_minutes": 70,
            "workout_structure": _interval_structure(8, 300, 90),
        },
    ],
    # ----- Week 8 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 40 min (no watch)",
            "description": "Forty minutes easy, without looking at your watch. Practice your sense of pace and time — land as close to 40 minutes as possible by feel alone.",
            "duration_minutes": 40,
            "weekly_challenge_text": "40 min challenge: today's run IS the challenge. Run 40 min without checking your watch, then see how close you got. Share screenshot + your estimate.",
        },
        {
            "workout_type": "tempo",
            "title": "DT 90 min — peak training",
            "description": "Ninety minutes at DT. Deep breathing, full sentences only — flowing conversation no longer possible. Peak training session of the build — teaches sustained energy efficiency, essential for a successful 15 km.",
            "duration_minutes": 90,
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 5 × 8 min / 2 min RD",
            "description": "Warmup, then 5 reps of 8 min interval pace / 2 min easy jog recovery. Long intervals — word-by-word breathing. Accustoms the body to extended efforts at high speed.",
            "duration_minutes": 70,
            "workout_structure": _interval_structure(5, 480, 120),
        },
    ],
    # ----- Week 9 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 40 min 40 sec",
            "description": "Forty minutes and forty seconds easy — the extra 40 seconds is a wink to the 40th edition of the race. Relaxed, conversational. Loosens legs, maintains base fitness.",
            "duration_minutes": 41,  # 40:40
            "workout_structure": _simple_structure(2440),
        },
        {
            "workout_type": "tempo",
            "title": "DT 75 min",
            "description": "Seventy-five minutes at DT. Faster than easy jog, deep breathing, full sentences only. Continued endurance build.",
            "duration_minutes": 75,
            "weekly_challenge_text": "Cijfer 40 challenge: work the number 40 into today's run creatively (finish at 40:40, average HR 140, pace 6:40/km, fastest km 5:40, etc.). Screenshot, tag @nnzevenheuvelenloop.",
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 25 × 40 sec / 40 sec RD",
            "description": "Warmup, then 25 reps of 40 sec interval pace / 40 sec easy jog recovery. Short, intense — breathing heavy but short duration keeps it sustainable. Sharpens speed, reactivity. NB: parcoursverkenning event on Sunday Nov 2 with Nimma Running Club — sign up via the official site.",
            "duration_minutes": 50,
            "workout_structure": _interval_structure(25, 40, 40),
        },
    ],
    # ----- Week 10 -----
    [
        {
            "workout_type": "easy",
            "title": "RD 45 min (draw '40' with GPS)",
            "description": "Forty-five minutes easy. While running, use GPS or Strava to draw the number 40 with your route — this week's challenge.",
            "duration_minutes": 45,
            "weekly_challenge_text": "Strava drawing challenge: run a route shaped like the number 40 (park, neighbourhood, or open field). Screenshot the 'drawing', tag @nnzevenheuvelenloop.",
        },
        {
            "workout_type": "tempo",
            "title": "DT 60 min progressive",
            "description": "Sixty minutes at DT, building gradually. Start relaxed, work toward a slightly faster but still controlled pace. Builds endurance and progressive-effort capacity.",
            "duration_minutes": 60,
        },
        {
            "workout_type": "intervals",
            "title": "INT WU + 15 × 2 min / 1 min RD",
            "description": "Warmup, then 15 reps of 2 min interval pace / 1 min easy jog recovery. Heavy breathing, hard to talk. Sharpens speed and the ability to repeat short intense efforts.",
            "duration_minutes": 60,
            "workout_structure": _interval_structure(15, 120, 60),
        },
    ],
    # ----- Week 11 — RACE WEEK -----
    # NB: race week uses _RACE_WEEK_DAYS = (Mon, Wed, Sun). Day 1+2 before Wed.
    [
        {
            "workout_type": "intervals",
            "title": "INT WU + 25 × 30 sec / 30 sec (before Wed)",
            "description": "Final activation before race day — DO BEFORE WEDNESDAY. Warmup, then 25 reps of 30 sec interval pace / 30 sec walk or easy jog recovery. Wakes the systems up. Heavy breathing but the short duration keeps it sustainable.",
            "duration_minutes": 35,
            "workout_structure": _interval_structure(25, 30, 30),
        },
        {
            "workout_type": "tempo",
            "title": "DT 40 min (before Wed)",
            "description": "Final endurance touch before tapering down — DO BEFORE WEDNESDAY. Forty minutes at DT. Calm but firm — deeper breathing than easy jog, short sentences possible.",
            "duration_minutes": 40,
        },
        {
            "workout_type": "race",
            "title": "🏁 RACE — NN Zevenheuvelenloop 15 km",
            "description": _RACE_COURSE + "\n\n" + _RACE_TIPS,
            "duration_minutes": 90,  # rough; gets overridden by target_time_s if set
            "target_distance_km": 15.0,
            "is_race": True,
        },
    ],
]


def _structure_for_session(session: dict) -> dict:
    """Get the structured Garmin step list — explicit if provided, else simple."""
    if "workout_structure" in session:
        return session["workout_structure"]
    return _simple_structure(session["duration_minutes"] * 60)


def _build_workout(
    week_num: int,
    day_of_week: int,
    planned_date: date,
    session: dict,
    target_time_s: int | None,
) -> PlannedWorkout:
    duration_s = session["duration_minutes"] * 60
    target_pace = None
    distance_km = session.get("target_distance_km")

    if session.get("is_race"):
        # Race workout — distance-based 15km, optional target time
        race_distance = GOAL_DISTANCES_KM["15k"]
        distance_km = race_distance
        if target_time_s and race_distance:
            duration_s = target_time_s
            target_pace = int(target_time_s / race_distance)
        structure = {
            "steps": [{
                "type": "active",
                "end": {"distance_m": int(race_distance * 1000)},
                **({"pace_s_per_km": target_pace} if target_pace else {}),
            }]
        }
    else:
        structure = _structure_for_session(session)

    description = session["description"]
    if session.get("weekly_challenge_text"):
        description = f"{description}\n\nWeekly challenge: {session['weekly_challenge_text']}"

    return PlannedWorkout(
        week_number=week_num,
        week_phase=_PHASE_FOR_WEEK[week_num],
        day_of_week=day_of_week,
        planned_date=planned_date,
        workout_type=session["workout_type"],
        title=session["title"],
        description=description,
        target_distance_km=distance_km,
        target_duration_s=duration_s,
        target_pace_s_per_km=target_pace,
        workout_structure=structure,
    )


def _rest_workout(week_num: int, day_of_week: int, planned_date: date) -> PlannedWorkout:
    return PlannedWorkout(
        week_number=week_num,
        week_phase=_PHASE_FOR_WEEK[week_num],
        day_of_week=day_of_week,
        planned_date=planned_date,
        workout_type="rest",
        title="Rest",
        description="Rest day — recovery between sessions. Optional 30-40 min cross-training (cycling, swimming, cross-trainer) or a short easy jog if you want a 4th session.",
    )


class MikeFoppen7Heuvelen(Methodology):
    """11-week NN Zevenheuvelenloop plan, advanced level, by Mike Foppen."""
    name = "foppen_7heuvelen"

    def total_weeks(self, goal_type: str, race_date: date | None, start_date: date) -> int:
        return 11

    def generate(self, params: PlanParams) -> list[PlannedWorkout]:
        if params.goal_type != "15k":
            raise ValueError(
                "The Mike Foppen plan is built for the NN Zevenheuvelenloop (15 km). "
                "Set goal to '15k' to use this methodology."
            )
        if params.race_date is None:
            raise ValueError("The Mike Foppen plan requires a race date.")
        if params.race_date.weekday() != 6:  # Sunday
            raise ValueError(
                "The NN Zevenheuvelenloop is run on a Sunday — please pick the Sunday race date."
            )

        race_date = params.race_date
        # Race week (W11) Monday = race date - 6 days
        race_week_monday = race_date - timedelta(days=6)
        # Plan Monday (start of W1) = 10 weeks before race week Monday
        plan_start = race_week_monday - timedelta(weeks=10)

        workouts: list[PlannedWorkout] = []
        for week_idx, week_data in enumerate(_WEEKS_DATA):
            week_number = week_idx + 1
            week_start = plan_start + timedelta(weeks=week_idx)
            is_race_week = week_number == 11
            day_slots = _RACE_WEEK_DAYS if is_race_week else _DEFAULT_DAYS

            # Map weekday -> session
            session_by_dow: dict[int, dict] = {}
            for session_idx, session in enumerate(week_data):
                session_by_dow[day_slots[session_idx]] = session

            for dow in range(7):
                planned_date = week_start + timedelta(days=dow)
                if dow in session_by_dow:
                    workouts.append(_build_workout(
                        week_number, dow, planned_date,
                        session_by_dow[dow], params.target_time_s,
                    ))
                else:
                    workouts.append(_rest_workout(week_number, dow, planned_date))

        return workouts
