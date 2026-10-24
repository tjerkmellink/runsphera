"""Tests for plan_service.reshape_plan — the Schedule & race date editor.

Contract under test: reshaping regenerates the plan with the new schedule
params and splices it in from "today" onward. History and completed rows are
never rewritten; pushed future workouts are deleted from Garmin best-effort;
the plans row always matches the generated schedule.

Run from repo root:
    .venv/Scripts/python.exe tests/test_plan_reshape.py
"""
from __future__ import annotations

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach.db import connect  # noqa: E402
from running_coach.plans import service as plan_service  # noqa: E402


def _next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7)


def _sunday_weeks_out(n: int) -> date:
    """The Sunday of the week `n` weeks after the plan-start Monday."""
    return _next_monday() + timedelta(weeks=n - 1, days=6)


def _fresh_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return connect(tmp)


def _make_daniels_plan(conn, race_weeks_out: int = 12):
    return plan_service.create_plan(
        conn,
        goal_type="half_marathon",
        methodology_id="daniels",
        race_date=_sunday_weeks_out(race_weeks_out),
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        workout_days=[1, 3, 5, 6],
    )


def _make_pfitz_plan(conn, race_weeks_out: int = 14):
    return plan_service.create_plan(
        conn,
        goal_type="marathon",
        methodology_id="pfitzinger",
        race_date=_sunday_weeks_out(race_weeks_out),
        target_time_s=None,
        days_per_week=5,
        long_run_day=6,
    )


def _rows(conn, plan_id):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM plan_workouts WHERE plan_id = ? ORDER BY planned_date",
        (plan_id,),
    ).fetchall()]


def _mid_plan_today(conn, plan_id, weeks_in: int = 2) -> str:
    first = _rows(conn, plan_id)[0]["planned_date"]
    return (date.fromisoformat(first) + timedelta(weeks=weeks_in)).isoformat()


class _FakeGarmin:
    def __init__(self):
        self.deleted: list[int] = []

    def delete_workout(self, wid):
        self.deleted.append(wid)


def test_reshape_moves_training_days() -> None:
    conn = _fresh_conn()
    pid = _make_daniels_plan(conn)
    today = _mid_plan_today(conn, pid)
    before = _rows(conn, pid)
    past_before = [r for r in before if r["planned_date"] < today]

    result = plan_service.reshape_plan(
        conn, None, pid,
        days_per_week=4, long_run_day=5, workout_days=[0, 2, 4, 5],
        today_iso=today,
    )
    after = _rows(conn, pid)
    past_after = [r for r in after if r["planned_date"] < today]

    # History untouched — same ids, dates, titles.
    assert [(r["id"], r["planned_date"], r["title"]) for r in past_before] == \
           [(r["id"], r["planned_date"], r["title"]) for r in past_after]
    # Future run days follow the new pattern.
    # Race day stays anchored to the race date whatever the training days —
    # exclude it from the pattern check.
    future_run_days = {
        date.fromisoformat(r["planned_date"]).weekday()
        for r in after
        if r["planned_date"] >= today
        and r["workout_type"] not in ("rest", "cross", "race")
    }
    assert future_run_days <= {0, 2, 4, 5}, f"unexpected run days: {future_run_days}"
    # Plans row matches the new schedule.
    plan = plan_service.get_plan(conn, pid)
    assert plan["long_run_day"] == 5
    assert plan["workout_days"] == "0,2,4,5"
    assert result["n_added"] > 0 and result["n_removed"] > 0


def test_reshape_keeps_completed_future_row() -> None:
    conn = _fresh_conn()
    pid = _make_daniels_plan(conn)
    today = _mid_plan_today(conn, pid)
    done = next(r for r in _rows(conn, pid)
                if r["planned_date"] >= today and r["workout_type"] not in ("rest", "cross"))
    conn.execute("UPDATE plan_workouts SET actual_activity_id = 999 WHERE id = ?", (done["id"],))
    conn.commit()

    result = plan_service.reshape_plan(
        conn, None, pid,
        days_per_week=4, long_run_day=5, workout_days=[0, 2, 4, 5],
        today_iso=today,
    )
    after = _rows(conn, pid)
    same_day = [r for r in after if r["planned_date"] == done["planned_date"]]
    assert len(same_day) == 1, "completed row must not be duplicated"
    assert same_day[0]["id"] == done["id"], "completed row must survive as-is"
    assert result["n_kept_done"] == 1


