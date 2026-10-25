"""Hal Higdon — tiered, beginner-friendly marathon & half-marathon plans.

A *methodology engine* in the same spirit as the Pfitzinger one: it reproduces
Higdon's documented *framework* — the experience-tier ladder (Novice 1/2,
Intermediate 1/2, Advanced 1/2), the mostly-easy-mileage-plus-one-long-run
shape, the step-back weeks, the single/triple 20-miler, the short taper — and
generates the week-by-week prescription itself, metricised and calibrated to
the runner. It is not a transcription of the copyrighted halhigdon.com tables.

Design notes:
- **Beginner-friendly by construction.** Novice 1 is pure easy running (three
  short runs, one long run, one cross-training day) with *zero* quality work.
  Higher tiers layer on marathon-pace runs, tempo, hills, and speed. This is
  the plan for someone starting out.
- **Paces reuse the Daniels VDOT table** (`daniels._paces_for_vdot`), exactly
  like Pfitzinger. Higdon prescribes by effort, so the app shows effort-first
  descriptions but still attaches a zone pace under the hood → Garmin push,
  adherence matching, and recalibration all keep working. Zone map: easy/long
  → E, marathon-pace run → M (marathon goal) / T (half goal), tempo → T,
  hills/speed → I, cross → none.
- **Experience tier = `params.variant`** (one of the six tier keys). NULL/None
  falls back to Novice 1. The tier drives the weekly template, weekday volume,
  which quality sessions appear, and how many long runs hit the 20-mile peak.
- **Fixed weekly template** anchored to the long-run day (= race weekday);
  `days_per_week` / `workout_days` are ignored (`fixed_schedule=True`). The
  persisted schedule is derived from the generated workouts.
- **Two distances**: marathon (18 weeks) and half marathon (12 weeks). Short
  windows compress by dropping opening base weeks (never back-dated); under a
  per-distance floor `generate()` raises.
- **Race day** overlays the final week's long-run slot.

Source-of-truth doc: docs/higdon.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .methodology import (
    GOAL_DISTANCES_KM,
    Methodology,
    PlanParams,
    PlannedWorkout,
)
from .daniels import (
    _fmt_pace,
    _interval_structure,
    _paces_for_vdot,
    _structure_duration_s,
    _tempo_structure,
)

# ---- Plan shape ----------------------------------------------------------

_MARATHON_WEEKS = 18
_HALF_WEEKS = 12
# Below these there's no honest Higdon build left; generate() raises.
_MARATHON_MIN = 12
_HALF_MIN = 8

# Long-run distance ladder (km), one entry per week EXCEPT the final week
# (which is race day, overlaid separately). Metricised from Higdon's published
# long-run progressions: a gentle ramp with a step-back every ~3rd week, the
# signature 32 km (20-mile) peak, then a short taper. All tiers share the
# ladder; Intermediate/Advanced flatten the top few onto the peak (their two /
# three 20-milers) via `_Tier.flatten_top`.
_MARATHON_LONG_KM: list[float] = [
    10, 11, 8, 14, 16, 11, 19, 23, 16, 26, 27, 21, 29, 31, 19, 32, 13,
]  # weeks 1..17; week 18 = marathon
_HALF_LONG_KM: list[float] = [
    6, 8, 10, 8, 12, 14, 11, 15, 16, 13, 10,
]  # weeks 1..11; week 12 = half


def _full_weeks(goal_type: str) -> int:
    return _MARATHON_WEEKS if goal_type == "marathon" else _HALF_WEEKS


def _min_weeks(goal_type: str) -> int:
    return _MARATHON_MIN if goal_type == "marathon" else _HALF_MIN


def _long_ladder(goal_type: str) -> list[float]:
    return _MARATHON_LONG_KM if goal_type == "marathon" else _HALF_LONG_KM


# ---- Experience tiers ----------------------------------------------------

# Weekly template roles keyed by position `(day_of_week - long_run_day) % 7`.
# Position 0 is always the long-run day (= race weekday). Roles:
#   long | easy | run | pace | tempo | hills | speed | cross | rest
# 'easy' uses the tier's easy_km, 'run' uses run_km (Intermediate/Advanced
# weekday runs are longer). Quality roles (pace/tempo/hills/speed) only appear
# in the tiers that actually prescribe them.

@dataclass(frozen=True)
class _Tier:
    key: str
    label: str
    template: dict[int, str]
    easy_km: float          # 'easy' role headline distance (km)
    run_km: float           # 'run' role headline distance (km)
    quality_km: float       # pace / tempo headline distance (km)
    hill_reps: int = 8      # 'hills' role rep count (×400 m)
    speed_reps: int = 6     # 'speed' role rep count (×800 m)
    flatten_top: int = 0    # raise this many biggest long runs to the peak
    mp_longs: int = 0       # marathon only: this many longest runs get an MP finish


_TIERS: dict[str, _Tier] = {
    # Pure easy running + one long run + a cross-training day. No quality work.
    "novice_1": _Tier(
        key="novice_1", label="Novice 1",
        template={0: "long", 1: "rest", 2: "easy", 3: "easy", 4: "easy", 5: "rest", 6: "cross"},
        easy_km=5.0, run_km=5.0, quality_km=0.0,
    ),
    # Novice 1 + a mid-week goal-pace run, and goal-pace finishes on the
    # biggest long runs.
    "novice_2": _Tier(
        key="novice_2", label="Novice 2",
        template={0: "long", 1: "rest", 2: "easy", 3: "pace", 4: "easy", 5: "rest", 6: "cross"},
        easy_km=6.0, run_km=6.0, quality_km=8.0, mp_longs=3,
    ),
    # Five running days: a Saturday run stacked before the Sunday long run
    # (back-to-back), plus a mid-week goal-pace run. Two 20-milers.
    "intermediate_1": _Tier(
        key="intermediate_1", label="Intermediate 1",
        template={0: "long", 1: "rest", 2: "run", 3: "pace", 4: "run", 5: "rest", 6: "run"},
        easy_km=8.0, run_km=8.0, quality_km=10.0, flatten_top=2, mp_longs=3,
    ),
    # Intermediate 1 + a weekly tempo. Three 20-milers.
    "intermediate_2": _Tier(
        key="intermediate_2", label="Intermediate 2",
        template={0: "long", 1: "rest", 2: "run", 3: "tempo", 4: "pace", 5: "rest", 6: "run"},
        easy_km=9.0, run_km=9.0, quality_km=11.0, flatten_top=3, mp_longs=4,
    ),
    # Six running days with hill repeats, a goal-pace run, and a tempo.
    "advanced_1": _Tier(
        key="advanced_1", label="Advanced 1",
        template={0: "long", 1: "run", 2: "hills", 3: "pace", 4: "tempo", 5: "rest", 6: "run"},
        easy_km=9.0, run_km=9.0, quality_km=11.0, hill_reps=8, flatten_top=3, mp_longs=4,
    ),
    # Highest volume: six running days with 800 m speed work, tempo, and
    # goal-pace runs.
    "advanced_2": _Tier(
        key="advanced_2", label="Advanced 2",
        template={0: "long", 1: "run", 2: "speed", 3: "pace", 4: "tempo", 5: "rest", 6: "run"},
        easy_km=10.0, run_km=11.0, quality_km=12.0, speed_reps=6, flatten_top=3, mp_longs=5,
    ),
}

_DEFAULT_TIER = "novice_1"


def tier_day_offsets(variant: str) -> list[int]:
    """Run-day template positions for a tier — offsets from the long-run day,
    excluding rest and cross days (matching `_derive_fixed_schedule`). The
    registry attaches these to the variant picker so the form can mirror the
    tier's real weekly schedule; deriving them here keeps the engine template
    the single source of truth."""
    tier = _TIERS[variant]
    return sorted(p for p, role in tier.template.items() if role not in ("rest", "cross"))


def _tier_for(variant: str | None) -> _Tier:
    """Resolve the experience tier. None (legacy plans, missing picker) falls
    back to Novice 1; an unknown *value* raises — silently generating a
    different tier than the label stored on the plan would lie forever."""
    if variant is None:
        return _TIERS[_DEFAULT_TIER]
    tier = _TIERS.get(variant)
    if tier is None:
        known = ", ".join(_TIERS)
        raise ValueError(f"Unknown Higdon experience tier {variant!r} — expected one of: {known}")
    return tier


# ---- Long-run ladder shaping --------------------------------------------

def _long_km_by_week(goal_type: str, tier: _Tier) -> list[float]:
    """The tier's long-run distance for each frame week (1-based → index 0…).

    Starts from the shared ladder and, for Intermediate/Advanced **marathon**
    plans, raises the biggest `flatten_top` long runs to the ladder peak —
    Higdon's two/three 20-milers. Half plans keep the plain ladder (Higdon's
    half schedules peak once); the final taper long run is left alone."""
    ladder = list(_long_ladder(goal_type))
    peak = max(ladder)
    if tier.flatten_top > 0 and goal_type == "marathon":
        # Candidates exclude the last (taper) week so we never inflate the
        # pre-race easy long run. Pick the biggest `flatten_top` and lift them.
        candidates = sorted(
            range(len(ladder) - 1), key=lambda i: (ladder[i], i), reverse=True
        )
        for i in candidates[: tier.flatten_top]:
            ladder[i] = peak
    return ladder


def _mp_weeks(goal_type: str, tier: _Tier, long_km: list[float]) -> set[int]:
    """Frame weeks (1-based) whose long run gets a marathon-pace finish.

    Marathon only — the longest runs are where you rehearse race rhythm. Half
    plans keep long runs plain (their goal-pace work lives in the pace run)."""
    if goal_type != "marathon" or tier.mp_longs <= 0:
        return set()
    candidates = sorted(
        range(len(long_km) - 1), key=lambda i: (long_km[i], i), reverse=True
    )
    return {i + 1 for i in candidates[: tier.mp_longs]}


def _weekday_km(base: float, week: int, n_weeks: int) -> float:
    """Gentle weekday-run scaling: a modest mid-plan bump, a taper cut. Higdon
    weekday runs are famously near-constant, so the swing is small. `week` is
    1-based, so the race week is `n_weeks` itself and the taper week is the
    one before it — matching _phase_for's two taper-badged weeks."""
    if week >= n_weeks:              # race week
        scaled = base * 0.6
    elif week >= n_weeks - 1:        # taper week
        scaled = base * 0.8
    elif 0.4 * n_weeks <= week <= 0.8 * n_weeks:
        scaled = base * 1.2
    else:
        scaled = base
    return float(max(3, round(scaled)))


