"""Common types for plan generation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any

GOAL_TYPES = ("stay_fit", "5k", "10k", "15k", "half_marathon", "marathon")

GOAL_DISTANCES_KM: dict[str, float | None] = {
    "stay_fit": None,
    "5k": 5.0,
    "10k": 10.0,
    "15k": 15.0,
    "half_marathon": 21.0975,
    "marathon": 42.195,
}

GOAL_LABELS: dict[str, str] = {
    "stay_fit": "Stay fit",
    "5k": "5 km race",
    "10k": "10 km race",
    "15k": "15 km race",
    "half_marathon": "Half marathon",
    "marathon": "Marathon",
}


@dataclass
class MethodologyInfo:
    """Human-readable metadata for a methodology, used by the UI."""
    id: str
    name: str
    tagline: str
    description: str
    best_for: str
    available: bool
    # When set, the UI auto-selects this goal and disables the other goal tiles
    # when this methodology is picked. Used for race-specific imported plans.
    force_goal: str | None = None
    # Goal allow-list. When non-empty, only these goals are selectable for this
    # methodology (the form disables the rest). `force_goal` is the single-goal
    # special case; `supported_goals` lets a methodology offer a subset of more
    # than one (e.g. Higdon: half + marathon). Empty ⇒ all goals allowed.
    supported_goals: list[str] = field(default_factory=list)
    # Methodology sub-plans surfaced as a picker on the create form, e.g.
    # Higdon's experience tiers. Each entry is (variant_id, label, short_desc,
    # day_offsets) where day_offsets are the variant's run-day positions
    # relative to the long-run day — the form uses them to mirror the fixed
    # schedule in the (dimmed) day pickers. Empty ⇒ no variant picker. The
    # chosen id rides through as PlanParams.variant and is persisted to
    # plans.variant so reshape can regenerate the same variant.
    variants: list[tuple[str, str, str, list[int]]] = field(default_factory=list)
    # Run-day offsets from the long-run day for fixed-schedule methodologies
    # WITHOUT variants (Foppen, Pfitzinger) — same form-mirroring purpose as
    # the per-variant offsets above. Empty ⇒ the form leaves the pickers as
    # the user set them.
    fixed_day_offsets: list[int] = field(default_factory=list)
    # True when the methodology owns its weekly schedule: the UI neutralises
    # the days-per-week / training-day pickers, the server ignores their
    # submitted values, and the persisted schedule is derived from the
    # workouts the methodology actually generated.
    fixed_schedule: bool = False
    # True when the plan targets one specific real-world race (imported
    # race plans like Foppen's 7 Heuvelen): the race date stays mandatory.
    # Everything else can be built without a race — the server synthesizes
    # a goal date on the final week's long-run day instead.
    requires_race_date: bool = False
    # False when the plan is effort/time-based and carries no VDOT pace
    # targets (Foppen, Couch to 5K). The recalibrate/set-VDOT UI hides,
    # and the service refuses to recalibrate or soft-swap — stamping E/M/T/I/R
    # paces onto effort-cue sessions would corrupt them.
    uses_vdot_paces: bool = True
    # Set when the methodology owns its session count but NOT the weekday
    # placement (Couch to 5K: always 3 sessions, on days the runner picks).
    # The form locks the days-per-week selector to this value; the engine
    # still validates server-side.
    fixed_days_per_week: int | None = None
    # Default day picks for such methodologies: offsets from the long-run
    # day the form seeds the training-day checkboxes with (e.g. C25K's
    # [-4, -2, 0] → Wed/Fri/Sun on a Sunday anchor — a rest day between
    # every session). Empty ⇒ the form falls back to the generic Daniels
    # slot pattern. Feed this from the engine's own constant so the form's
    # defaults can never drift from what generate() would do on its own.
    preferred_day_offsets: list[int] = field(default_factory=list)

    # ── Tile presentation (methodology picker on /plans/new) ────────────
    # These drive the illustrated gallery tile. Hero art is a per-id PNG pair
    # in /static/heroes/<id>-{light,dark}.png; the rest is authored copy so
    # the tile stays scannable without parsing it out of `description`.
    #
    # Short one-line hook shown under the title (distinct from the longer
    # `tagline`). Falls back to `tagline` in the template when empty.
    hook: str = ""
    # Hero badge label (e.g. "All distances", "Race-specific · Marathon").
    badge: str = ""
    # Phase-token key colouring the badge dot: base|build|peak|taper|race|maintain.
    badge_phase: str = "build"
    # Intensity level driving the tinted chip: "low" | "moderate" | "high"
    # (empty hides the chip).
    intensity: str = ""
    # Plain fact chips as (value, label) pairs — value renders in mono, label
    # is translated. e.g. ("18", "wks"), ("~88 km", "peak"), ("Novice → Advanced", "").
    stat_chips: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class PlanParams:
    goal_type: str
    start_date: date
    race_date: date | None
    target_time_s: int | None
    days_per_week: int
    long_run_day: int  # 0=Mon ... 6=Sun
    current_vdot: float
    weekly_km_baseline: float
    # User-picked weekdays the runner trains on (0=Mon..6=Sun). Length must
    # equal `days_per_week` and include `long_run_day`. When None, the
    # methodology falls back to a fixed slot pattern anchored to long_run_day.
    workout_days: list[int] | None = None
    # Methodology sub-plan selector (e.g. Higdon experience tier). None ⇒ the
    # methodology picks its own default. See MethodologyInfo.variants.
    variant: str | None = None


@dataclass
class PlannedWorkout:
    week_number: int
    week_phase: str
    day_of_week: int
    planned_date: date
    workout_type: str  # 'easy' | 'long' | 'tempo' | 'intervals' | 'recovery' | 'rest' | 'race' | 'cross'
    title: str
    description: str
    target_distance_km: float | None = None
    target_duration_s: int | None = None
    target_pace_s_per_km: int | None = None
    # Optional structured step list for multi-step workouts (tempo, intervals).
    # Shape: {"steps": [{"type": ..., "end": {...}, "pace_s_per_km": ...}, ...]}
    # Step types: warmup | active | recovery | cooldown | repeat (with nested "steps")
    # End condition: {"distance_m": N} or {"duration_s": N}
    workout_structure: dict[str, Any] | None = None


class Methodology(ABC):
    @abstractmethod
    def generate(self, params: PlanParams) -> list[PlannedWorkout]:
        """Produce the full list of workouts for the plan, including rest days."""

    @abstractmethod
    def total_weeks(self, goal_type: str, race_date: date | None, start_date: date) -> int:
        """How many weeks the plan should span for this goal."""
