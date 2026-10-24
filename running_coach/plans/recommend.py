"""Rules-first plan recommendation from the fitness baseline.

Turns what we know about the runner — the plan seed (VDOT + weekly km with
per-value sources) and one self-assessment answer ("Can you currently run
10 minutes non-stop?") — into a gentle nudge on /plans/new: a "Recommended
for you" badge on one methodology tile, a pre-checked Higdon tier, and (for
true beginners) the 5K goal. Guidance only, never gating: the user can
override everything.

Deterministic and pure — no DB access; fully unit-testable. See
docs/plan-recommendation.md for the rule table.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Recommendation:
    # Tile to badge + pre-check on /plans/new. None ⇒ no recommendation
    # (rule 0: we know nothing — the UI shows the question strip instead).
    methodology_id: str | None
    # Higdon tier to pre-check. Computed even when the badge lands on a
    # different tile, so the tier pre-check fires whenever the user clicks
    # the Higdon tile.
    higdon_variant: str | None
    # Goal tile to pre-check. Only set on the beginner path ("5k").
    goal_type: str | None
    # One short sentence shown under the badge (rendered through t()).
    reason: str


_EMPTY = Recommendation(None, None, None, "")


def _higdon_tier(km_known: bool, km: float, vdot_known: bool, vdot: float) -> str:
    """Volume-first tier ladder; VDOT separates the top tiers."""
    if not km_known or km < 15:
        return "novice_1"
    if km < 25:
        return "novice_2"
    if km < 40:
        return "intermediate_1"
    if vdot_known and vdot >= 70:
        return "advanced_2"
    if vdot_known and vdot >= 55:
        return "advanced_1"
    return "intermediate_2"


def recommend_plan(
    seed: dict,
    can_run_10min: bool | None,
    available: frozenset[str] | set[str],
) -> Recommendation:
    """Map (seed, self-assessment) → a Recommendation.

    `seed` is `plan_service.get_plan_seed()` output verbatim. `available`
    is the set of available methodology ids, so the beginner rules degrade
    gracefully (c25k missing → Higdon Novice 1) and we never badge a tile
    that isn't there.
    """
    vdot = float(seed.get("current_vdot") or 0)
    vdot_known = seed.get("vdot_source") in ("garmin", "manual")
    km = float(seed.get("weekly_km_baseline") or 0)
    km_known = seed.get("weekly_km_source") in ("garmin", "manual")
    garmin_data = "garmin" in (seed.get("vdot_source"), seed.get("weekly_km_source"))

    # Someone with measured Garmin volume/VO₂max obviously runs — never
    # bother them with the 10-minute question.
    answer = can_run_10min
    if answer is None and garmin_data:
        answer = True

    tier = _higdon_tier(km_known, km, vdot_known, vdot)

    def pick(preferred: str, fallback: str = "higdon") -> str | None:
        if preferred in available:
            return preferred
        if fallback in available:
            return fallback
        return None

    # Rule 0 — we know nothing: no badge; the UI asks the question instead.
    if answer is None and not km_known and not vdot_known:
        return _EMPTY

    # Rule 1 — can't run 10 minutes yet: Couch to 5K, goal 5K.
    if answer is False:
        m = pick("c25k")
        return Recommendation(
            m, "novice_1", "5k" if m == "c25k" else None,
            "A gentle run/walk build to your first 5K.",
        )

    # Rule 2 — negligible volume (and no explicit "yes"): also the on-ramp.
    if km_known and km < 8 and can_run_10min is not True:
        m = pick("c25k")
        return Recommendation(
            m, "novice_1", "5k" if m == "c25k" else None,
            "Your current volume suits a run/walk 5K build.",
        )

    # Rule 3 — runs, but volume unknown: simple structure while we learn.
    if not km_known:
        return Recommendation(
            pick("higdon"), tier, None,
            "Simple structure while we learn your fitness.",
        )

    # Rules 4-5 — low volume: Higdon's novice tiers keep the step-up safe.
    if km < 25:
        return Recommendation(
            pick("higdon"), tier, None,
            "Steady, low-complexity structure that matches your volume.",
        )

    # Rules 6-7 — solid volume: Daniels when we have a real fitness number,
    # Higdon's middle tiers otherwise.
    if vdot_known:
        return Recommendation(
            pick("daniels"), tier, None,
            "Real fitness data + solid volume — precise pace zones pay off.",
        )
    return Recommendation(
        pick("higdon"), tier, None,
        "Solid volume — add a fitness number for pace-zone training.",
    )