# ---- Role → workout builders --------------------------------------------

def _mp_long_structure(total_km: float, m_km: float, paces: dict[str, int]) -> dict:
    """Two-step easy→marathon-pace long run. Zone tags let the recalibrator
    rewrite each segment against its own zone (mirrors daniels/pfitzinger)."""
    return {
        "steps": [
            {"type": "active", "zone": "E",
             "end": {"distance_m": int((total_km - m_km) * 1000)},
             "pace_s_per_km": paces["E"]},
            {"type": "active", "zone": "M",
             "end": {"distance_m": int(m_km * 1000)},
             "pace_s_per_km": paces["M"]},
        ]
    }


def _easy_run(size: float, paces: dict[str, int]) -> dict:
    return {
        "workout_type": "easy",
        "title": f"Easy run {size:.0f} km",
        "description": (
            f"Easy {size:.0f} km at a relaxed, conversational pace "
            f"({_fmt_pace(paces['E'])}). Effort over pace — you should be able "
            "to chat the whole way."
        ),
        "distance_km": float(size),
        "pace_s": paces["E"],
        "structure": None,
    }


def _long_run(size: float, paces: dict[str, int], goal_type: str, mp: bool) -> dict:
    if mp and goal_type == "marathon":
        m_km = max(round(size * 0.3), 5)
        return {
            "workout_type": "long",
            "title": f"Long run {size:.0f} km incl. {m_km} km @ goal pace",
            "description": (
                f"{size - m_km:.0f} km easy ({_fmt_pace(paces['E'])}), then "
                f"{m_km} km at marathon goal pace (M, {_fmt_pace(paces['M'])}). "
                "Rehearse race rhythm on tired legs."
            ),
            "distance_km": float(size),
            "pace_s": paces["E"],
            "structure": _mp_long_structure(size, m_km, paces),
        }
    return {
        "workout_type": "long",
        "title": f"Long run {size:.0f} km",
        "description": (
            f"Steady long run at an easy, conversational pace "
            f"({_fmt_pace(paces['E'])}). Time on feet is the point — keep it "
            "relaxed and finish strong."
        ),
        "distance_km": float(size),
        "pace_s": paces["E"],
        "structure": None,
    }


