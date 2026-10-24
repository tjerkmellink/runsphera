"""Jack Daniels' VDOT methodology.

Pace zones interpolated from VDOT 30–70, weekly mileage progressed against the runner's
own baseline, workouts assigned by phase. Coverage is enough for sane plans toward
10k / half / marathon and an open-ended "stay fit" rotation.
"""
from __future__ import annotations

from datetime import date, timedelta

from .methodology import (
    GOAL_DISTANCES_KM,
    Methodology,
    PlanParams,
    PlannedWorkout,
)
from ._structure import totals_from_structure

# Daniels pace zones (seconds per km), keyed by VDOT.
# E = easy, M = marathon, T = threshold (tempo), I = interval (VO2max),
# R = repetition (anaerobic/speed).
#
# M / T / I / R values are transcribed from Daniels' Running Formula
# (4th edition, 2014), Table 5.2, cross-referenced with the
# runsmartproject.com VDOT calculator.
#
# E is set to **M + 60 sec/km** — the "1 minute slower than marathon pace"
# rule from the marathon training blueprint (docs/grounding/). This is the
# *everyday easy / long run* pace, not the faster cool-down jog pace at
# the bottom of Daniels' E range. Earlier versions used the faster E_lower
# value (Daniels' "59-78% of VO2max" lower bound), which for VDOT 50 came
# out to 5:16/km — too fast for sustainable easy training and well below
# the blueprint's "1-2 min slower than M" guideline. Bug surfaced
# 2026-05-29 by a runner whose conversational easy was 6:00-6:30/km but
# the engine prescribed 5:21.
#
# Lock-down test: tests/test_daniels_paces.py.
_VDOT_PACES: dict[int, dict[str, int]] = {
    30: {"E": 474, "M": 414, "T": 384, "I": 355, "R": 328},
    35: {"E": 432, "M": 372, "T": 345, "I": 320, "R": 297},
    40: {"E": 399, "M": 339, "T": 313, "I": 290, "R": 270},
    45: {"E": 373, "M": 313, "T": 290, "I": 268, "R": 251},
    50: {"E": 350, "M": 290, "T": 270, "I": 250, "R": 232},
    55: {"E": 330, "M": 270, "T": 251, "I": 233, "R": 216},
    60: {"E": 313, "M": 253, "T": 236, "I": 218, "R": 202},
    65: {"E": 299, "M": 239, "T": 222, "I": 205, "R": 190},
    70: {"E": 286, "M": 226, "T": 210, "I": 193, "R": 179},
}


def _paces_for_vdot(vdot: float) -> dict[str, int]:
    """Linear interpolation between table entries. Clamps to [30, 70]."""
    vdot = max(30.0, min(70.0, vdot))
    keys = sorted(_VDOT_PACES.keys())
    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= vdot <= hi:
            t = (vdot - lo) / (hi - lo)
            return {
                k: round(_VDOT_PACES[lo][k] * (1 - t) + _VDOT_PACES[hi][k] * t)
                for k in _VDOT_PACES[lo]
            }
    return dict(_VDOT_PACES[keys[-1]])


def _fmt_pace(secs_per_km: int) -> str:
    m, s = divmod(secs_per_km, 60)
    return f"{m}:{s:02d}/km"


# How many weeks each phase should occupy, by goal.
_DEFAULT_WEEKS: dict[str, int] = {
    "5k": 8,
    "10k": 10,
    "15k": 11,
    "half_marathon": 12,
    "marathon": 16,
    "stay_fit": 4,
}

_PHASE_SPEC: dict[str, list[tuple[str, int]]] = {
    "5k":            [("base", 2), ("build", 3), ("peak", 2), ("taper", 1)],
    "10k":           [("base", 3), ("build", 4), ("peak", 2), ("taper", 1)],
    "15k":           [("base", 3), ("build", 4), ("peak", 2), ("taper", 2)],
    "half_marathon": [("base", 4), ("build", 4), ("peak", 2), ("taper", 2)],
    "marathon":      [("base", 5), ("build", 5), ("peak", 3), ("taper", 3)],
    "stay_fit":      [("maintain", 4)],
}

# Peak weekly km as a multiplier of the runner's current 4-week baseline.
_PEAK_MULTIPLIER: dict[str, float] = {
    "5k": 1.25,
    "10k": 1.30,
    "15k": 1.40,
    "half_marathon": 1.50,
    "marathon": 1.80,
    "stay_fit": 1.00,
}

# Daniels caps every long run at 2.5 hours: past that point the injury and
# recovery cost outruns the aerobic benefit (Running Formula, ch. 4). Marathon
# peak weeks size the long run toward this ceiling instead of the flat
# percentage split — a % of a modest weekly volume otherwise leaves a
# 4-day/week marathoner peaking at a long run far shorter than the ceiling
# allows (observed: 20 km max on 61 km/wk, race ~3:47).
_LONG_RUN_CAP_S = 150 * 60
# Fraction of the peak-phase marathon long run finished at M pace.
_PEAK_LONG_M_FRACTION = 0.35


