"""Push planned workouts to Garmin Connect.

Stage 1 supported simple distance-based workouts (Easy, Long, Recovery, Race).
Stage 2 adds structured workouts (Tempo, Intervals) built from a JSON step list
stored on the plan_workouts row.

Garmin shape reference (confirmed against existing user workouts):
  - targetType = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", ...}
  - targetValueLow / targetValueHigh in m/s (Garmin converts to pace for display)
  - endCondition.distance = type 1, endCondition.time = type 2
  - stepType: warmup=1, cooldown=2, interval=3, recovery=4, rest=5, repeat=6
  - RepeatGroup wraps nested ExecutableSteps for interval blocks
"""
from __future__ import annotations

import json
from typing import Any

from garminconnect.workout import (
    ExecutableStep,
    RepeatGroup,
    RunningWorkout,
    WorkoutSegment,
)

# Single-step workout types (Stage 1).
_SIMPLE_TYPES = frozenset({"easy", "long", "recovery", "race"})
# Structured types (Stage 2) — need workout_structure JSON.
_STRUCTURED_TYPES = frozenset({"tempo", "intervals"})
# Never pushable.
_NOT_PUSHABLE = frozenset({"rest", "cross"})


def is_pushable(workout_type: str, workout_structure: Any = None) -> bool:
    if workout_type in _NOT_PUSHABLE:
        return False
    if workout_type in _STRUCTURED_TYPES:
        return bool(workout_structure)
    return workout_type in _SIMPLE_TYPES


def is_pushable_row(row: dict[str, Any]) -> bool:
    """Convenience: takes a plan_workouts row dict."""
    return is_pushable(row.get("workout_type", ""), row.get("workout_structure"))


def push_status(workout_type: str, workout_structure: Any = None) -> str:
    """Why this isn't pushable (empty string if it is)."""
    if workout_type in _NOT_PUSHABLE:
        return "Rest day — nothing to push."
    if workout_type in _STRUCTURED_TYPES and not workout_structure:
        return "Structured steps missing — regenerate the plan to enable push."
    if workout_type in _SIMPLE_TYPES or workout_type in _STRUCTURED_TYPES:
        return ""
    return f"Workout type '{workout_type}' is not pushable."


# --- Garmin shape primitives -------------------------------------------------

_STEP_TYPE_MAP: dict[str, tuple[int, str, int]] = {
    # internal key -> (stepTypeId, stepTypeKey, displayOrder)
    "warmup":   (1, "warmup", 1),
    "active":   (3, "interval", 3),
    "interval": (3, "interval", 3),
    "recovery": (4, "recovery", 4),
    "cooldown": (2, "cooldown", 2),
    "rest":     (5, "rest", 5),
}


def _pace_target(pace_s_per_km: int, tolerance_s: int = 10) -> tuple[dict[str, Any], float, float]:
    slow = pace_s_per_km + tolerance_s
    fast = pace_s_per_km - tolerance_s
    return (
        {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6},
        round(1000.0 / slow, 3),
        round(1000.0 / fast, 3),
    )


def _no_target() -> dict[str, Any]:
    return {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}


# NOTE: ConditionType constants in the garminconnect library are stale —
# empirically verified IDs against Garmin: lap.button=1, time=2, distance=3.
def _distance_end(value_m: float) -> tuple[dict[str, Any], float]:
    return (
        {"conditionTypeId": 3, "conditionTypeKey": "distance", "displayOrder": 2, "displayable": True},
        float(value_m),
    )


def _time_end(value_s: float) -> tuple[dict[str, Any], float]:
    return (
        {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 1, "displayable": True},
        float(value_s),
    )


# --- Builders ---------------------------------------------------------------

def _build_executable_step(step_def: dict, step_order: int) -> ExecutableStep:
    """Build a single ExecutableStep from a step dict in the workout_structure JSON."""
    step_type_key = step_def["type"]
    st_id, st_key, st_disp = _STEP_TYPE_MAP[step_type_key]

    end = step_def.get("end") or {}
    if "distance_m" in end:
        end_cond, end_val = _distance_end(end["distance_m"])
    elif "duration_s" in end:
        end_cond, end_val = _time_end(end["duration_s"])
    else:
        raise ValueError(f"step has no end condition: {step_def}")

    pace_s = step_def.get("pace_s_per_km")
    if pace_s:
        target_type, low, high = _pace_target(int(pace_s))
    else:
        target_type, low, high = _no_target(), None, None

    step = ExecutableStep(
        stepOrder=step_order,
        stepType={"stepTypeId": st_id, "stepTypeKey": st_key, "displayOrder": st_disp},
        endCondition=end_cond,
        endConditionValue=end_val,
        targetType=target_type,
    )
    # Empirically: Garmin uses targetValueOne / targetValueTwo, not Low / High.
    if low is not None:
        step.targetValueOne = low
        step.targetValueTwo = high
    return step


