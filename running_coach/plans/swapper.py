"""Rule-based workout swaps when readiness flags caution-or-worse.

Returns a *new* plan_workouts row dict with softened shape. Pure function — no
DB writes here; the caller persists the change.

Mapping:
  tempo / intervals + CAUTION → Easy run at same distance, E pace
  tempo / intervals + EASY    → Easy run at 70% distance (min 3 km), E pace
  long + CAUTION              → Easier long: keep distance, force E pace, simple structure
  long + EASY                 → Easy run at 65% distance (min 5 km)
  easy + EASY                 → Rest day
  race                        → never swap
  anything else               → no change
"""
from __future__ import annotations

from typing import Any

from .daniels import _fmt_pace, _paces_for_vdot

_SWAP_TAG = " (swapped)"


def _easy_pace_for_plan(vdot_at_start: float | None) -> int:
    """Return the easy pace in s/km for a plan, falling back to a sane default."""
    if vdot_at_start is None:
        return 330  # ~5:30/km — used if VDOT wasn't captured
    return _paces_for_vdot(float(vdot_at_start))["E"]


def can_swap(workout_type: str, severity: str) -> bool:
    """Whether a swap is offered for this (type, severity) pair."""
    if severity == "go" or severity == "rest":
        return False
    if workout_type == "race":
        return False
    if workout_type in ("tempo", "intervals"):
        return True
    if workout_type == "long":
        return True
    if workout_type == "easy" and severity == "easy":
        return True
    return False


def soft_swap(pw: dict[str, Any], severity: str, vdot_at_start: float | None) -> dict[str, Any]:
    """Return a *new* plan_workouts dict with the workout softened.

    Severity is the coach status: 'caution' or 'easy'. Anything else returns the
    original unchanged.
    """
    wtype = pw["workout_type"]
    if not can_swap(wtype, severity):
        return pw

    easy_pace = _easy_pace_for_plan(vdot_at_start)
    original_km = pw.get("target_distance_km") or 0.0
    original_min = (pw.get("target_duration_s") or 0) / 60
    # Time-based workouts (e.g. the Foppen plan) carry duration but no distance.
    is_time_based = not original_km and original_min > 0
    new = dict(pw)
    # Multi-step structure no longer applies after softening.
    new["workout_structure"] = None

    if wtype in ("tempo", "intervals"):
        new["workout_type"] = "easy"
        if is_time_based:
            new_min = original_min if severity == "caution" else max(round(original_min * 0.7), 20)
            new["title"] = f"Easy {int(new_min)} min{_SWAP_TAG}"
            new["description"] = (
                f"Swapped from {pw['title']} — readiness flagged "
                f"{'caution' if severity == 'caution' else 'low'}. "
                f"Conversational pace; the watch just times the duration."
            )
            new["target_distance_km"] = None
            new["target_pace_s_per_km"] = None
            new["target_duration_s"] = int(new_min * 60)
            new["workout_structure"] = {"steps": [{"type": "active", "end": {"duration_s": int(new_min * 60)}}]}
        else:
            new_km = original_km if severity == "caution" else max(round(original_km * 0.7, 1), 3.0)
            new["title"] = f"Easy {new_km:.0f} km{_SWAP_TAG}"
            new["description"] = (
                f"Swapped from {pw['title']} — readiness flagged "
                f"{'caution' if severity == 'caution' else 'low'}. "
                f"Conversational pace, {_fmt_pace(easy_pace)}."
            )
            new["target_distance_km"] = new_km
            new["target_pace_s_per_km"] = easy_pace
            new["target_duration_s"] = int(new_km * easy_pace)
        return new

    if wtype == "long":
        if severity == "caution":
            new["title"] = f"Long {original_km:.0f} km (kept easy{_SWAP_TAG.strip()})"
            new["description"] = (
                f"Original long-run plan softened — all at E pace ({_fmt_pace(easy_pace)}), "
                "no marathon-pace surges."
            )
            new["target_pace_s_per_km"] = easy_pace
            new["target_duration_s"] = int(original_km * easy_pace)
        else:  # easy
            new_km = max(round(original_km * 0.65, 1), 5.0)
            new["workout_type"] = "easy"
            new["title"] = f"Easy {new_km:.0f} km{_SWAP_TAG}"
            new["description"] = (
                f"Cut down from a {original_km:.0f} km long run — readiness was low. "
                f"Conversational pace, {_fmt_pace(easy_pace)}."
            )
            new["target_distance_km"] = new_km
            new["target_pace_s_per_km"] = easy_pace
            new["target_duration_s"] = int(new_km * easy_pace)
        return new

    if wtype == "easy" and severity == "easy":
        new["workout_type"] = "rest"
        new["title"] = f"Rest{_SWAP_TAG}"
        new["description"] = "Swapped from easy run — recovery prioritized."
        new["target_distance_km"] = None
        new["target_pace_s_per_km"] = None
        new["target_duration_s"] = None
        return new

    return pw