def _pace_run(size: float, paces: dict[str, int], goal_type: str) -> dict:
    """Goal-pace run: marathon pace (M) for the marathon, half-marathon race
    pace (≈ T) for the half. Title chosen so the recalibrator rezones it right
    (`_zone_for_workout`: 'marathon-pace' → M, otherwise tempo → T)."""
    if goal_type == "marathon":
        zone, zpace = "M", paces["M"]
        title = f"Marathon-pace run {size:.0f} km"
        effort = "marathon goal pace"
    else:
        zone, zpace = "T", paces["T"]
        title = f"Half-pace run {size:.0f} km"
        effort = "half-marathon goal pace"
    return {
        "workout_type": "tempo",
        "title": title,
        "description": (
            f"Warm up, then settle into {effort} ({zone}, {_fmt_pace(zpace)}) "
            "for the main block, and cool down. Dial in race rhythm and effort."
        ),
        "distance_km": float(size),
        "pace_s": zpace,
        "structure": _tempo_structure(size, zpace),
    }


def _tempo_run(size: float, paces: dict[str, int]) -> dict:
    return {
        "workout_type": "tempo",
        "title": f"Tempo run {size:.0f} km",
        "description": (
            f"Warm up, then a sustained block at threshold pace "
            f"(T, {_fmt_pace(paces['T'])}) — 'comfortably hard'. Cool down. "
            "Raises the pace you can hold aerobically."
        ),
        "distance_km": float(size),
        "pace_s": paces["T"],
        "structure": _tempo_structure(size, paces["T"]),
    }


