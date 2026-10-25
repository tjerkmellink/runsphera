"""Pete Pfitzinger — 18-week / ~55 mpw marathon build ("18/55").

A *methodology engine*, not a transcription of the copyrighted week-by-week
schedule from *Advanced Marathoning*. It reproduces Pfitzinger's documented
framework — four mesocycles, his signature workout vocabulary, the 18-week /
~55-mile-peak shape — and calibrates every pace and distance to the runner's
own fitness. Distances are metric throughout.

Design notes:
- **Paces reuse the Daniels VDOT table.** Pfitzinger prescribes efforts by
  reference to race paces that map cleanly onto Daniels' zones:
  general-aerobic / recovery / long / medium-long → E, lactate-threshold
  ("15K–half-marathon pace") → T, VO₂max ("5K pace") → I, marathon-pace → M.
  So `daniels._paces_for_vdot` is the single source of pace truth, and the
  existing recalibrate / swap / Garmin-push machinery works unchanged.
- **Signature workouts** mapped onto the app's workout-type enum
  (easy/tempo/intervals/long/recovery/rest/race): medium-long run → `long`
  (titled "Medium-long"), lactate-threshold → `tempo`, VO₂max → `intervals`,
  marathon-pace long run → `long` with the two-step E+M `workout_structure`
  (same shape Daniels uses for its peak long run), tune-up race → `race`,
  general-aerobic → `easy`, recovery → `recovery`.
- **Fixed weekly template** anchored to the long-run day (= race weekday).
  ~5 running days. `days_per_week` / `workout_days` from PlanParams are
  **ignored** — the registry marks this `fixed_schedule=True` so the form
  neutralises the pickers and create_plan persists the generated schedule.
- **Volume** ramps from the runner's baseline toward the ~88 km (55-mile) peak
  with periodic step-back weeks; the 3-week taper sheds as a fraction of the
  peak. When the runner's recent base is well below what the plan assumes, a
  caution line is attached to the week-1 long run (the plan stays faithful to
  18/55 rather than silently capping — the runner stays in control).
- **Short windows compress**: with 12–17 weeks to the race, opening endurance
  weeks are dropped (never back-dated into the past); under 12 weeks
  generate() raises.
- **Race day** is the final week's long-run slot, overlaid with the marathon.
- Requires `goal_type == "marathon"` and a `race_date`.

Source-of-truth doc: docs/pfitzinger_18_55.md.
"""
from __future__ import annotations

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

# Four Pfitzinger mesocycles. Internal phase names map to the UI's
# base/build/peak/taper badges via _BADGE.
_PHASE_LAYOUT: list[tuple[str, int]] = [
    ("endurance", 6),       # aerobic base + volume; LT introduced late
    ("lt_endurance", 5),    # lactate-threshold emphasis, MP long runs begin
    ("race_prep", 4),       # VO₂max, marathon-pace long runs, tune-up races
    ("taper", 3),           # sharpen + shed fatigue; week 18 is race week
]
TOTAL_WEEKS = sum(n for _, n in _PHASE_LAYOUT)  # 18

_BADGE = {
    "endurance": "base",
    "lt_endurance": "build",
    "race_prep": "peak",
    "taper": "taper",
}

# Per-week load as a position on the baseline→peak line (0.0 = baseline floor,
# 1.0 = ~88 km peak). Step-backs every ~3rd week. 18 values; the last three
# (taper) are unused — taper volume is a fraction of the peak (_TAPER_FRACS)
# so high-baseline runners still shed real volume.
_LOAD_POS: list[float] = [
    # endurance (6)
    0.00, 0.22, 0.40, 0.26, 0.52, 0.64,
    # lt_endurance (5)
    0.76, 0.60, 0.90, 0.80, 1.00,
    # race_prep (4)  — wk12 & wk14 carry tune-up races (lighter around them)
    0.70, 0.96, 0.66, 0.86,
    # taper (3) — unused, see _TAPER_FRACS; wk18 (race week) handled specially
    0.00, 0.00, 0.00,
]

