"""Tests for plans.event_swap — swapping a calendar race event into the
active plan.

Contract under test: the race always lands on the plan row at the event's
date; an optional second session that week (typically the long run) becomes
a rest day; both originals are snapshotted in plan_event_swaps and restored
byte-for-byte on revert; pushed Garmin copies of overwritten rows are
deleted best-effort; completed rows are never rewritten.

Run from repo root:
    .venv/Scripts/python.exe tests/test_event_swap.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera import race_calendar  # noqa: E402
from runsphera.db import connect  # noqa: E402
from runsphera.plans import event_swap  # noqa: E402
from runsphera.plans import service as plan_service  # noqa: E402


def _next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def _sunday_weeks_out(n: int) -> date:
    return _next_monday() + timedelta(weeks=n - 1, days=6)


def _fresh_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return connect(tmp)


def _make_plan(conn, race_weeks_out: int = 12):
    pid = plan_service.create_plan(
        conn,
        goal_type="half_marathon",
        methodology_id="daniels",
        race_date=_sunday_weeks_out(race_weeks_out),
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        workout_days=[1, 3, 5, 6],
    )
    return plan_service.get_plan(conn, pid)


def _row(conn, pw_id):
    return dict(conn.execute(
        "SELECT * FROM plan_workouts WHERE id = ?", (pw_id,)
    ).fetchone())


def _week_rows(conn, plan_id, week_number):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM plan_workouts WHERE plan_id = ? AND week_number = ? "
        "ORDER BY planned_date",
        (plan_id, week_number),
    ).fetchall()]


def _long_run(conn, plan_id, week_number):
    return next(r for r in _week_rows(conn, plan_id, week_number)
                if r["workout_type"] == "long")


def _rest_day(conn, plan_id, week_number):
    return next(r for r in _week_rows(conn, plan_id, week_number)
                if r["workout_type"] == "rest")


def _add_event(conn, race_date_iso: str, name="100 Bruggenloop", km=15.0,
               label="15 km"):
    return race_calendar.add_user_event(
        conn,
        name=name,
        race_date=date.fromisoformat(race_date_iso),
        distance_km=km,
        distance_label=label,
        city="Rotterdam",
    )


class _FakeGarmin:
    def __init__(self):
        self.deleted: list[int] = []

    def delete_workout(self, wid):
        self.deleted.append(wid)


# ── tests ────────────────────────────────────────────────────────────


def test_swap_on_long_run_day():
    """The user's headline case: race lands directly on the long-run day."""
    conn = _fresh_conn()
    plan = _make_plan(conn)
    long_run = _long_run(conn, plan["id"], 4)

    event_id = _add_event(conn, long_run["planned_date"])
    event = race_calendar.get_event(conn, event_id)

    ctx = event_swap.swap_context(conn, plan, event)
    assert ctx["eligible"], ctx
    assert ctx["target"]["id"] == long_run["id"]
    # Race lands on the long run itself — no extra session proposed.
    assert ctx["proposed_extra_id"] is None

    result = event_swap.apply_swap(
        conn, None, event_id=event_id, distance_km=15.0, distance_label="15 km",
    )
    assert result["swapped"] and result["race_workout_id"] == long_run["id"]
    assert result["displaced_workout_id"] is None

    row = _row(conn, long_run["id"])
    assert row["workout_type"] == "race"
    assert "100 Bruggenloop" in row["title"] and "15 km" in row["title"]
    assert row["target_distance_km"] == 15.0
    assert row["workout_structure"] is None
    assert long_run["title"] in row["description"]

    # Bookkeeping: swap recorded, event saved to the runner's calendar.
    swap = event_swap.get_swap_for_event(conn, event_id, plan["id"])
    assert swap and swap["race_workout_id"] == long_run["id"]
    assert swap["race_original"]["title"] == long_run["title"]
    assert race_calendar.is_favorited(conn, event_id)

    # Modal lookup resolves the race role; context now reports "swapped".
    by_workout = event_swap.get_swap_for_workout(conn, long_run["id"])
    assert by_workout["role"] == "race"
    assert by_workout["event_name"] == "100 Bruggenloop"
    ctx2 = event_swap.swap_context(conn, plan, event)
    assert ctx2["swapped"] and not ctx2["eligible"]


def test_swap_on_rest_day_displacing_long_run():
    """Race on a rest day + give up the week's long run for it."""
    conn = _fresh_conn()
    plan = _make_plan(conn)
    rest = _rest_day(conn, plan["id"], 4)
    long_run = _long_run(conn, plan["id"], 4)

    event_id = _add_event(conn, rest["planned_date"])
    event = race_calendar.get_event(conn, event_id)

    ctx = event_swap.swap_context(conn, plan, event)
    assert ctx["eligible"]
    assert ctx["target"]["id"] == rest["id"]
    # The long run is the default pick to free up.
    assert ctx["proposed_extra_id"] == long_run["id"]
    assert any(c["id"] == long_run["id"] for c in ctx["extra_candidates"])

    event_swap.apply_swap(
        conn, None, event_id=event_id, distance_km=15.0, distance_label="15 km",
        displaced_workout_id=long_run["id"],
    )

    race_row = _row(conn, rest["id"])
    assert race_row["workout_type"] == "race"
    freed = _row(conn, long_run["id"])
    assert freed["workout_type"] == "rest"
    assert freed["target_distance_km"] is None
    assert "100 Bruggenloop" in freed["description"]

    # Displaced row resolves to the 'displaced' role for the modal.
    by_workout = event_swap.get_swap_for_workout(conn, long_run["id"])
    assert by_workout["role"] == "displaced"