_EASY_PACE_FALLBACK_S_PER_KM = 330  # ~5:30/km — used to estimate untargeted distance steps


def _estimate_step_duration(step_def: dict) -> int:
    """Rough seconds estimate for one step, recursing into repeats."""
    if step_def["type"] == "repeat":
        inner = sum(_estimate_step_duration(s) for s in step_def["steps"])
        return inner * int(step_def["iterations"])
    end = step_def.get("end") or {}
    if "duration_s" in end:
        return int(end["duration_s"])
    if "distance_m" in end:
        pace = step_def.get("pace_s_per_km") or _EASY_PACE_FALLBACK_S_PER_KM
        return int(end["distance_m"] / 1000.0 * pace)
    return 0


def _estimate_workout_duration_s(structure: dict | None, fallback_distance_km: float | None,
                                 fallback_pace: int | None) -> int:
    if structure and structure.get("steps"):
        return sum(_estimate_step_duration(s) for s in structure["steps"])
    if fallback_distance_km and fallback_pace:
        return int(fallback_distance_km * fallback_pace)
    if fallback_distance_km:
        return int(fallback_distance_km * _EASY_PACE_FALLBACK_S_PER_KM)
    return 0


def _build_steps(step_defs: list[dict], start_order: int) -> tuple[list, int]:
    """Recursively build ExecutableSteps and RepeatGroups. Returns (steps, next_order)."""
    out: list = []
    order = start_order
    for sd in step_defs:
        if sd["type"] == "repeat":
            inner_steps, inner_next = _build_steps(sd["steps"], order + 1)
            group = RepeatGroup(
                stepOrder=order,
                stepType={"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                numberOfIterations=int(sd["iterations"]),
                workoutSteps=inner_steps,
                endCondition={
                    "conditionTypeId": 7,
                    "conditionTypeKey": "iterations",
                    "displayOrder": 7,
                    "displayable": False,
                },
                endConditionValue=float(sd["iterations"]),
            )
            out.append(group)
            order = inner_next
        else:
            out.append(_build_executable_step(sd, order))
            order += 1
    return out, order


# --- Public entrypoint ------------------------------------------------------

def planned_to_garmin_workout(pw: dict[str, Any]) -> RunningWorkout:
    """Convert a plan_workouts row dict to a Garmin RunningWorkout.

    Uses the workout_structure JSON if present (tempo/intervals); otherwise falls
    back to a single distance-based step (easy/long/recovery/race).
    """
    wtype = pw["workout_type"]
    structure_raw = pw.get("workout_structure")
    structure = json.loads(structure_raw) if isinstance(structure_raw, str) else structure_raw

    if not is_pushable(wtype, structure):
        raise ValueError(push_status(wtype, structure) or f"workout type '{wtype}' is not pushable")

    if structure and structure.get("steps"):
        steps, _ = _build_steps(structure["steps"], start_order=1)
    else:
        # Simple single-step path.
        distance_km = pw.get("target_distance_km")
        if not distance_km or distance_km <= 0:
            raise ValueError("workout has no target distance")
        distance_m = float(distance_km) * 1000.0
        pace_s = pw.get("target_pace_s_per_km")
        step_def = {
            "type": "active",
            "end": {"distance_m": distance_m},
        }
        if pace_s:
            step_def["pace_s_per_km"] = int(pace_s)
        steps = [_build_executable_step(step_def, step_order=1)]

    estimated_s = (
        int(pw.get("target_duration_s") or 0)
        or _estimate_workout_duration_s(structure, pw.get("target_distance_km"), pw.get("target_pace_s_per_km"))
    )

    return RunningWorkout(
        workoutName=pw["title"],
        description=pw.get("description") or "",
        estimatedDurationInSecs=estimated_s,
        workoutSegments=[
            WorkoutSegment(
                segmentOrder=1,
                sportType={"sportTypeId": 1, "sportTypeKey": "running"},
                workoutSteps=steps,
            )
        ],
    )
