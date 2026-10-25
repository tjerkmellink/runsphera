"""Execution score for completed plan workouts.

Composite 0–100 score telling the runner *how well they executed the
prescription*, surfaced as a corner ring on the plan-workout card. Three
sub-scores combined per workout type:

- **Pace** — actual pace vs target. For structured workouts (tempo /
  intervals) we use the active-block-only pace (from `laps.py`) so the
  warmup + cooldown don't drag the comparison; for easy / long /
  recovery we use total-run average.
- **Distance** — actual km vs target km, with a small over-shoot grace
  band and a sharper under-shoot penalty (cutting a run short matters
  more than running a bit long).
- **HR-zone discipline** — % of time spent in the *right* zones for the
  workout type. Easy/recovery rewards Z1–Z2; tempo rewards Z3–Z4;
  intervals rewards Z4–Z5; long is broad Z1–Z3. Without HR data this
  sub-score is skipped and the others are re-weighted.

The weighting per workout type lives in `_WEIGHTS`. Each sub-score is
0–100; the combined score is the weighted mean over the available
sub-scores. The score is None for rest/cross days and for workouts
without a matched activity.

See docs/roadmap.md item #5 for the design context.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from . import laps as laps_module


# ── Tunables ──────────────────────────────────────────────────────────

# Pace tolerance per workout type. `tight` is the within-tolerance band
# (no penalty), `loose` is where the score floors at zero. Linear falloff
# in between. Asymmetric for some types — going faster than easy is
# itself a problem (you didn't recover); going slower than tempo is.
# Bands are seconds-per-km off target. `under` = ran FASTER than target,
# `over` = ran SLOWER than target. For easy/recovery the asymmetry
# matters: too fast = "you didn't actually recover," too slow = no
# penalty (you recovered more). Tempo/intervals are roughly symmetric
# — being off in either direction means you missed the block.
_PACE_TOLERANCE_S_PER_KM: dict[str, dict[str, float]] = {
    # type:       under_tight, under_loose, over_tight, over_loose
    "tempo":      {"under": 5,  "under_loose": 25,  "over": 5,  "over_loose": 25},
    "intervals":  {"under": 5,  "under_loose": 25,  "over": 5,  "over_loose": 25},
    "race":       {"under": 8,  "under_loose": 40,  "over": 8,  "over_loose": 40},
    "easy":       {"under": 20, "under_loose": 75,  "over": 60, "over_loose": 150},
    "long":       {"under": 25, "under_loose": 75,  "over": 75, "over_loose": 180},
    "recovery":   {"under": 60, "under_loose": 150, "over": 30, "over_loose": 90},
}

# Sub-score weights per workout type. Structured workouts lean on pace
# (you nailed the block or you didn't); easier sessions weight HR more
# because "did you actually keep it easy?" is the question.
_WEIGHTS: dict[str, dict[str, float]] = {
    "tempo":     {"pace": 0.60, "distance": 0.20, "hr": 0.20},
    "intervals": {"pace": 0.55, "distance": 0.15, "hr": 0.30},
    "race":      {"pace": 0.50, "distance": 0.40, "hr": 0.10},
    # easy / long lean on distance because that IS the prescription —
    # "run X km at conversational pace." Skipping half the distance
    # matters more than slight pace drift.
    "easy":      {"pace": 0.20, "distance": 0.50, "hr": 0.30},
    "long":      {"pace": 0.20, "distance": 0.55, "hr": 0.25},
    "recovery":  {"pace": 0.30, "distance": 0.30, "hr": 0.40},
}

# Zone "good" mapping per workout type. Each entry is the set of HR zone
# numbers (1–5) that should dominate. The HR sub-score is the % of
# duration spent in those zones.
#
# `easy` includes Z3 as a "still aerobic" allowance — many amateur
# runners hit Z3 on conversational pace because Garmin's default zones
# are calibrated conservatively for max-HR-based aging tables. We still
# flag Z4-Z5 on an easy day (the "you didn't actually keep it easy"
# signal stays), just not the moderate-aerobic drift into Z3.
_HR_GOOD_ZONES: dict[str, tuple[int, ...]] = {
    "tempo":     (3, 4),
    "intervals": (4, 5),
    "race":      (3, 4, 5),
    "easy":      (1, 2, 3),
    "long":      (1, 2, 3),
    "recovery":  (1, 2),
}


# ── Sub-score functions ──────────────────────────────────────────────

def _pace_score(
    actual_s: float | None,
    target_s: float | None,
    workout_type: str,
) -> float | None:
    """0–100. None when either pace is missing (e.g. unmatched run or
    rest day). Penalty bands are workout-type-specific — going under
    target on an easy run is a different sin than overshooting a tempo.
    """
    if not actual_s or not target_s:
        return None
    tol = _PACE_TOLERANCE_S_PER_KM.get(workout_type)
    if not tol:
        return None
    diff = actual_s - target_s  # +ve = slower than target
    if diff >= 0:
        # Slower than target — use "over" band.
        if diff <= tol["over"]:
            return 100.0
        falloff = (diff - tol["over"]) / (tol["over_loose"] - tol["over"])
        return max(0.0, 100.0 * (1.0 - falloff))
    else:
        # Faster than target — use "under" band. Same math, abs(diff).
        d = -diff
        if d <= tol["under"]:
            return 100.0
        falloff = (d - tol["under"]) / (tol["under_loose"] - tol["under"])
        return max(0.0, 100.0 * (1.0 - falloff))


def _distance_score(
    actual_km: float | None,
    target_km: float | None,
) -> float | None:
    """0–100. Sharp penalty for under-shooting (cut the run short);
    gentle penalty for overshooting (a long run that runs long is
    still doing the work). Returns None when target is missing."""
    if not target_km or target_km <= 0:
        return None
    actual_km = actual_km or 0
    ratio = actual_km / target_km
    if 0.95 <= ratio <= 1.10:
        return 100.0
    if ratio < 0.95:
        # Linear falloff from 95% → 50% completion → 0 score at half-done.
        return max(0.0, 100.0 * (ratio - 0.50) / (0.95 - 0.50))
    # Overshoot: linear falloff from 1.10x (100) → 1.50x (0). Going way
    # past the prescribed distance burns reserves for the rest of the
    # week, so this isn't just a free pass.
    return max(0.0, 100.0 * (1.50 - ratio) / 0.40)


def _hr_score(
    activity: dict,
    workout_type: str,
) -> float | None:
    """0–100 — % of total duration spent in the "right" zones for this
    workout type. Returns None when no HR-zone data is recorded.
    """
    good = _HR_GOOD_ZONES.get(workout_type)
    if not good:
        return None
    total = sum((activity.get(f"hr_zone_{i}_s") or 0) for i in range(1, 6))
    if total <= 0:
        return None
    in_good = sum((activity.get(f"hr_zone_{i}_s") or 0) for i in good)
    return 100.0 * in_good / total


# ── Combiner ─────────────────────────────────────────────────────────

def compute(
    conn: sqlite3.Connection,
    planned: dict,
    activity: dict | None,
) -> dict[str, Any] | None:
    """Return the execution-score breakdown for one plan workout.

    Returns None when:
      - the workout type is rest / cross (no score applies)
      - no activity is matched yet
      - the planned target pace + distance are both missing (nothing to
        score against — e.g. a free-form note)

    Otherwise returns:
      {
        "score": int 0-100,         # the headline number for the ring
        "pace_score": float | None,
        "distance_score": float | None,
        "hr_score": float | None,
        "color": "green" | "amber" | "red",
      }
    """
    wtype = planned.get("workout_type")
    if wtype in (None, "rest", "cross"):
        return None
    if not activity:
        return None

    # Pace sub-score: use active-block pace for structured workouts so
    # the warmup/cooldown don't drag the comparison; fall back to total
    # avg for free runs.
    target_pace_s = planned.get("target_pace_s_per_km")
    actual_pace_s: float | None = None
    activity_id = activity.get("activity_id") or planned.get("actual_activity_id")
    if wtype in ("tempo", "intervals") and activity_id:
        ab = laps_module.active_block_summary(conn, int(activity_id))
        if ab and ab.get("avg_pace_s_per_km"):
            actual_pace_s = float(ab["avg_pace_s_per_km"])
    if actual_pace_s is None:
        # Fallback: total-run avg pace.
        d_m = activity.get("distance_m") or 0
        t_s = activity.get("duration_s") or 0
        if d_m > 0 and t_s > 0:
            actual_pace_s = (t_s / d_m) * 1000.0

    pace_s = _pace_score(actual_pace_s, target_pace_s, wtype)

    dist_s = _distance_score(
        (activity.get("distance_m") or 0) / 1000.0,
        planned.get("target_distance_km"),
    )

    hr_s = _hr_score(activity, wtype)

    weights = _WEIGHTS.get(wtype, {"pace": 0.5, "distance": 0.3, "hr": 0.2})
    parts: list[tuple[float, float]] = []
    if pace_s is not None: parts.append((pace_s, weights["pace"]))
    if dist_s is not None: parts.append((dist_s, weights["distance"]))
    if hr_s   is not None: parts.append((hr_s,   weights["hr"]))
    if not parts:
        return None

    weight_total = sum(w for _, w in parts)
    combined = sum(s * w for s, w in parts) / weight_total
    score = int(round(combined))

    return {
        "score": score,
        "pace_score":     round(pace_s, 1) if pace_s   is not None else None,
        "distance_score": round(dist_s, 1) if dist_s  is not None else None,
        "hr_score":       round(hr_s, 1)   if hr_s    is not None else None,
        "color": _color_for(score),
    }


def _color_for(score: int) -> str:
    """Map 0-100 → display color. Aligned with the Tempo accent palette:
    green is the calm-OK signal, amber is the heads-up, red is the
    "this wasn't the workout" signal."""
    if score >= 85:
        return "green"
    if score >= 60:
        return "amber"
    return "red"