# Taper volume as a fraction of the peak (weeks 16, 17). The book sheds to
# ~80% then ~58% of peak mileage before race week.
_TAPER_FRACS = (0.80, 0.58)

# Volume anchors (km). Peak ≈ 55 miles. Baseline is floored so the opening
# weeks are a real marathon build, not a jog, and capped at the peak — the
# 18/55 targets ~88 km regardless of a bigger base (that runner wants 18/70).
_PEAK_KM = 88.0
_BASE_FLOOR_KM = 40.0
# When the runner's 4-week base sits this far (km) below the plan's week-1
# volume, attach the ramp-conservatively caution to week 1.
_MISMATCH_GAP_KM = 12.0

# Pfitzinger long-run ceiling (km). His long runs top out around 20–21 miles;
# at peak volume the 38% share hits this cap, producing the signature 32 km runs.
_LONG_CAP_KM = 32.0
_MLR_CAP_KM = 24.0

# Marathon-pace long runs are shorter than the biggest plain long runs (the
# book's MP sessions total 21–29 km), and the MP block grows as race prep
# progresses: 13 mi w/ 8 @ MP early → 18 mi w/ 14 @ MP late.
_MP_LONG_CAP_KM = 29.0
_MP_FRACTION_DEFAULT = 0.50
_MP_FRACTION = {11: 0.50, 13: 0.60, 15: 0.70}  # global (18-week-frame) week → MP share

# Global week indices (1-based, 18-week frame) that host a tune-up race in
# race_prep — raced the day before the long run, book-style.
_TUNEUP_WEEKS = frozenset({12, 14})

# Fewer than this many weeks to the race and the build can't be trimmed
# further (only endurance weeks are dropped — the book's own 12-week variant
# is the floor).
_MIN_WEEKS = 12

# Weekly-template positions, measured as (day_of_week - long_run_day) % 7:
#   0 = long-run day, 1 = day after (rest), 2 = quality A, 3 = medium-long,
#   4 = recovery, 5 = general-aerobic (+ strides), 6 = rest.
_POS_LONG = 0
_POS_REST_A = 1
_POS_QUALITY = 2
_POS_MLR = 3
_POS_RECOVERY = 4
_POS_GA = 5
_POS_REST_B = 6

# Run-day offsets from the long-run day (rest positions excluded) — the
# registry hands these to the plan form so the dimmed day pickers can mirror
# the engine's real 5-day schedule instead of the runner's stale picks.
RUN_DAY_OFFSETS = sorted((_POS_LONG, _POS_QUALITY, _POS_MLR, _POS_RECOVERY, _POS_GA))


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _weekly_km(week_idx: int, baseline: float) -> float:
    """Volume target for a normal (non-race) week, indexed in the 18-week
    frame. Ramps baseline→peak; taper weeks shed from the peak itself."""
    taper_idx = week_idx - (TOTAL_WEEKS - 3)
    if taper_idx >= 0:
        frac = _TAPER_FRACS[min(taper_idx, len(_TAPER_FRACS) - 1)]
        return round(_PEAK_KM * frac, 1)
    start = min(max(baseline, _BASE_FLOOR_KM), _PEAK_KM)
    return round(start + _LOAD_POS[week_idx] * (_PEAK_KM - start), 1)


def _sizes(weekly_km: float) -> dict[str, float]:
    """Split a week's volume across Pfitzinger's session roles (km)."""
    long_km = _clamp(round(weekly_km * 0.38), 14, _LONG_CAP_KM)
    mlr_km = _clamp(round(weekly_km * 0.24), 11, _MLR_CAP_KM)
    quality_km = _clamp(round(weekly_km * 0.16), 8, 14)
    recovery_km = _clamp(round(weekly_km * 0.10), 4, 9)
    ga_km = max(round(weekly_km - long_km - mlr_km - quality_km - recovery_km), 6)
    return {
        "long": float(long_km),
        "mlr": float(mlr_km),
        "quality": float(quality_km),
        "recovery": float(recovery_km),
        "ga": float(ga_km),
    }