def test_reshape_race_date_moves_race() -> None:
    conn = _fresh_conn()
    pid = _make_daniels_plan(conn, race_weeks_out=12)
    today = _mid_plan_today(conn, pid)
    old_race = plan_service.get_plan(conn, pid)["race_date"]
    new_race = _sunday_weeks_out(14)

    plan_service.reshape_plan(conn, None, pid, race_date=new_race, today_iso=today)
    after = _rows(conn, pid)
    race_rows = [r for r in after if r["workout_type"] == "race"]
    assert any(r["planned_date"] == new_race.isoformat() for r in race_rows), \
        f"race not on {new_race}: {[r['planned_date'] for r in race_rows]}"
    assert not any(r["planned_date"] == old_race for r in race_rows), "old race day survived"
    assert plan_service.get_plan(conn, pid)["race_date"] == new_race.isoformat()
    assert max(r["week_number"] for r in after) == 14


def test_reshape_deletes_pushed_future_from_garmin() -> None:
    conn = _fresh_conn()
    pid = _make_daniels_plan(conn)
    today = _mid_plan_today(conn, pid)
    victim = next(r for r in _rows(conn, pid) if r["planned_date"] >= today)
    conn.execute(
        "UPDATE plan_workouts SET garmin_workout_id = 424242, pushed_at = datetime('now') "
        "WHERE id = ?", (victim["id"],),
    )
    conn.commit()

    client = _FakeGarmin()
    result = plan_service.reshape_plan(
        conn, client, pid,
        days_per_week=4, long_run_day=5, workout_days=[0, 2, 4, 5],
        today_iso=today,
    )
    assert client.deleted == [424242]
    assert result["garmin_cleaned"] == 1


def test_reshape_pfitzinger_race_weekday_reanchors() -> None:
    conn = _fresh_conn()
    pid = _make_pfitz_plan(conn, race_weeks_out=14)
    today = _mid_plan_today(conn, pid)
    old_race = date.fromisoformat(plan_service.get_plan(conn, pid)["race_date"])
    new_race = old_race - timedelta(days=1)  # Sunday -> Saturday, same weekend

    plan_service.reshape_plan(conn, None, pid, race_date=new_race, today_iso=today)
    plan = plan_service.get_plan(conn, pid)
    assert plan["long_run_day"] == new_race.weekday(), "long-run day must follow the race weekday"
    after = _rows(conn, pid)
    race_rows = [r for r in after if r["workout_type"] == "race"
                 and r["planned_date"] == new_race.isoformat()]
    assert race_rows, "marathon must land on the new race date"


def test_reshape_pfitzinger_far_race_rejected() -> None:
    """Moving the race so far out that the 18-week cap would shift the plan's
    start must be refused, not silently spliced with a gap."""
    conn = _fresh_conn()
    pid = _make_pfitz_plan(conn, race_weeks_out=14)
    today = _mid_plan_today(conn, pid)
    far_race = _sunday_weeks_out(25)
    _raises(
        lambda: plan_service.reshape_plan(conn, None, pid, race_date=far_race, today_iso=today),
        "shift",
    )


def test_reshape_rejects_bad_day_picks() -> None:
    conn = _fresh_conn()
    pid = _make_daniels_plan(conn)
    today = _mid_plan_today(conn, pid)
    _raises(
        lambda: plan_service.reshape_plan(
            conn, None, pid,
            days_per_week=4, long_run_day=6, workout_days=[1, 3, 6],
            today_iso=today,
        ),
        "exactly 4",
    )
    _raises(
        lambda: plan_service.reshape_plan(
            conn, None, pid,
            days_per_week=4, long_run_day=0, workout_days=[1, 3, 5, 6],
            today_iso=today,
        ),
        "long run day",
    )