def _hill_repeats(reps: int, paces: dict[str, int]) -> dict:
    # Headline distance derived from the structure itself (WU 2 + CD 2 + reps
    # + 90 s jog-backs at easy pace) so the card, weekly totals, and the
    # pushed workout agree — same contract as _speed and Pfitzinger's VO₂max.
    jog_km = round(90 / paces["E"], 2)
    distance_km = round(4.0 + reps * (0.4 + jog_km), 1)
    return {
        "workout_type": "intervals",
        "title": f"Hill repeats {reps}×400 m",
        "description": (
            f"WU 2 km, then {reps}×400 m uphill hard at ~5K effort "
            f"(I, {_fmt_pace(paces['I'])}) with an easy jog back down to "
            "recover, CD 2 km. Builds strength and running economy."
        ),
        "distance_km": distance_km,
        "pace_s": paces["I"],
        "structure": _interval_structure(reps, 400, 90, paces["I"]),
    }


def _speed(reps: int, paces: dict[str, int]) -> dict:
    jog_km = round(120 / paces["E"], 2)
    distance_km = round(4.0 + reps * (0.8 + jog_km), 1)
    return {
        "workout_type": "intervals",
        "title": f"Speed {reps}×800 m",
        "description": (
            f"WU 2 km, {reps}×800 m at 5K effort (I, {_fmt_pace(paces['I'])}) "
            "with 2:00 jog recovery, CD 2 km. Sharpens leg speed and VO₂max."
        ),
        "distance_km": distance_km,
        "pace_s": paces["I"],
        "structure": _interval_structure(reps, 800, 120, paces["I"]),
    }