# ---- Role → workout builders --------------------------------------------

def _mp_long_structure(total_km: float, m_km: float, paces: dict[str, int]) -> dict:
    """Two-step easy→marathon-pace long run. Zone tags let the recalibrator
    rewrite each segment against its own zone (mirrors daniels' peak long)."""
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


def _long_run(role: str, size: float, paces: dict[str, int], mp_frac: float = _MP_FRACTION_DEFAULT) -> dict:
    """The weekend long run — plain, or with a marathon-pace finish."""
    if role == "mp_long":
        m_km = max(round(size * mp_frac), 5)
        structure = _mp_long_structure(size, m_km, paces)
        return {
            "workout_type": "long",
            "title": f"Long {size:.0f} km incl. {m_km} km @ MP",
            "description": (
                f"Endurance {size - m_km:.0f} km easy ({_fmt_pace(paces['E'])}), "
                f"then {m_km} km at marathon pace (M, {_fmt_pace(paces['M'])}). "
                "Practice race rhythm on tired legs."
            ),
            "distance_km": float(size),
            "pace_s": paces["E"],
            "structure": structure,
        }
    return {
        "workout_type": "long",
        "title": f"Long {size:.0f} km",
        "description": (
            f"Steady aerobic long run, ~{_fmt_pace(paces['E'])}. "
            "The backbone of the marathon build — time on feet."
        ),
        "distance_km": float(size),
        "pace_s": paces["E"],
        "structure": None,
    }


def _medium_long(size: float, paces: dict[str, int]) -> dict:
    """Pfitzinger's signature mid-week medium-long run."""
    return {
        "workout_type": "long",
        "title": f"Medium-long {size:.0f} km",
        "description": (
            f"Mid-week medium-long run, {size:.0f} km easy ({_fmt_pace(paces['E'])}). "
            "Extends aerobic endurance without the recovery cost of a second long run."
        ),
        "distance_km": float(size),
        "pace_s": paces["E"],
        "structure": None,
    }


def _lactate_threshold(size: float, paces: dict[str, int]) -> dict:
    """LT tempo: warmup + sustained block at T pace + cooldown."""
    # The T block is the middle of the session; _tempo_structure carves 2 km
    # warmup + 2 km cooldown when there's room.
    return {
        "workout_type": "tempo",
        "title": f"Lactate threshold {size:.0f} km",
        "description": (
            f"Warm up, then a sustained block at lactate-threshold pace "
            f"(T, {_fmt_pace(paces['T'])}) — 15K-to-half effort, "
            "'comfortably hard'. Cool down. Raises the pace you can hold aerobically."
        ),
        "distance_km": float(size),
        "pace_s": paces["T"],
        "structure": _tempo_structure(size, paces["T"]),
    }


def _vo2max(size: float, paces: dict[str, int], short: bool = False) -> dict:
    """VO₂max intervals at I pace (5K effort). Short variant for the taper.

    `size` (the weekly quality allocation) only picks the rep count; the
    headline distance is derived from the structure itself (WU + reps +
    jog recoveries + CD) so cards, weekly totals, and the pushed workout
    all agree."""
    reps = 4 if short else (5 if size < 11 else 6)
    rep_m = 1000
    jog_km = round(120 / paces["E"], 2)  # 2:00 recovery jog at easy pace
    distance_km = round(4.0 + reps * (rep_m / 1000 + jog_km), 1)
    return {
        "workout_type": "intervals",
        "title": f"VO₂max {reps}×1000 m",
        "description": (
            f"WU 2 km, {reps}×1000 m at VO₂max pace (I, {_fmt_pace(paces['I'])}) "
            "with 2:00 jog recovery, CD 2 km. ~5K effort — sharpens aerobic power."
        ),
        "distance_km": distance_km,
        "pace_s": paces["I"],
        "structure": _interval_structure(reps, rep_m, 120, paces["I"]),
    }