def test_revert_restores_both_rows():
    conn = _fresh_conn()
    plan = _make_plan(conn)
    rest = _rest_day(conn, plan["id"], 4)
    long_run = _long_run(conn, plan["id"], 4)

    event_id = _add_event(conn, rest["planned_date"])
    event_swap.apply_swap(
        conn, None, event_id=event_id, distance_km=15.0,
        displaced_workout_id=long_run["id"],
    )
    swap = event_swap.get_swap_for_event(conn, event_id, plan["id"])

    result = event_swap.revert_swap(conn, None, swap["id"])
    assert result["reverted"]
    assert set(result["restored_workout_ids"]) == {rest["id"], long_run["id"]}

    backup_fields = ("workout_type", "title", "description",
                     "target_distance_km", "target_duration_s",
                     "target_pace_s_per_km", "workout_structure")
    for original in (rest, long_run):
        restored = _row(conn, original["id"])
        for f in backup_fields:
            assert restored[f] == original[f], (original["id"], f)

    assert event_swap.get_swap_for_event(conn, event_id, plan["id"]) is None


def test_guards():
    conn = _fresh_conn()
    plan = _make_plan(conn)

    # Outside the plan window.
    outside_id = _add_event(
        conn, (date.fromisoformat(plan["race_date"]) + timedelta(days=30)).isoformat()
    )
    try:
        event_swap.apply_swap(conn, None, event_id=outside_id, distance_km=10.0)
        raise AssertionError("expected ValueError for out-of-window event")
    except ValueError:
        pass

    # The plan's own goal race day is off-limits.
    goal_day_id = _add_event(conn, plan["race_date"])
    try:
        event_swap.apply_swap(conn, None, event_id=goal_day_id, distance_km=10.0)
        raise AssertionError("expected ValueError for goal race day")
    except ValueError:
        pass

    # Completed target day is locked.
    long_run = _long_run(conn, plan["id"], 4)
    conn.execute("UPDATE plan_workouts SET actual_activity_id = 999 WHERE id = ?",
                 (long_run["id"],))
    conn.commit()
    done_id = _add_event(conn, long_run["planned_date"])
    try:
        event_swap.apply_swap(conn, None, event_id=done_id, distance_km=10.0)
        raise AssertionError("expected ValueError for completed day")
    except ValueError:
        pass

    # Double swap of the same event is refused.
    rest = _rest_day(conn, plan["id"], 5)
    twice_id = _add_event(conn, rest["planned_date"])
    event_swap.apply_swap(conn, None, event_id=twice_id, distance_km=10.0)
    try:
        event_swap.apply_swap(conn, None, event_id=twice_id, distance_km=10.0)
        raise AssertionError("expected ValueError for double swap")
    except ValueError:
        pass

    # A displaced pick outside the candidate set (other week) is refused.
    rest6 = _rest_day(conn, plan["id"], 6)
    other_week_long = _long_run(conn, plan["id"], 8)
    bad_pick_id = _add_event(conn, rest6["planned_date"])
    try:
        event_swap.apply_swap(conn, None, event_id=bad_pick_id, distance_km=10.0,
                              displaced_workout_id=other_week_long["id"])
        raise AssertionError("expected ValueError for cross-week displaced pick")
    except ValueError:
        pass


def test_garmin_cleanup_on_swap_and_revert():
    conn = _fresh_conn()
    plan = _make_plan(conn)
    rest = _rest_day(conn, plan["id"], 4)
    long_run = _long_run(conn, plan["id"], 4)
    conn.execute("UPDATE plan_workouts SET garmin_workout_id = 111, "
                 "pushed_at = '2026-01-01' WHERE id = ?", (long_run["id"],))
    conn.commit()

    event_id = _add_event(conn, rest["planned_date"])
    client = _FakeGarmin()
    event_swap.apply_swap(
        conn, client, event_id=event_id, distance_km=15.0,
        displaced_workout_id=long_run["id"],
    )
    assert client.deleted == [111]
    assert _row(conn, long_run["id"])["garmin_workout_id"] is None

    # Push the race itself, then revert — the stale race copy is deleted too.
    conn.execute("UPDATE plan_workouts SET garmin_workout_id = 222, "
                 "pushed_at = '2026-01-02' WHERE id = ?", (rest["id"],))
    conn.commit()
    swap = event_swap.get_swap_for_event(conn, event_id, plan["id"])
    client2 = _FakeGarmin()
    event_swap.revert_swap(conn, client2, swap["id"])
    assert client2.deleted == [222]


def test_revert_refused_after_race_completed():
    conn = _fresh_conn()
    plan = _make_plan(conn)
    long_run = _long_run(conn, plan["id"], 4)
    event_id = _add_event(conn, long_run["planned_date"])
    event_swap.apply_swap(conn, None, event_id=event_id, distance_km=15.0)
    conn.execute("UPDATE plan_workouts SET actual_activity_id = 999 WHERE id = ?",
                 (long_run["id"],))
    conn.commit()
    swap = event_swap.get_swap_for_event(conn, event_id, plan["id"])
    try:
        event_swap.revert_swap(conn, None, swap["id"])
        raise AssertionError("expected ValueError for completed race")
    except ValueError:
        pass


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"ok    {fn.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL  {fn.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"ERROR {fn.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
