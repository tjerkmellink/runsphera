"""Training-plan generation engines.

Each methodology is a class implementing `Methodology.generate(params) -> list[PlannedWorkout]`.
The registry exposes available methodologies plus their human-readable metadata so the UI
can render them with explanations.
"""
from __future__ import annotations

from .methodology import (
    MethodologyInfo,
    PlannedWorkout,
    PlanParams,
    GOAL_TYPES,
    GOAL_DISTANCES_KM,
)
from .c25k import C25KPlan, PREFERRED_DAY_OFFSETS as _C25K_DAYS
from .daniels import DanielsVDOT
from .foppen_7heuvelen import MikeFoppen7Heuvelen, RUN_DAY_OFFSETS as _FOPPEN_DAYS
from .pfitzinger import Pfitzinger18_55, RUN_DAY_OFFSETS as _PFITZ_DAYS
from .higdon import HigdonPlan, tier_day_offsets as _higdon_days

# Registry: methodology_id -> (info, class_or_None).
# `cls` is None for "coming soon" methodologies — we surface them in the UI but disable selection.
_REGISTRY: dict[str, tuple[MethodologyInfo, type | None]] = {
    "daniels": (
        MethodologyInfo(
            id="daniels",
            name="Jack Daniels' VDOT",
            tagline="Pace zones derived from VO₂max. Rigorous and well-documented.",
            description=(
                "Daniels' Running Formula builds every workout around five pace zones — Easy, "
                "Marathon, Threshold, Interval, and Repetition — that scale precisely with your "
                "VDOT (a VO₂max-equivalent score). Quality work is concentrated in two sessions a "
                "week, with the rest at a strict easy pace to drive aerobic adaptation."
            ),
            best_for="All distances, all levels. Especially good when you have a recent VO₂max number.",
            available=True,
            hook="Pace zones derived from your VO₂max.",
            badge="All distances",
            badge_phase="build",
            intensity="moderate",
            stat_chips=[("8–23", "wks"), ("5–6", "days/wk")],
        ),
        DanielsVDOT,
    ),
    "foppen_7heuvelen": (
        MethodologyInfo(
            id="foppen_7heuvelen",
            name="Mike Foppen — 7 Heuvelen 15 km",
            tagline="Race-specific 11-week plan for the NN Zevenheuvelenloop. Effort-based, hill-aware.",
            description=(
                "Eleven-week plan authored by Mike Foppen (Olympic 5000 m athlete) for the "
                "NN Zevenheuvelenloop in Nijmegen. Three sessions per week — easy jog (RD), "
                "tempo run (DT), and intervals (INT) — all prescribed by duration and effort "
                "cues rather than pace zones. Fixed schedule: requires only a Sunday race "
                "date. Days-per-week and long-run-day selectors are ignored."
            ),
            best_for="Runners targeting the NN Zevenheuvelenloop (15 km hilly race, Nijmegen).",
            available=True,
            force_goal="15k",
            fixed_schedule=True,
            requires_race_date=True,
            uses_vdot_paces=False,
            fixed_day_offsets=_FOPPEN_DAYS,
            hook="Effort-based, with an eye for the hills.",
            badge="Race-specific · 15K",
            badge_phase="race",
            intensity="high",
            stat_chips=[("11", "wks"), ("3", "days/wk")],
        ),
        MikeFoppen7Heuvelen,
    ),
    "pfitzinger": (
        MethodologyInfo(
            id="pfitzinger",
            name="Pfitzinger 18/55 — Marathon",
            tagline="18-week marathon build, ~55 mi (88 km) peak. Medium-long runs + lactate threshold.",
            description=(
                "Pete Pfitzinger's marathon methodology (Advanced Marathoning): four "
                "mesocycles over 18 weeks — endurance, lactate-threshold, race preparation, "
                "taper. The signature is the mid-week medium-long run stacked alongside a "
                "weekend long run, threshold tempos, VO₂max intervals, marathon-pace long "
                "runs, and 2 tune-up races. Paces are calibrated to your VDOT; volume ramps "
                "from your base toward the ~88 km peak. Owns its 5-day/week schedule "
                "(days-per-week selector is ignored)."
            ),
            best_for="Marathoners who can build toward higher mileage and want a proven, structured 18-week plan.",
            available=True,
            force_goal="marathon",
            fixed_schedule=True,
            fixed_day_offsets=_PFITZ_DAYS,
            hook="18-week marathon build, ~88 km peak.",
            badge="Race-specific · Marathon",
            badge_phase="peak",
            intensity="high",
            stat_chips=[("18", "wks"), ("5", "days/wk"), ("~88 km", "peak")],
        ),
        Pfitzinger18_55,
    ),
    "higdon": (
        MethodologyInfo(
            id="higdon",
            name="Hal Higdon",
            tagline="Step-up plans by experience tier. Beginner-friendly.",
            description=(
                "Higdon's plans (Novice 1/2, Intermediate 1/2, Advanced 1/2) are simple, "
                "battle-tested, and use minimal quality work — mostly steady mileage with one "
                "long run. A solid choice if you don't want to think about VDOT zones. Pick "
                "your experience tier; the marathon build runs 18 weeks, the half 12. Owns its "
                "weekly schedule (day pickers are ignored)."
            ),
            best_for="First-timers and runners who prefer a low-complexity schedule.",
            available=True,
            supported_goals=["half_marathon", "marathon"],
            fixed_schedule=True,
            # Day offsets come from the engine's tier templates so the form's
            # schedule mirror can never drift from what actually generates.
            variants=[
                (vid, label, desc, _higdon_days(vid))
                for vid, label, desc in [
                    ("novice_1", "Novice 1", "New to the distance. Easy runs + one long run. No speedwork."),
                    ("novice_2", "Novice 2", "A step up: adds mid-week goal-pace running."),
                    ("intermediate_1", "Intermediate 1", "Five days a week; back-to-back weekend runs, two 20-milers."),
                    ("intermediate_2", "Intermediate 2", "More volume + a weekly tempo. Three 20-milers."),
                    ("advanced_1", "Advanced 1", "Six days: hills, goal-pace, and tempo work."),
                    ("advanced_2", "Advanced 2", "Highest volume: 800 m speed, tempo, goal-pace."),
                ]
            ],
            hook="Step-up plans by experience tier.",
            badge="Beginner-friendly",
            badge_phase="base",
            intensity="low",
            stat_chips=[("Novice → Advanced", ""), ("4–6", "days/wk"), ("12 / 18", "wks")],
        ),
        HigdonPlan,
    ),
    "c25k": (
        MethodologyInfo(
            id="c25k",
            name="Couch to 5K",
            tagline="The classic 9-week run/walk on-ramp — from zero to 30 minutes of running.",
            description=(
                "Three time-based sessions a week alternating running and walking, "
                "ramping from 8×1-minute runs to a continuous 30-minute (~5 km) "
                "graduation run. No paces, no zones — effort cues only. The "
                "gold-standard start for absolute beginners: every session opens "
                "and closes with a 5-minute brisk walk, and the walk breaks do the "
                "injury-proofing that a new runner's tendons need."
            ),
            best_for="Absolute beginners and returners after a long layoff.",
            available=True,
            force_goal="5k",
            supported_goals=["5k"],
            uses_vdot_paces=False,
            fixed_days_per_week=3,
            preferred_day_offsets=_C25K_DAYS,
            hook="From the couch to 30 minutes of running.",
            badge="Beginner · 5K",
            badge_phase="base",
            intensity="low",
            stat_chips=[("9", "wks"), ("3", "days/wk"), ("~30", "min/session")],
        ),
        C25KPlan,
    ),
    "hybrid": (
        MethodologyInfo(
            id="hybrid",
            name="Hybrid (Daniels + Hansons)",
            tagline="Daniels paces, Hansons-style cumulative fatigue.",
            description=(
                "Borrow Daniels' pace zones for precision, but follow Hansons' philosophy: cap "
                "the long run around 30% of weekly volume and move more of that volume to "
                "mid-week medium-long runs. Trains marathon-specific fatigue resistance without "
                "an oversized weekend long run."
            ),
            best_for="Marathoners who want long-run fatigue training without the 32 km weekly grind.",
            available=False,
            hook="Daniels paces, Hansons-style cumulative fatigue.",
            badge="All distances",
            badge_phase="build",
            intensity="high",
            stat_chips=[("16–18", "wks"), ("6", "days/wk")],
        ),
        None,
    ),
}