def _general_aerobic(size: float, paces: dict[str, int], strides: bool = False) -> dict:
    desc = f"General aerobic run, {size:.0f} km at a steady easy pace ({_fmt_pace(paces['E'])})."
    title = f"General aerobic {size:.0f} km"
    if strides:
        desc += " Finish with 6×100 m strides — relaxed, controlled leg speed."
        title += " + strides"
    return {
        "workout_type": "easy",
        "title": title,
        "description": desc,
        "distance_km": float(size),
        "pace_s": paces["E"],
        "structure": None,
    }


def _recovery(size: float, paces: dict[str, int]) -> dict:
    return {
        "workout_type": "recovery",
        "title": f"Recovery {size:.0f} km",
        "description": (
            f"Short, very easy recovery run — slower than general aerobic. "
            f"Keep it relaxed (≥{_fmt_pace(paces['E'])}). Flush the legs, add no fatigue."
        ),
        "distance_km": float(size),
        "pace_s": paces["E"],
        "structure": None,
    }


def _tuneup_race(paces: dict[str, int]) -> dict:
    """A mid-plan tune-up race (8–15 km), run as a hard effort. If you don't
    have a real race that weekend, run it as a solo time trial or move it."""
    dist = 15.0
    return {
        "workout_type": "race",
        "title": "Tune-up race ~15 km",
        "description": (
            "Tune-up race, 8–15 km. Race it — a hard, honest effort that "
            "sharpens fitness and rehearses race-day logistics. No real race "
            "this weekend? Run a solo time trial at the same effort, or move "
            "this to a nearby race date."
        ),
        "distance_km": dist,
        "pace_s": paces["T"],
        "structure": None,
    }


def _rest() -> dict:
    return {
        "workout_type": "rest",
        "title": "Rest",
        "description": "Full rest or light cross-training (walk, swim, easy bike).",
        "distance_km": None,
        "pace_s": None,
        "structure": None,
    }


# ---- Weekly assembly -----------------------------------------------------

def _role_for(phase: str, week_in_phase: int, global_week: int, position: int) -> str:
    """Resolve the session role for one day, given its template position.
    `global_week` is always in the 18-week frame, even on compressed plans,
    so the tune-up / MP anchors stay tied to the race."""
    if position == _POS_REST_A:
        return "rest"
    if position == _POS_REST_B:
        # Book-style: the tune-up race is the day BEFORE the long run.
        return "tuneup" if global_week in _TUNEUP_WEEKS else "rest"
    if position == _POS_RECOVERY:
        return "recovery"
    if position == _POS_MLR:
        return "mlr"

    if position == _POS_LONG:
        if global_week in _TUNEUP_WEEKS:
            return "post_race_long"   # shorter steady long run on tired legs
        if phase == "race_prep":
            return "mp_long"
        if phase == "lt_endurance" and week_in_phase == 4:
            return "mp_long"          # last LT-block long run rehearses MP
        return "long"

    if position == _POS_QUALITY:
        if phase == "endurance":
            return "lt" if week_in_phase >= 2 else "ga"   # LT enters ~week 3
        if phase == "lt_endurance":
            return "lt"
        # race_prep and taper both sharpen with VO₂max — the book's taper
        # keeps short 5K-pace touches and drops threshold volume entirely.
        return "vo2_short" if phase == "taper" else "vo2"

    if position == _POS_GA:
        # Rest up the day before racing a tune-up (GA day precedes _POS_REST_B).
        return "rest" if global_week in _TUNEUP_WEEKS else "ga_strides"

    return "rest"


