"""Totals derived from a `workout_structure`.

`workout_structure` is the contract with the watch (architecture decision #4),
so it is the authority on what a session actually asks of the runner. The
headline columns — `target_distance_km`, `target_pace_s_per_km`,
`target_duration_s` — must agree with it, or the plan reports one volume while
the watch prescribes another.

This lives in its own module because both sides need it and neither may import
the other: `plans/service.py` uses it when an edit rebuilds a structure, and
the engines in `plans/daniels.py` use it at generation time.
"""
from __future__ import annotations

# Warmup/cooldown steps often carry no pace. Count them at a plausible easy
# pace so durations are not wildly short; Garmin recomputes from the actual run.
DEFAULT_PACE_S = 360


def totals_from_structure(structure: dict | None, fallback_pace: int | None = None) -> dict:
    """Walk the steps and compute total km + a representative pace + total seconds.

    Pace = the first active step's ``pace_s_per_km`` (the "headline" pace the
    runner aims for during the working bit). Duration = sum across steps, using
    each step's own pace when present, otherwise ``fallback_pace``. Recovery
    steps measured in ``duration_s`` contribute their own seconds.

    Repeats multiply their children, so a 5x1000m block with 120s recoveries
    counts all five reps *and* all five recoveries — the distance the runner
    covers, not the distance of the working intervals alone.
    """
    total_km = 0.0
    total_s = 0
    active_pace: int | None = None
    default_pace = fallback_pace if fallback_pace else DEFAULT_PACE_S

    def walk(steps: list[dict], multiplier: int = 1) -> None:
        nonlocal total_km, total_s, active_pace
        for step in steps:
            if step.get("type") == "repeat":
                iters = int(step.get("iterations", 1))
                walk(step.get("steps", []), multiplier * iters)
                continue
            end = step.get("end", {})
            pace_s = step.get("pace_s_per_km")
            if step.get("type") == "active" and pace_s and active_pace is None:
                active_pace = int(pace_s)
            if "distance_m" in end:
                km = end["distance_m"] / 1000.0
                total_km += km * multiplier
                total_s += int(km * (pace_s or default_pace)) * multiplier
            elif "duration_s" in end:
                secs = int(end["duration_s"])
                total_s += secs * multiplier
                # A timed step still covers ground. Interval recoveries and
                # stride jogs are expressed in seconds, but the runner is
                # moving — omitting their distance understates the session by
                # roughly a kilometre on a 6-stride taper run.
                #
                # Never price a recovery at the session's headline pace: that
                # is the *work* pace (R, I, T), and a jog between 100 m strides
                # is easy by definition. An unpaced recovery uses the easy
                # default instead.
                step_pace = pace_s
                if step_pace is None:
                    step_pace = (
                        DEFAULT_PACE_S if step.get("type") == "recovery" else default_pace
                    )
                total_km += (secs / step_pace) * multiplier

    walk((structure or {}).get("steps", []))
    return {
        "total_km": round(total_km, 2),
        "total_duration_s": total_s,
        "headline_pace_s": active_pace or fallback_pace,
    }
