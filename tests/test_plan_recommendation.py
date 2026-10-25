"""Lock-down tests for plans/recommend.py — the rules-first enrollment
guidance (docs/plan-recommendation.md).

Seeds are hand-built dicts shaped like plan_service.get_plan_seed() output;
no DB needed.

Run from repo root:
    .venv/Scripts/python.exe tests/test_plan_recommendation.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.plans.recommend import recommend_plan  # noqa: E402

ALL = frozenset({"daniels", "foppen_7heuvelen", "pfitzinger", "higdon", "c25k"})
NO_C25K = ALL - {"c25k"}


def seed(vdot=45.0, vdot_source="default", km=25.0, km_source="default") -> dict:
    return {
        "current_vdot": vdot,
        "vdot_source": vdot_source,
        "vdot_note": None,
        "weekly_km_baseline": km,
        "weekly_km_source": km_source,
    }


def test_rule0_blank_slate_no_recommendation() -> None:
    rec = recommend_plan(seed(), None, ALL)
    assert rec.methodology_id is None
    assert rec.goal_type is None


def test_rule1_not_yet_beats_everything() -> None:
    """An explicit 'not yet' wins even over high recorded volume."""
    rec = recommend_plan(seed(km=45.0, km_source="manual", vdot=52, vdot_source="manual"), False, ALL)
    assert rec.methodology_id == "c25k"
    assert rec.goal_type == "5k"
    assert rec.higdon_variant == "novice_1"


def test_rule2_negligible_volume_gets_the_onramp() -> None:
    rec = recommend_plan(seed(km=5.0, km_source="manual"), None, ALL)
    assert rec.methodology_id == "c25k"
    assert rec.goal_type == "5k"
    # ...but an explicit "yes" overrides: they run, just not much.
    rec_yes = recommend_plan(seed(km=5.0, km_source="manual"), True, ALL)
    assert rec_yes.methodology_id == "higdon"
    assert rec_yes.goal_type is None


def test_rule3_runs_but_volume_unknown() -> None:
    rec = recommend_plan(seed(), True, ALL)
    assert rec.methodology_id == "higdon"
    assert rec.higdon_variant == "novice_1"


def test_rules_4_5_low_volume_novice_tiers() -> None:
    assert recommend_plan(seed(km=14.9, km_source="manual"), True, ALL).higdon_variant == "novice_1"
    r = recommend_plan(seed(km=15.0, km_source="garmin"), True, ALL)
    assert r.methodology_id == "higdon" and r.higdon_variant == "novice_2"
    assert recommend_plan(seed(km=24.9, km_source="manual"), True, ALL).higdon_variant == "novice_2"


def test_rules_6_7_solid_volume_daniels_needs_real_vdot() -> None:
    with_vdot = recommend_plan(
        seed(km=30.0, km_source="garmin", vdot=48, vdot_source="garmin"), None, ALL
    )
    assert with_vdot.methodology_id == "daniels"
    assert with_vdot.higdon_variant == "intermediate_1"
    without_vdot = recommend_plan(seed(km=30.0, km_source="manual"), True, ALL)
    assert without_vdot.methodology_id == "higdon"
    assert without_vdot.higdon_variant == "intermediate_1"


def test_high_volume_tier_ladder() -> None:
    assert recommend_plan(
        seed(km=45, km_source="garmin", vdot=50, vdot_source="garmin"), None, ALL
    ).higdon_variant == "intermediate_2"
    assert recommend_plan(
        seed(km=45, km_source="garmin", vdot=56, vdot_source="garmin"), None, ALL
    ).higdon_variant == "advanced_1"
    assert recommend_plan(
        seed(km=45, km_source="garmin", vdot=71, vdot_source="garmin"), None, ALL
    ).higdon_variant == "advanced_2"


def test_garmin_data_implies_yes() -> None:
    """Garmin-sourced seed → never rule 0, never the question."""
    rec = recommend_plan(seed(km=20, km_source="garmin"), None, ALL)
    assert rec.methodology_id == "higdon"
    assert rec.higdon_variant == "novice_2"


def test_c25k_unavailable_falls_back_to_higdon() -> None:
    rec = recommend_plan(seed(), False, NO_C25K)
    assert rec.methodology_id == "higdon"
    assert rec.goal_type is None, "no 5k goal push when the on-ramp engine is missing"
    assert rec.higdon_variant == "novice_1"


def test_never_recommends_unavailable_methodology() -> None:
    rec = recommend_plan(
        seed(km=40, km_source="garmin", vdot=50, vdot_source="garmin"),
        None, frozenset({"higdon"}),
    )
    assert rec.methodology_id == "higdon"  # daniels unavailable → fallback
    rec_none = recommend_plan(seed(), False, frozenset())
    assert rec_none.methodology_id is None


def test_every_recommendation_has_a_reason() -> None:
    cases = [
        (seed(), False),
        (seed(km=5, km_source="manual"), None),
        (seed(), True),
        (seed(km=20, km_source="manual"), True),
        (seed(km=30, km_source="garmin", vdot=48, vdot_source="garmin"), None),
    ]
    for s, answer in cases:
        rec = recommend_plan(s, answer, ALL)
        assert rec.methodology_id and rec.reason, (s, answer)


TESTS = [
    test_rule0_blank_slate_no_recommendation,
    test_rule1_not_yet_beats_everything,
    test_rule2_negligible_volume_gets_the_onramp,
    test_rule3_runs_but_volume_unknown,
    test_rules_4_5_low_volume_novice_tiers,
    test_rules_6_7_solid_volume_daniels_needs_real_vdot,
    test_high_volume_tier_ladder,
    test_garmin_data_implies_yes,
    test_c25k_unavailable_falls_back_to_higdon,
    test_never_recommends_unavailable_methodology,
    test_every_recommendation_has_a_reason,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}\n        {exc}")
        else:
            print(f"  ok    {fn.__name__}")
    print()
    if failed:
        print(f"{failed} / {len(TESTS)} failed")
        return 1
    print(f"{len(TESTS)} / {len(TESTS)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