def _build_role(role: str, sizes: dict[str, float], paces: dict[str, int], global_week: int) -> dict:
    if role == "rest":
        return _rest()
    if role == "recovery":
        return _recovery(sizes["recovery"], paces)
    if role == "mlr":
        return _medium_long(sizes["mlr"], paces)
    if role == "long":
        return _long_run("long", sizes["long"], paces)
    if role == "post_race_long":
        w = _long_run("long", max(round(sizes["long"] * 0.85), 14), paces)
        w["description"] += (
            " The day after the tune-up race — steady, honest effort on tired legs."
        )
        return w
    if role == "mp_long":
        size = min(sizes["long"], _MP_LONG_CAP_KM)
        frac = _MP_FRACTION.get(global_week, _MP_FRACTION_DEFAULT)
        return _long_run("mp_long", size, paces, frac)
    if role == "tuneup":
        return _tuneup_race(paces)
    if role == "lt":
        return _lactate_threshold(sizes["quality"], paces)
    if role == "vo2":
        return _vo2max(sizes["quality"], paces)
    if role == "vo2_short":
        return _vo2max(max(sizes["quality"] - 2, 6), paces, short=True)
    if role == "ga":
        return _general_aerobic(sizes["ga"], paces)
    if role == "ga_strides":
        return _general_aerobic(sizes["ga"], paces, strides=True)
    raise ValueError(f"unknown session role: {role!r}")


# Race week (week 18): minimal freshening runs, keyed by template position.
# The long-run slot rests here and is overlaid with the marathon in generate().
def _race_week_day(position: int, paces: dict[str, int]) -> dict:
    if position == _POS_QUALITY:  # Tue — dress-rehearsal touch of race pace
        return {
            "workout_type": "tempo",
            "title": "Race-pace tune 7 km",
            "description": (
                f"Easy with 3 km at marathon pace (M, {_fmt_pace(paces['M'])}) in the "
                "middle. Wake the legs up; stay well within yourself."
            ),
            "distance_km": 7.0,
            "pace_s": paces["M"],
            "structure": _tempo_structure(7.0, paces["M"]),
        }
    if position == _POS_MLR:  # Wed — short GA + strides
        return _general_aerobic(8.0, paces, strides=True)
    if position == _POS_RECOVERY:  # Thu — recovery
        return _recovery(5.0, paces)
    if position == _POS_GA:  # Fri — very short shakeout
        return {
            "workout_type": "recovery",
            "title": "Shakeout 4 km",
            "description": (
                f"Optional 4 km very easy shakeout ({_fmt_pace(paces['E'])}) with "
                "a few strides. Legs fresh for Sunday."
            ),
            "distance_km": 4.0,
            "pace_s": paces["E"],
            "structure": None,
        }
    # Mon, Sat, and the long-run slot (race, overlaid later) → rest
    return _rest()


def _effective_weeks(race_date: date, start_date: date) -> int:
    """How many of the 18 weeks fit between start_date and the race.

    Counts Monday-aligned weeks from the start week through the race week,
    inclusive, capped at the full 18. The caller decides what to do when
    fewer than _MIN_WEEKS fit."""
    race_week_monday = race_date - timedelta(days=race_date.weekday())
    start_monday = start_date - timedelta(days=start_date.weekday())
    available = (race_week_monday - start_monday).days // 7 + 1
    return min(TOTAL_WEEKS, available)