def _cross() -> dict:
    return {
        "workout_type": "cross",
        "title": "Cross-training",
        "description": (
            "30–60 min easy cross-training — bike, swim, elliptical, or a brisk "
            "walk. Aerobic work with no pounding. Take it fully off if you're "
            "beat up; the running is what matters."
        ),
        "distance_km": None,
        "pace_s": None,
        "structure": None,
    }


def _rest() -> dict:
    return {
        "workout_type": "rest",
        "title": "Rest",
        "description": "Full rest. Recovery is where the training actually sticks.",
        "distance_km": None,
        "pace_s": None,
        "structure": None,
    }


def _build_role(
    role: str,
    tier: _Tier,
    paces: dict[str, int],
    goal_type: str,
    week: int,
    n_weeks: int,
    long_km: float,
    mp: bool,
) -> dict:
    if role == "rest":
        return _rest()
    if role == "cross":
        return _cross()
    if role == "long":
        return _long_run(long_km, paces, goal_type, mp)
    if role == "easy":
        return _easy_run(_weekday_km(tier.easy_km, week, n_weeks), paces)
    if role == "run":
        return _easy_run(_weekday_km(tier.run_km, week, n_weeks), paces)
    if role == "pace":
        return _pace_run(_weekday_km(tier.quality_km, week, n_weeks), paces, goal_type)
    if role == "tempo":
        return _tempo_run(_weekday_km(tier.quality_km, week, n_weeks), paces)
    if role == "hills":
        return _hill_repeats(tier.hill_reps, paces)
    if role == "speed":
        return _speed(tier.speed_reps, paces)
    raise ValueError(f"unknown Higdon role: {role!r}")


# ---- Phase badges & window fitting --------------------------------------

def _phase_for(week: int, n_weeks: int, long_km: list[float], peak: float) -> str:
    """Map a frame week to the UI's base/build/peak/taper badge. Higdon has no
    named mesocycles, so this is derived from position + long-run size."""
    if week >= n_weeks - 1:                 # final long run + race week
        return "taper"
    if long_km[week - 1] >= 0.85 * peak:    # the 20-miler weeks
        return "peak"
    if week <= max(2, round(n_weeks * 0.4)):
        return "base"
    return "build"


def _effective_weeks(full: int, race_date: date, start_date: date) -> int:
    """How many of the `full` weeks fit between start_date and the race.
    Monday-aligned, inclusive of both the start and race weeks, capped at
    `full`."""
    race_week_monday = race_date - timedelta(days=race_date.weekday())
    start_monday = start_date - timedelta(days=start_date.weekday())
    available = (race_week_monday - start_monday).days // 7 + 1
    return min(full, available)