def _time_capped_long_km(paces: dict[str, int], m_fraction: float = 0.0) -> int:
    """Longest long run (whole km) that fits the 2.5-hour ceiling, given the
    fraction of it run at M pace (the rest at E pace)."""
    blended = paces["E"] * (1.0 - m_fraction) + paces["M"] * m_fraction
    return int(_LONG_RUN_CAP_S // blended)

# Legacy slot patterns — kept as the *fallback* when the runner didn't pick
# explicit workout days (i.e., `params.workout_days` is None for plans created
# before the column existed). Each entry: (slot_type, day_offset_from_long_run_day).
_SLOT_PATTERNS: dict[int, list[tuple[str, int]]] = {
    3: [("long", 0), ("rest", 1), ("rest", 2), ("rest", 3),
        ("quality", 4), ("rest", 5), ("easy", 6)],
    4: [("long", 0), ("rest", 1), ("easy", 2), ("rest", 3),
        ("quality", 4), ("easy", 5), ("rest", 6)],
    5: [("long", 0), ("easy", 1), ("rest", 2), ("easy", 3),
        ("quality", 4), ("easy", 5), ("rest", 6)],
    6: [("long", 0), ("easy", 1), ("quality2", 2), ("easy", 3),
        ("rest", 4), ("quality", 5), ("easy", 6)],
}


def _cyclic_gap(a: int, b: int) -> int:
    """Smallest day-of-week distance between two weekdays (0=Mon..6=Sun),
    treating the week as cyclic. Returns 0..3 (max distance on a 7-day cycle)."""
    d = abs(a - b) % 7
    return min(d, 7 - d)


def _slot_map(
    days_per_week: int,
    long_run_day: int,
    workout_days: list[int] | None = None,
) -> dict[int, str]:
    """{day_of_week_0_to_6: slot_type} for one week of training.

    When `workout_days` is supplied, the slot types (long / quality / easy)
    are assigned dynamically across the runner's picked days, respecting
    Daniels' recovery rules (no back-to-back hard sessions, quality ideally
    2-4 days before the long run). Otherwise falls back to the fixed
    `_SLOT_PATTERNS` anchored to the long-run day."""
    if workout_days is None:
        slots = _SLOT_PATTERNS[days_per_week]
        return {(long_run_day + offset) % 7: slot for slot, offset in slots}

    workout_days = sorted(set(workout_days))
    if long_run_day not in workout_days:
        raise ValueError(
            f"long_run_day ({long_run_day}) must be one of workout_days {workout_days}"
        )
    if len(workout_days) != days_per_week:
        raise ValueError(
            f"workout_days has {len(workout_days)} entries but days_per_week is {days_per_week}"
        )

    slots: dict[int, str] = {dow: "rest" for dow in range(7)}
    slots[long_run_day] = "long"
    others = [d for d in workout_days if d != long_run_day]

    if not others:
        return slots

    # Score each non-long workout day for the *main quality* slot. Daniels:
    # quality session sits 3-4 days before the long run; never back-to-back.
    def quality_score(d: int) -> float:
        if _cyclic_gap(d, long_run_day) == 1:
            return -1_000_000  # never adjacent to the long run
        forward_gap = (long_run_day - d) % 7  # days from d forward to long
        # Closeness to the ideal 3-day-before-long. Prefer days BEFORE long
        # (forward_gap small) over days after.
        return -abs(forward_gap - 3)

    others_by_score = sorted(others, key=quality_score, reverse=True)

    # 6-day weeks carry a second quality (intervals/VO₂); others run one.
    quality_count = 2 if days_per_week == 6 else 1
    qualities: list[int] = []
    for d in others_by_score:
        if len(qualities) >= quality_count:
            break
        # No new quality adjacent to an already-placed hard day (long or quality).
        if any(_cyclic_gap(d, hard) == 1 for hard in qualities + [long_run_day]):
            continue
        qualities.append(d)

    # Couldn't place all qualities under the no-adjacency rule — fall back to
    # "best score" ignoring adjacency. Rare edge case (tight day choices).
    if len(qualities) < quality_count:
        for d in others_by_score:
            if d in qualities:
                continue
            qualities.append(d)
            if len(qualities) >= quality_count:
                break

    for i, q in enumerate(qualities):
        slots[q] = "quality2" if i > 0 else "quality"
    for d in others:
        if d not in qualities:
            slots[d] = "easy"
    return slots


def _weekly_km_for_week(
    week_idx: int,
    total_weeks: int,
    phase: str,
    goal_type: str,
    baseline_km: float,
) -> float:
    """Volume target for a given week. Bumps through base/build, peaks, then tapers."""
    peak_km = baseline_km * _PEAK_MULTIPLIER.get(goal_type, 1.3)
    peak_km = max(peak_km, baseline_km + 5)  # ensure non-trivial progression

    if phase == "maintain":
        # Rolling 4-week microcycle: low-medium-medium-cutback
        cycle = [1.00, 1.10, 1.15, 0.85]
        return baseline_km * cycle[week_idx % 4]

    # Phase position helpers
    phase_weeks = [(p, n) for p, n in _phase_layout(goal_type, total_weeks)]
    phase_starts: dict[str, int] = {}
    cursor = 0
    for p, n in phase_weeks:
        phase_starts[p] = cursor
        cursor += n
    phase_len = next(n for p, n in phase_weeks if p == phase)
    week_in_phase = week_idx - phase_starts[phase]

    if phase == "base":
        # Ramp baseline → ~75% of peak
        start = baseline_km
        end = baseline_km + (peak_km - baseline_km) * 0.6
    elif phase == "build":
        start = baseline_km + (peak_km - baseline_km) * 0.6
        end = peak_km
    elif phase == "peak":
        start = end = peak_km
    elif phase == "taper":
        # Linear drop to ~35% of peak in the final week
        start = peak_km * 0.85
        end = peak_km * 0.35
    else:
        return baseline_km

    if phase == "taper" and phase_len == 1:
        # A single taper week has no ramp to interpolate along: t=0 would
        # leave it at 0.85 × peak — barely a taper. Sit at the midpoint
        # (0.60 × peak) instead. Multi-week tapers keep the 0.85 → 0.35 ramp.
        t = 0.5
    else:
        t = week_in_phase / max(phase_len - 1, 1)
    target = start + (end - start) * t

    # Cutback every 4th week of base/build to manage fatigue.
    if phase in ("base", "build") and (week_in_phase + 1) % 4 == 0:
        target *= 0.82

    return round(target, 1)


def _phase_layout(goal_type: str, total_weeks: int) -> list[tuple[str, int]]:
    """Allocate phases across the plan length.

    Longer-than-default plans grow base + build only (the real
    fitness-building phases); peak and taper stay at their spec values.
    Marathon training literature is firm on this: peak >4 weeks digs you
    into a hole, taper >3 weeks costs fitness without buying freshness.

    Shorter-than-default plans compress base + build first; peak and taper
    drop only when there's nowhere else to give.

    Refs: docs/grounding/the-complete-marathon-training-blueprint
    ("Two to three weeks of less volume" for taper; "3-4 weeks before race
    day, you hit your heaviest mileage" for peak).
    """
    spec = _PHASE_SPEC[goal_type]
    default_total = sum(n for _, n in spec)

    # Trivial: stay_fit has no phasing (or unknown goal).
    if default_total == 0 or total_weeks == default_total:
        return list(spec)

    out: dict[str, int] = {p: n for p, n in spec}

    if total_weeks > default_total:
        # Longer plan — route extras to base + build alternately (build
        # first to favour threshold + race-pace fitness density).
        extra = total_weeks - default_total
        growth = [p for p in ("build", "base") if p in out]
        if not growth:
            out[spec[0][0]] += extra
        else:
            for i in range(extra):
                out[growth[i % len(growth)]] += 1
    else:
        # Shorter plan — compress base first, then build, then peak; never
        # touch taper until everything else is at 1 week.
        deficit = default_total - total_weeks
        for phase in ("base", "build", "peak"):
            while deficit > 0 and out.get(phase, 0) > 1:
                out[phase] -= 1
                deficit -= 1
            if deficit == 0:
                break
        # If still over budget, allow phases (including taper) to drop to
        # absolute minimums. Goes from base again to avoid trimming taper.
        if deficit > 0:
            for phase in ("base", "build", "peak", "taper"):
                while deficit > 0 and out.get(phase, 0) > 0:
                    out[phase] -= 1
                    deficit -= 1
                if deficit == 0:
                    break

    return [(p, out[p]) for p, _ in spec]


def _tempo_split(total_km: float) -> tuple[float, float, float]:
    """Split a tempo session into (warmup, main, cooldown) km that sum to total.

    Warmup and cooldown are 2 km when the total leaves enough room for a
    meaningful main block, otherwise they shrink to 25% each so the parts
    always add up to the prescribed total distance.
    """
    wu = round(min(2.0, total_km * 0.25), 1)
    cd = wu
    main = round(max(total_km - wu - cd, 1.0), 1)
    return wu, main, cd


def _tempo_structure(total_km: float, main_pace_s: int) -> dict:
    """Warmup + main @ target pace + cooldown. All parts sum to total_km."""
    wu_km, main_km, cd_km = _tempo_split(total_km)
    return {
        "steps": [
            {"type": "warmup", "end": {"distance_m": int(wu_km * 1000)}},
            {"type": "active", "end": {"distance_m": int(main_km * 1000)}, "pace_s_per_km": main_pace_s},
            {"type": "cooldown", "end": {"distance_m": int(cd_km * 1000)}},
        ]
    }


def _fmt_km(km: float) -> str:
    """Render km nicely: '4' for whole numbers, '1.5' otherwise."""
    return f"{km:g}"


def _step_duration_s(step: dict) -> int | None:
    """Seconds for a single structure step, or None when it can't be timed.

    Time-capped steps answer for themselves; distance steps need a pace to
    convert. Repeat blocks recurse — the whole block is timeable only if
    every step inside it is."""
    if step.get("type") == "repeat":
        inner = 0
        for sub in step.get("steps") or []:
            sub_s = _step_duration_s(sub)
            if sub_s is None:
                return None
            inner += sub_s
        return inner * int(step.get("iterations") or 1)
    end = step.get("end") or {}
    if end.get("duration_s"):
        return int(end["duration_s"])
    dist_m = end.get("distance_m")
    pace = step.get("pace_s_per_km")
    if not dist_m or not pace:
        return None
    return int(dist_m / 1000 * pace)


def _structure_duration_s(structure: dict | None) -> int | None:
    """Exact duration for a structure that fully times itself — the mixed-pace
    long run and taper strides. Returns None when any step can't be timed:
    classic tempo/interval structures leave warm-up and cool-down unpaced, so
    they keep the historical distance × headline-pace estimate."""
    if not structure or not structure.get("steps"):
        return None
    total = 0
    for step in structure["steps"]:
        step_s = _step_duration_s(step)
        if step_s is None:
            return None
        total += step_s
    return total


def _interval_structure(reps: int, rep_distance_m: int, recovery_s: int, pace_s: int) -> dict:
    """Standard interval: 2km warmup + N × [rep @ I pace + recovery] + 2km cooldown."""
    return {
        "steps": [
            {"type": "warmup", "end": {"distance_m": 2000}},
            {"type": "repeat", "iterations": reps, "steps": [
                {"type": "active", "end": {"distance_m": rep_distance_m}, "pace_s_per_km": pace_s},
                {"type": "recovery", "end": {"duration_s": recovery_s}},
            ]},
            {"type": "cooldown", "end": {"distance_m": 2000}},
        ]
    }


# Taper strides: an easy run carrying a few short, fast bursts.
_STRIDE_M = 100
_STRIDE_RECOVERY_S = 60
_STRIDE_COOLDOWN_M = 1000
_STRIDE_MIN_WARMUP_M = 1000


def _strides_structure(total_km: float, paces: dict[str, int]) -> tuple[int, dict] | None:
    """Easy run with strides woven in: easy block, N × [100 m @ R + jog], easy finish.

    Daniels' taper strides are an easy run that happens to carry short R-pace
    bursts, not an interval session — but the row is typed `intervals` (the
    recalibrator reads "Strides" in the title as R), and `intervals` is a
    structured type, so without a structure the session is silently
    unpushable to the watch. The watch models this shape fine.

    Rep count flexes 6 → 4 so a short taper run still fits a block. Returns
    None when even four reps leave no room for a real easy warm-up, and the
    caller falls back to a plain easy run.

    Returns (reps, structure) so the caller can name the session honestly.
    """
    total_m = int(round(total_km * 1000))
    recovery_m = int(_STRIDE_RECOVERY_S / paces["E"] * 1000)
    for reps in (6, 5, 4):
        warmup_m = total_m - reps * (_STRIDE_M + recovery_m) - _STRIDE_COOLDOWN_M
        if warmup_m < _STRIDE_MIN_WARMUP_M:
            continue
        return reps, {
            "steps": [
                {"type": "warmup", "zone": "E",
                 "end": {"distance_m": int(round(warmup_m / 100) * 100)},
                 "pace_s_per_km": paces["E"]},
                {"type": "repeat", "iterations": reps, "steps": [
                    {"type": "active", "zone": "R",
                     "end": {"distance_m": _STRIDE_M}, "pace_s_per_km": paces["R"]},
                    {"type": "recovery", "zone": "E",
                     "end": {"duration_s": _STRIDE_RECOVERY_S}},
                ]},
                {"type": "cooldown", "zone": "E",
                 "end": {"distance_m": _STRIDE_COOLDOWN_M},
                 "pace_s_per_km": paces["E"]},
            ],
        }
    return None


def _quality_workout(
    phase: str,
    week_in_phase: int,
    goal_type: str,
    target_km: float,
    paces: dict[str, int],
) -> tuple[str, str, str, int, dict | None]:
    """Pick a quality session.

    Returns (workout_type, title, description, target_pace_s, workout_structure).
    """
    alt = week_in_phase % 2  # alternates tempo vs intervals

    if phase == "base":
        if goal_type == "5k" and alt == 1:
            # 5K races live on speed: repetition work enters in base already.
            # Title word "Repetitions" is load-bearing — the recalibration
            # zone mapper reads it as R (plain "Intervals" re-zones to I).
            return (
                "intervals",
                "Repetitions 8×200 m",
                f"WU 2 km, 8×200 m @ R pace ({_fmt_pace(paces['R'])}) w/ 90 s jog, CD 2 km.",
                paces["R"],
                _interval_structure(8, 200, 90, paces["R"]),
            )
        wu, main, cd = _tempo_split(target_km)
        return (
            "tempo",
            f"Tempo {target_km:.0f} km",
            f"Easy {_fmt_km(wu)} km, {_fmt_km(main)} km @ T pace ({_fmt_pace(paces['T'])}), easy {_fmt_km(cd)} km.",
            paces["T"],
            _tempo_structure(target_km, paces["T"]),
        )

    if phase == "build":
        if goal_type == "5k":
            # Alternate VO₂max intervals with repetition speed (I, R, I, ...):
            # tempo takes a back seat for 5K, per Daniels' 5K-15K progression.
            if alt == 0:
                return (
                    "intervals",
                    "Intervals 5×1000 m",
                    f"WU 2 km easy, 5×1000 m @ I pace ({_fmt_pace(paces['I'])}) w/ 2:00 jog, CD 2 km.",
                    paces["I"],
                    _interval_structure(5, 1000, 120, paces["I"]),
                )
            return (
                "intervals",
                "Repetitions 6×400 m",
                f"WU 2 km, 6×400 m @ R pace ({_fmt_pace(paces['R'])}) w/ 90 s jog, CD 2 km.",
                paces["R"],
                _interval_structure(6, 400, 90, paces["R"]),
            )
        if alt == 0:
            wu, main, cd = _tempo_split(target_km)
            return (
                "tempo",
                f"Tempo {target_km:.0f} km",
                f"Easy {_fmt_km(wu)} km, {_fmt_km(main)} km @ T pace ({_fmt_pace(paces['T'])}), easy {_fmt_km(cd)} km.",
                paces["T"],
                _tempo_structure(target_km, paces["T"]),
            )
        reps = 5 if target_km < 9 else 6
        return (
            "intervals",
            f"Intervals {reps}×1000 m",
            f"WU 2 km easy, {reps}×1000 m @ I pace ({_fmt_pace(paces['I'])}) w/ 2:00 jog, CD 2 km.",
            paces["I"],
            _interval_structure(reps, 1000, 120, paces["I"]),
        )

    if phase == "peak":
        if goal_type == "marathon":
            wu, main, cd = _tempo_split(target_km)
            return (
                "tempo",
                f"Marathon-pace {target_km:.0f} km",
                f"Easy {_fmt_km(wu)} km, {_fmt_km(main)} km @ M pace ({_fmt_pace(paces['M'])}), easy {_fmt_km(cd)} km.",
                paces["M"],
                _tempo_structure(target_km, paces["M"]),
            )
        if goal_type == "half_marathon":
            reps = max(round(target_km / 2), 3)
            return (
                "tempo",
                f"Cruise intervals {reps}×1.5 km",
                f"WU 2 km, {reps}×1.5 km @ T pace ({_fmt_pace(paces['T'])}) w/ 1:00 jog, CD 2 km.",
                paces["T"],
                _interval_structure(reps, 1500, 60, paces["T"]),
            )
        if goal_type == "5k":
            if alt == 0:
                return (
                    "intervals",
                    "Intervals 5×800 m",
                    f"WU 2 km, 5×800 m @ I pace ({_fmt_pace(paces['I'])}) w/ 2:00 jog, CD 2 km.",
                    paces["I"],
                    _interval_structure(5, 800, 120, paces["I"]),
                )
            # Final sharpening closest to race day: short, fast, low fatigue.
            return (
                "intervals",
                "Repetitions 6×400 m",
                f"WU 2 km, 6×400 m @ R pace ({_fmt_pace(paces['R'])}) w/ 90 s jog, CD 2 km.",
                paces["R"],
                _interval_structure(6, 400, 90, paces["R"]),
            )
        if goal_type == "10k" and alt == 1:
            return (
                "intervals",
                "Intervals 5×1000 m",
                f"WU 2 km, 5×1000 m @ I pace ({_fmt_pace(paces['I'])}) w/ 2:00 jog, CD 2 km.",
                paces["I"],
                _interval_structure(5, 1000, 120, paces["I"]),
            )
        # 10k / 15k fallback
        return (
            "intervals",
            "Intervals 6×800 m",
            f"WU 2 km, 6×800 m @ I pace ({_fmt_pace(paces['I'])}) w/ 90 s jog, CD 2 km.",
            paces["I"],
            _interval_structure(6, 800, 90, paces["I"]),
        )

    if phase == "taper":
        # Strides read as an easy run, but the row is typed `intervals` so the
        # recalibrator zones it at R. That makes a structure mandatory: without
        # one the session is unpushable and never reaches the watch.
        strides = _strides_structure(target_km, paces)
        if strides is not None:
            reps, structure = strides
            return (
                "intervals",
                f"Strides {reps}×{_STRIDE_M} m",
                (
                    f"Easy {_fmt_km(target_km)} km at E pace ({_fmt_pace(paces['E'])}) "
                    f"with {reps}×{_STRIDE_M} m strides at R pace ({_fmt_pace(paces['R'])}), "
                    f"{_STRIDE_RECOVERY_S} s easy jog between. Stay sharp, not sore."
                ),
                paces["R"],
                structure,
            )
        # Too short to hold a strides block — keep it an honest easy run.
        return (
            "easy",
            f"Easy {_fmt_km(target_km)} km",
            (
                f"Easy shakeout at E pace ({_fmt_pace(paces['E'])}). "
                f"Add 4×20 s strides if the legs feel flat."
            ),
            paces["E"],
            None,
        )

    if phase == "maintain":
        if alt == 0:
            wu, main, cd = _tempo_split(target_km)
            return (
                "tempo",
                f"Tempo {target_km:.0f} km",
                f"Easy {_fmt_km(wu)} km, {_fmt_km(main)} km @ T pace ({_fmt_pace(paces['T'])}), easy {_fmt_km(cd)} km.",
                paces["T"],
                _tempo_structure(target_km, paces["T"]),
            )
        return (
            "intervals",
            "Intervals 5×1000 m",
            f"WU 2 km, 5×1000 m @ I pace ({_fmt_pace(paces['I'])}) w/ 2:00 jog, CD 2 km.",
            paces["I"],
            _interval_structure(5, 1000, 120, paces["I"]),
        )

    return ("easy", f"Easy {target_km:.0f} km", f"Easy aerobic, {_fmt_pace(paces['E'])}.", paces["E"], None)


def _long_run_workout(
    phase: str,
    goal_type: str,
    target_km: float,
    paces: dict[str, int],
) -> tuple[str, str, str, int, dict | None]:
    if phase == "peak" and goal_type == "marathon":
        m_pace_km = max(round(target_km * _PEAK_LONG_M_FRACTION), 5)
        # Two-step structure so the M-pace finish reaches the watch instead of
        # living only in the description text. Steps carry a `zone` tag so the
        # pace recalibrator can rewrite each segment against its own zone.
        structure = {
            "steps": [
                {"type": "active", "zone": "E",
                 "end": {"distance_m": int((target_km - m_pace_km) * 1000)},
                 "pace_s_per_km": paces["E"]},
                {"type": "active", "zone": "M",
                 "end": {"distance_m": int(m_pace_km * 1000)},
                 "pace_s_per_km": paces["M"]},
            ]
        }
        return (
            "long",
            f"Long {target_km:.0f} km incl. {m_pace_km} km @ M pace",
            f"First {target_km - m_pace_km:.0f} km easy ({_fmt_pace(paces['E'])}), last {m_pace_km} km @ M pace ({_fmt_pace(paces['M'])}).",
            paces["E"],
            structure,
        )
    if phase == "peak" and goal_type == "half_marathon":
        # Same treatment as the marathon peak long run above: without a
        # structure the description promises a T-pace finish that never
        # reaches the watch, which sends one flat E-pace step for the whole
        # distance. Zone tags let the recalibrator rewrite each segment
        # against its own pace zone.
        easy_km = max(target_km - 6, 1)
        structure = {
            "steps": [
                {"type": "active", "zone": "E",
                 "end": {"distance_m": int(easy_km * 1000)},
                 "pace_s_per_km": paces["E"]},
                {"type": "active", "zone": "T",
                 "end": {"distance_m": 5000},
                 "pace_s_per_km": paces["T"]},
                {"type": "cooldown", "zone": "E",
                 "end": {"distance_m": 1000},
                 "pace_s_per_km": paces["E"]},
            ]
        }
        return (
            "long",
            f"Long {target_km:.0f} km incl. 5 km @ HM pace",
            f"Easy {easy_km:.0f} km then 5 km @ ~T pace ({_fmt_pace(paces['T'])}). Cooldown 1 km.",
            paces["E"],
            structure,
        )
    if phase == "taper":
        return (
            "long",
            f"Long {target_km:.0f} km",
            f"Cut-back long run, fully easy ({_fmt_pace(paces['E'])}).",
            paces["E"],
            None,
        )
    return (
        "long",
        f"Long {target_km:.0f} km",
        f"Conversational pace, ~{_fmt_pace(paces['E'])}. Steady aerobic.",
        paces["E"],
        None,
    )


def _headline_from_structure(structure: dict | None, distance_km: float,
                             pace_s: int | None) -> tuple[float, int | None, int | None]:
    """Reconcile a session's headline numbers with what it actually prescribes.

    `_tempo_structure` is built to a km budget, so its totals already match the
    headline. `_interval_structure` is not: its rep counts are Daniels'
    published prescription (5x1000m at I pace, 6x400m at R pace, ...), and the
    warmup, cooldown and recoveries are fixed. A 5 km "budget" can therefore
    prescribe 9 km of running.

    The structure is the contract with the watch, so it wins. Reporting the
    budget instead understates weekly volume on every interval week — the
    runner was always running the longer session, the plan just wasn't counting
    it. Trimming reps to fit the budget would be the wrong fix: it changes a
    published training prescription to protect a display number.
    """
    if not structure or not structure.get("steps"):
        return distance_km, pace_s, None
    totals = totals_from_structure(structure, fallback_pace=pace_s)
    return (
        totals["total_km"] or distance_km,
        totals["headline_pace_s"] or pace_s,
        totals["total_duration_s"] or None,
    )


def _allocate_week(
    weekly_km: float,
    template: dict[int, str],
    phase: str,
    goal_type: str,
    paces: dict[str, int],
    week_in_phase: int,
    phase_len: int = 1,
) -> dict[int, dict]:
    """Return {day_of_week: workout_dict_or_None} for this week."""
    has_quality2 = "quality2" in template.values()

    # Volume split:
    # long: 28-32%, quality1: 18%, quality2: 13%, rest goes to easy days.
    # Everything rounds to whole km so the rounded titles (Tempo 6 km,
    # Easy 9 km, Long 11 km) sum to the displayed weekly total. Without
    # this, the title-rounded numbers won't match the precise total_km
    # used elsewhere.
    long_km = float(round(weekly_km * (0.28 if has_quality2 else 0.32)))

    # 5K training doesn't need marathon-style long runs: cap at a quarter of
    # the week (12 km hard ceiling) and let the freed volume land on easy days.
    if goal_type == "5k":
        long_km = float(min(round(weekly_km * 0.25), 12))

    # Marathon long runs size toward Daniels' 2.5-hour ceiling, not the flat
    # percentage: on modest weekly volume the % split leaves the longest run
    # far below what the ceiling allows (and what race day asks for).
    if goal_type == "marathon":
        if phase == "peak":
            cap = _time_capped_long_km(paces, _PEAK_LONG_M_FRACTION)
            long_km = float(min(round(weekly_km * 0.40), cap))
            if phase_len > 1 and week_in_phase == phase_len - 1:
                # Final peak week steps down ~10% so the longest run lands
                # 4+ weeks out, easing into the taper.
                long_km = float(round(long_km * 0.9))
        elif phase == "build" and week_in_phase == phase_len - 1:
            # Bridge week into peak: stretch toward the fully-easy ceiling so
            # the first peak-week long run isn't a >2 km jump.
            long_km = float(min(round(weekly_km * 0.36), _time_capped_long_km(paces)))
    q1_km = float(min(round(weekly_km * 0.18), 12))
    q2_km = float(min(round(weekly_km * 0.13), 10)) if has_quality2 else 0.0
    easy_slots = sum(1 for v in template.values() if v == "easy")
    consumed = long_km + q1_km + q2_km
    easy_pool = max(weekly_km - consumed, easy_slots * 4)  # floor each easy at ~4km
    easy_km = float(max(round(easy_pool / easy_slots), 4)) if easy_slots else 0.0

    result: dict[int, dict] = {}
    for dow in range(7):
        slot = template.get(dow, "rest")
        if slot == "long":
            wtype, title, desc, pace, structure = _long_run_workout(phase, goal_type, long_km, paces)
            km, pace, dur = _headline_from_structure(structure, long_km, pace)
            result[dow] = {
                "workout_type": wtype, "title": title, "description": desc,
                "distance_km": km, "pace_s": pace, "structure": structure,
                "duration_s": dur,
            }
        elif slot == "quality":
            wtype, title, desc, pace, structure = _quality_workout(phase, week_in_phase, goal_type, q1_km, paces)
            km, pace, dur = _headline_from_structure(structure, q1_km, pace)
            result[dow] = {
                "workout_type": wtype, "title": title, "description": desc,
                "distance_km": km, "pace_s": pace, "structure": structure,
                "duration_s": dur,
            }
        elif slot == "quality2":
            wtype, title, desc, pace, structure = _quality_workout(phase, week_in_phase + 1, goal_type, q2_km, paces)
            km, pace, dur = _headline_from_structure(structure, q2_km, pace)
            result[dow] = {
                "workout_type": wtype, "title": title, "description": desc,
                "distance_km": km, "pace_s": pace, "structure": structure,
                "duration_s": dur,
            }
        elif slot == "easy":
            result[dow] = {
                "workout_type": "easy",
                "title": f"Easy {easy_km:.0f} km",
                "description": f"Conversational aerobic, {_fmt_pace(paces['E'])}.",
                "distance_km": easy_km, "pace_s": paces["E"], "structure": None,
            }
        else:
            result[dow] = {
                "workout_type": "rest",
                "title": "Rest",
                "description": "Full rest or light cross-training (walk, swim, easy bike).",
                "distance_km": None, "pace_s": None, "structure": None,
            }
    return result


class DanielsVDOT(Methodology):
    name = "daniels"

    def total_weeks(self, goal_type: str, race_date: date | None, start_date: date) -> int:
        if race_date is not None:
            if race_date < start_date:
                return 1
            # Round UP so the week containing the race day is included in the plan.
            # `// 7` alone truncates the partial last week — race day would fall outside.
            weeks = (race_date - start_date).days // 7 + 1
            return max(1, min(weeks, 30))  # cap at 30 to keep plans sane
        return _DEFAULT_WEEKS[goal_type]

    def generate(self, params: PlanParams) -> list[PlannedWorkout]:
        paces = _paces_for_vdot(params.current_vdot)
        total_weeks = self.total_weeks(params.goal_type, params.race_date, params.start_date)
        phase_alloc = _phase_layout(params.goal_type, total_weeks)

        # Build a flat per-week phase list and per-phase index
        weeks_phases: list[tuple[str, int]] = []  # (phase, week_in_phase)
        phase_len_by = {p: n for p, n in phase_alloc}
        for phase, count in phase_alloc:
            for w in range(count):
                weeks_phases.append((phase, w))

        # The plan starts on the Monday on or after start_date.
        plan_start_monday = params.start_date + timedelta(days=(7 - params.start_date.weekday()) % 7)

        workouts: list[PlannedWorkout] = []
        for week_idx, (phase, week_in_phase) in enumerate(weeks_phases):
            week_start = plan_start_monday + timedelta(weeks=week_idx)
            weekly_km = _weekly_km_for_week(week_idx, total_weeks, phase, params.goal_type, params.weekly_km_baseline)
            template = _slot_map(
                params.days_per_week, params.long_run_day, params.workout_days
            )
            day_workouts = _allocate_week(
                weekly_km, template, phase, params.goal_type, paces,
                week_in_phase, phase_len_by[phase],
            )

            for dow in range(7):
                planned_date = week_start + timedelta(days=dow)
                w = day_workouts[dow]
                # Exact when every step times itself (mixed-pace long run,
                # taper strides). Otherwise fall back to the structure totals,
                # which count recoveries and price unpaced warm-up/cool-down at
                # an easy default — never distance x headline pace, which would
                # bill an interval session's whole 9 km at I pace.
                duration_s = _structure_duration_s(w["structure"])
                if duration_s is None:
                    duration_s = w.get("duration_s")
                if duration_s is None and w["distance_km"] and w["pace_s"]:
                    duration_s = int(w["distance_km"] * w["pace_s"])
                workouts.append(PlannedWorkout(
                    week_number=week_idx + 1,
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

        # Race day overlay: replace whatever's on race_date with the race itself.
        if params.race_date is not None and params.goal_type != "stay_fit":
            race_distance = GOAL_DISTANCES_KM[params.goal_type]
            target_pace = None
            target_duration = params.target_time_s
            if params.target_time_s and race_distance:
                target_pace = int(params.target_time_s / race_distance)
            for w in workouts:
                if w.planned_date == params.race_date:
                    w.workout_type = "race"
                    w.title = f"🏁 Race day — {race_distance} km"
                    w.description = (
                        f"Execute the plan. Target pace: {_fmt_pace(target_pace)}." if target_pace
                        else "Race day — execute the work you've done."
                    )
                    w.target_distance_km = race_distance
                    w.target_duration_s = target_duration
                    w.target_pace_s_per_km = target_pace
                    # The race can land on a day that was already a quality
                    # session. Its structure must go with it: `race` is a
                    # simple type, but planned_to_garmin_workout prefers any
                    # structure it finds over the headline distance, so a
                    # leftover one would send the runner 6x100m strides on
                    # race morning under a "Race day" title.
                    w.workout_structure = None
                    break

        return workouts