class Pfitzinger18_55(Methodology):
    """18-week, ~55-mile-peak Pfitzinger marathon build, calibrated to VDOT."""
    name = "pfitzinger"

    def total_weeks(self, goal_type: str, race_date: date | None, start_date: date) -> int:
        if race_date is None:
            return TOTAL_WEEKS
        return max(_effective_weeks(race_date, start_date), _MIN_WEEKS)

    def generate(self, params: PlanParams) -> list[PlannedWorkout]:
        if params.goal_type != "marathon":
            raise ValueError(
                "The Pfitzinger 18/55 plan is a marathon build. Set goal to "
                "'marathon' to use this methodology."
            )
        if params.race_date is None:
            raise ValueError("The Pfitzinger 18/55 plan requires a race date.")

        # Fit the build to the time actually available: with less than 18
        # weeks to the race, drop opening endurance weeks (the book's own
        # shorter variant trims the base, never the sharpening) instead of
        # back-dating weeks into the past. Below 12 weeks there is no
        # honest Pfitzinger build left.
        n_weeks = _effective_weeks(params.race_date, params.start_date)
        if n_weeks < _MIN_WEEKS:
            raise ValueError(
                f"The race is only {max(n_weeks, 0)} week(s) away — the Pfitzinger "
                f"18/55 build needs at least {_MIN_WEEKS} weeks. Pick a later race "
                "or the Daniels methodology."
            )
        offset = TOTAL_WEEKS - n_weeks  # how many endurance weeks were dropped

        paces = _paces_for_vdot(params.current_vdot)
        long_run_day = params.race_date.weekday()  # anchor the week to race weekday

        # The final week's long-run slot is race day. Walk back to week-1 Monday.
        race_week_monday = params.race_date - timedelta(days=params.race_date.weekday())
        plan_start_monday = race_week_monday - timedelta(weeks=n_weeks - 1)

        # Flatten the phase layout into a per-week (phase, week_in_phase) list,
        # then trim the dropped endurance weeks off the front. Week indices in
        # role/volume logic stay in the 18-week frame so tune-ups, MP runs, and
        # the taper keep their distance-to-race anchoring.
        weeks_phases: list[tuple[str, int]] = []
        for phase, count in _PHASE_LAYOUT:
            for w in range(count):
                weeks_phases.append((phase, w))
        weeks_phases = weeks_phases[offset:]

        # Baseline-vs-plan mismatch caution, attached to week 1's long run.
        baseline = params.weekly_km_baseline
        week1_km = _weekly_km(offset, baseline)
        mismatch_note = None
        if baseline + _MISMATCH_GAP_KM < week1_km:
            mismatch_note = (
                f"\n\nHeads up: this 18/55 build opens near {week1_km:.0f} km/week and "
                f"peaks around {_PEAK_KM:.0f} km/week — well above your recent "
                f"~{baseline:.0f} km/week base. Ramp conservatively, treat the easy "
                "paces as ceilings, and back off if anything nags. The numbers are "
                "the plan's; your body has the final say."
            )

        workouts: list[PlannedWorkout] = []
        for week_idx, (phase, week_in_phase) in enumerate(weeks_phases):
            frame_idx = week_idx + offset          # index in the 18-week frame
            global_week = frame_idx + 1            # book week number (drives roles)
            display_week = week_idx + 1            # week_number shown to the user
            is_race_week = global_week == TOTAL_WEEKS
            week_start = plan_start_monday + timedelta(weeks=week_idx)
            weekly_km = _weekly_km(frame_idx, baseline)
            sizes = _sizes(weekly_km)

            for dow in range(7):
                planned_date = week_start + timedelta(days=dow)
                position = (dow - long_run_day) % 7

                if is_race_week:
                    if position == _POS_LONG:
                        w = _rest()  # overlaid with the race below
                    else:
                        w = _race_week_day(position, paces)
                else:
                    role = _role_for(phase, week_in_phase, global_week, position)
                    w = _build_role(role, sizes, paces, global_week)
                    if week_idx == 0 and position == _POS_LONG and mismatch_note:
                        w = dict(w)
                        w["description"] = w["description"] + mismatch_note

                duration_s = _structure_duration_s(w["structure"])
                if duration_s is None and w["distance_km"] and w["pace_s"]:
                    duration_s = int(w["distance_km"] * w["pace_s"])

                workouts.append(PlannedWorkout(
                    week_number=display_week,
                    week_phase=_BADGE[phase],
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

        # Race-day overlay: the marathon replaces week-18's long-run slot.
        race_distance = GOAL_DISTANCES_KM["marathon"]
        target_pace = None
        if params.target_time_s and race_distance:
            target_pace = int(params.target_time_s / race_distance)
        for w in workouts:
            if w.planned_date == params.race_date:
                w.workout_type = "race"
                w.title = f"🏁 Race day — Marathon {race_distance:.3g} km"
                w.description = (
                    f"{n_weeks} weeks of work come due. Target pace: {_fmt_pace(target_pace)}. "
                    "Trust the taper, run the first half with discipline."
                    if target_pace else
                    f"{n_weeks} weeks of work come due. Run the first half with discipline — "
                    "the race starts at 32 km."
                )
                w.target_distance_km = race_distance
                w.target_duration_s = params.target_time_s
                w.target_pace_s_per_km = target_pace
                w.workout_structure = None
                break

        return workouts