class HigdonPlan(Methodology):
    """Hal Higdon's tiered marathon & half-marathon plans, calibrated to VDOT."""
    name = "higdon"

    def total_weeks(self, goal_type: str, race_date: date | None, start_date: date) -> int:
        full = _full_weeks(goal_type)
        if race_date is None:
            return full
        return max(_effective_weeks(full, race_date, start_date), _min_weeks(goal_type))

    def generate(self, params: PlanParams) -> list[PlannedWorkout]:
        goal = params.goal_type
        if goal not in ("half_marathon", "marathon"):
            raise ValueError(
                "The Hal Higdon plans cover the half marathon and the marathon. "
                "Set your goal to 'half_marathon' or 'marathon' to use this "
                "methodology."
            )
        if params.race_date is None:
            raise ValueError("The Hal Higdon plan requires a race date.")

        full = _full_weeks(goal)
        n_weeks = _effective_weeks(full, params.race_date, params.start_date)
        floor = _min_weeks(goal)
        if n_weeks < floor:
            label = "marathon" if goal == "marathon" else "half-marathon"
            raise ValueError(
                f"The race is only {max(n_weeks, 0)} week(s) away — the Higdon "
                f"{label} plan needs at least {floor} weeks. Pick a later race "
                "date or the Daniels methodology for a shorter build."
            )
        offset = full - n_weeks  # opening base weeks dropped on a short window

        tier = _tier_for(params.variant)
        paces = _paces_for_vdot(params.current_vdot)
        long_run_day = params.race_date.weekday()

        long_km = _long_km_by_week(goal, tier)
        peak = max(long_km)
        mp_weeks = _mp_weeks(goal, tier, long_km)

        race_week_monday = params.race_date - timedelta(days=params.race_date.weekday())
        plan_start_monday = race_week_monday - timedelta(weeks=n_weeks - 1)

        workouts: list[PlannedWorkout] = []
        for week_idx in range(n_weeks):
            frame_week = week_idx + offset + 1     # 1-based week in the full frame
            display_week = week_idx + 1
            is_race_week = frame_week == full
            week_start = plan_start_monday + timedelta(weeks=week_idx)
            phase = _phase_for(frame_week, full, long_km, peak)
            wk_long = long_km[frame_week - 1] if frame_week - 1 < len(long_km) else peak

            for dow in range(7):
                planned_date = week_start + timedelta(days=dow)
                position = (dow - long_run_day) % 7
                role = tier.template[position]

                if is_race_week and position == 0:
                    w = _rest()  # race overlaid below
                elif is_race_week and role in ("long", "pace", "tempo", "hills", "speed"):
                    # Race week: strip quality, keep legs fresh with easy runs.
                    w = _easy_run(_weekday_km(tier.easy_km, frame_week, full), paces)
                else:
                    w = _build_role(
                        role, tier, paces, goal, frame_week, full,
                        wk_long, frame_week in mp_weeks,
                    )

                duration_s = _structure_duration_s(w["structure"])
                if duration_s is None and w["distance_km"] and w["pace_s"]:
                    duration_s = int(w["distance_km"] * w["pace_s"])

                workouts.append(PlannedWorkout(
                    week_number=display_week,
                    week_phase=phase,
                    day_of_week=dow,
                    planned_date=planned_date,
                    workout_type=w["workout_type"],
                    title=w["title"],
                    description=w["description"],
                    target_distance_km=w["distance_km"],
                    target_duration_s=duration_s,
                    target_pace_s_per_km=w["pace_s"],
                    workout_structure=w["structure"],
                ))

        # Race-day overlay on the final week's long-run slot.
        race_distance = GOAL_DISTANCES_KM[goal]
        target_pace = None
        if params.target_time_s and race_distance:
            target_pace = int(params.target_time_s / race_distance)
        label = "Marathon" if goal == "marathon" else "Half marathon"
        for w in workouts:
            if w.planned_date == params.race_date:
                w.workout_type = "race"
                w.title = f"🏁 Race day — {label} {race_distance:.4g} km"
                w.description = (
                    f"{n_weeks} weeks of work come due. Target pace: "
                    f"{_fmt_pace(target_pace)}. Start easy, run the smart race "
                    "you trained for."
                    if target_pace else
                    f"{n_weeks} weeks of work come due. Start conservatively and "
                    "trust your training — the race gets real in the back half."
                )
                w.target_distance_km = race_distance
                w.target_duration_s = params.target_time_s
                w.target_pace_s_per_km = target_pace
                w.workout_structure = None
                break

        return workouts