def test_reshape_rejects_past_race_date() -> None:
    conn = _fresh_conn()
    pid = _make_daniels_plan(conn)
    today = _mid_plan_today(conn, pid)
    _raises(
        lambda: plan_service.reshape_plan(
            conn, None, pid,
            race_date=date.fromisoformat(today) - timedelta(days=1),
            today_iso=today,
        ),
        "future",
    )


def _make_higdon_plan(conn, variant=None, goal_type="marathon", race_weeks_out=20):
    return plan_service.create_plan(
        conn,
        goal_type=goal_type,
        methodology_id="higdon",
        race_date=_sunday_weeks_out(race_weeks_out),
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        variant=variant,
    )


def test_create_plan_validates_variant() -> None:
    """The variant allow-list is enforced server-side — the form's picker is
    JS-only and can be bypassed. Unknown variants must fail loud, not silently
    generate Novice 1 under a lying label (also on every future reshape)."""
    conn = _fresh_conn()
    _raises(lambda: _make_higdon_plan(conn, variant="garbage"), "unknown")
    # Goal allow-list too: Higdon declares half + marathon only.
    _raises(lambda: _make_higdon_plan(conn, goal_type="10k"), "does not offer")


def test_create_plan_normalizes_variant() -> None:
    """Missing variant defaults to the first declared tier (persisted label
    always matches the generated plan); methodologies without variants never
    persist one, even when a no-JS form submit POSTs the picker's default."""
    conn = _fresh_conn()
    pid = _make_higdon_plan(conn)  # no variant given
    row = conn.execute("SELECT variant FROM plans WHERE id = ?", (pid,)).fetchone()
    assert row["variant"] == "novice_1", dict(row)

    pid2 = plan_service.create_plan(
        conn,
        goal_type="half_marathon",
        methodology_id="daniels",
        race_date=_sunday_weeks_out(12),
        target_time_s=None,
        days_per_week=4,
        long_run_day=6,
        workout_days=[1, 3, 5, 6],
        variant="novice_1",  # what a no-JS submit would POST
    )
    row2 = conn.execute("SELECT variant FROM plans WHERE id = ?", (pid2,)).fetchone()
    assert row2["variant"] is None, dict(row2)


def test_reshape_higdon_keeps_variant() -> None:
    """Reshaping a Higdon plan regenerates in the persisted tier."""
    conn = _fresh_conn()
    pid = _make_higdon_plan(conn, variant="advanced_1")
    today = _mid_plan_today(conn, pid)
    plan_service.reshape_plan(conn, None, pid, today_iso=today)
    row = conn.execute("SELECT variant FROM plans WHERE id = ?", (pid,)).fetchone()
    assert row["variant"] == "advanced_1", dict(row)
    # advanced_1 signature: hill-repeat interval days survive the reshape.
    types = {
        r[0] for r in conn.execute(
            "SELECT DISTINCT workout_type FROM plan_workouts WHERE plan_id = ?",
            (pid,),
        )
    }
    assert "intervals" in types, types


def _raises(fn, needle: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert needle.lower() in str(exc).lower(), f"wrong error: {exc}"
    else:
        raise AssertionError(f"expected ValueError mentioning {needle!r}")


# ──────────────────────────────────────────────────────────────────────────

TESTS = [
    test_reshape_moves_training_days,
    test_reshape_keeps_completed_future_row,
    test_reshape_race_date_moves_race,
    test_reshape_deletes_pushed_future_from_garmin,
    test_reshape_pfitzinger_race_weekday_reanchors,
    test_reshape_pfitzinger_far_race_rejected,
    test_reshape_rejects_bad_day_picks,
    test_reshape_rejects_past_race_date,
    test_create_plan_validates_variant,
    test_create_plan_normalizes_variant,
    test_reshape_higdon_keeps_variant,
]


def main() -> int:
    failed = 0
    for fn in TESTS:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {fn.__name__}\n        {exc}")
        except Exception as exc:  # noqa: BLE001 — surface hard errors too
            failed += 1
            print(f"  ERROR {fn.__name__}\n        {type(exc).__name__}: {exc}")
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