def list_methodologies() -> list[MethodologyInfo]:
    """All methodologies including unavailable ones, for UI rendering."""
    return [info for info, _ in _REGISTRY.values()]


def get_methodology(methodology_id: str):
    """Return an instance of the methodology engine, or raise if unavailable."""
    if methodology_id not in _REGISTRY:
        raise ValueError(f"Unknown methodology: {methodology_id}")
    info, cls = _REGISTRY[methodology_id]
    if cls is None:
        raise ValueError(f"Methodology '{info.name}' is not yet implemented")
    return cls()


def get_methodology_info(methodology_id: str) -> MethodologyInfo:
    """Return the UI/behaviour metadata for a methodology, or raise if unknown."""
    if methodology_id not in _REGISTRY:
        raise ValueError(f"Unknown methodology: {methodology_id}")
    return _REGISTRY[methodology_id][0]


__all__ = [
    "C25KPlan",
    "DanielsVDOT",
    "MikeFoppen7Heuvelen",
    "Pfitzinger18_55",
    "HigdonPlan",
    "GOAL_DISTANCES_KM",
    "GOAL_TYPES",
    "MethodologyInfo",
    "PlannedWorkout",
    "PlanParams",
    "get_methodology",
    "get_methodology_info",
    "list_methodologies",
]
