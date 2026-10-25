"""Tests for the "This week, wrapped" data layer (2026-07-26).

Covers plan_service.week_stats() and its helpers — current-week detection,
per-week actual distance/time sums, cumulative plan distance, the forgiving
(≥80%) consistency streak, and the complete flag.

Rather than generate a real plan (whose dates never line up with a fixed
"today"), these build a small synthetic 3-week plan directly in the DB so the
adherence/streak edges are explicit.

Run from repo root:
    .venv/Scripts/python.exe tests/test_week_stats.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera.db import connect  # noqa: E402
from runsphera.plans import service as plan_service  # noqa: E402

TODAY = "2026-03-18"  # a Wednesday inside week 3 (2026-03-16 .. 03-22)

# Each week: Mon easy, Wed quality, Sat long, Sun rest → 3 qualifying sessions.
_WEEKS = {
    1: {"start": "2026-03-02", "days": [("2026-03-02", "easy"), ("2026-03-04", "quality"),
                                         ("2026-03-07", "long"), ("2026-03-08", "rest")]},
    2: {"start": "2026-03-09", "days": [("2026-03-09", "easy"), ("2026-03-11", "quality"),
                                         ("2026-03-14", "long"), ("2026-03-15", "rest")]},
    3: {"start": "2026-03-16", "days": [("2026-03-16", "easy"), ("2026-03-18", "quality"),
                                         ("2026-03-21", "long"), ("2026-03-22", "rest")]},
}


def _fresh_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return connect(tmp)


def _make_plan(conn) -> int:
    cur = conn.execute(
        "INSERT INTO plans (goal_type, methodology, days_per_week, long_run_day, title) "
        "VALUES ('marathon', 'daniels', 3, 6, 'Test plan')"
    )
    conn.commit()
    return cur.lastrowid


def _add_activity(conn, activity_id: int, date_iso: str, *, km: float, dur_s: int,
                  load: float | None = None, climb_m: float | None = None) -> None:
    conn.execute(
        """INSERT INTO activities
           (activity_id, activity_type, start_time_local, start_time_gmt,
            duration_s, distance_m, training_load, elevation_gain_m, raw_json)
           VALUES (?, 'running', ?, ?, ?, ?, ?, ?, '{}')""",
        (activity_id, f"{date_iso}T07:00:00", f"{date_iso}T06:00:00",
         dur_s, km * 1000.0, load, climb_m),
    )
    conn.commit()


def _build_plan(conn, plan_id: int, matched: dict[int, set[int]]) -> None:
    """Insert all weeks' workouts. `matched` maps week_number → set of the
    session indices (0=Mon easy, 1=Wed quality, 2=Sat long) that have a run."""
    aid = 1000
    for wn, wk in _WEEKS.items():
        session_i = 0
        for date_iso, wtype in wk["days"]:
            actual = None
            if wtype != "rest":
                if session_i in matched.get(wn, set()):
                    aid += 1
                    _add_activity(conn, aid, date_iso, km=10.0, dur_s=3000, load=80.0, climb_m=50.0)
                    actual = aid
                session_i += 1
            conn.execute(
                """INSERT INTO plan_workouts
                   (plan_id, week_number, week_phase, day_of_week, planned_date,
                    workout_type, title, target_distance_km, actual_activity_id)
                   VALUES (?, ?, 'build', 0, ?, ?, ?, 10.0, ?)""",
                (plan_id, wn, date_iso, wtype, f"{wtype} run", actual),
            )
    conn.commit()


def _week_stats(conn, plan_id: int, week_number: int, today_iso: str = TODAY) -> dict:
    weeks = plan_service.get_plan_weeks(conn, plan_id)
    week = next(w for w in weeks if w["week_number"] == week_number)
    return plan_service.week_stats(conn, plan_id, weeks, week, today_iso)


# ── current_plan_week ────────────────────────────────────────────────────

def test_current_plan_week_finds_today() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    _build_plan(conn, pid, matched={})
    weeks = plan_service.get_plan_weeks(conn, pid)
    cur = plan_service.current_plan_week(weeks, TODAY)
    assert cur is not None and cur["week_number"] == 3, cur


def test_current_plan_week_none_outside() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    _build_plan(conn, pid, matched={})
    weeks = plan_service.get_plan_weeks(conn, pid)
    assert plan_service.current_plan_week(weeks, "2026-05-01") is None


# ── completion + counts ──────────────────────────────────────────────────

def test_incomplete_week_counts() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    # Week 3: only the Monday easy run done.
    _build_plan(conn, pid, matched={1: {0, 1, 2}, 2: {0, 1, 2}, 3: {0}})
    s = _week_stats(conn, pid, 3)
    assert s["sessions_planned"] == 3
    assert s["sessions_done"] == 1
    assert s["complete"] is False
    assert s["pct"] == 33


def test_complete_week_flag() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    _build_plan(conn, pid, matched={1: {0, 1, 2}, 2: {0, 1, 2}, 3: {0, 1, 2}})
    s = _week_stats(conn, pid, 3)
    assert s["complete"] is True
    assert s["sessions_done"] == 3 and s["sessions_planned"] == 3
    assert s["pct"] == 100


# ── actual sums ──────────────────────────────────────────────────────────

def test_week_distance_time_load_sums() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    _build_plan(conn, pid, matched={3: {0, 1}})  # two 10 km / 3000 s / TL80 runs
    s = _week_stats(conn, pid, 3)
    assert s["distance_km"] == 20.0
    assert s["moving_time_s"] == 6000
    assert s["load"] == 160
    assert s["climb_m"] == 100
    assert s["longest_run_km"] == 10.0


def test_plan_distance_cumulative() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    # 3 done in wk1, 3 in wk2, 1 in wk3 → 7 runs × 10 km = 70 km banked.
    _build_plan(conn, pid, matched={1: {0, 1, 2}, 2: {0, 1, 2}, 3: {0}})
    s = _week_stats(conn, pid, 3)
    assert s["plan_runs_done"] == 7
    assert s["plan_distance_km"] == 70.0


# ── streak (forgiving, ≥80%) ─────────────────────────────────────────────

def test_streak_counts_prior_complete_weeks() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    # Weeks 1 & 2 fully done; week 3 (current) only 1/3 → below threshold.
    _build_plan(conn, pid, matched={1: {0, 1, 2}, 2: {0, 1, 2}, 3: {0}})
    s = _week_stats(conn, pid, 3)
    # Current week doesn't qualify yet, but the two prior weeks do.
    assert s["streak_weeks"] == 2, s["streak_weeks"]


def test_streak_includes_current_once_complete() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    _build_plan(conn, pid, matched={1: {0, 1, 2}, 2: {0, 1, 2}, 3: {0, 1, 2}})
    s = _week_stats(conn, pid, 3)
    assert s["streak_weeks"] == 3, s["streak_weeks"]


def test_streak_breaks_on_sub_threshold_week() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    # Week 1 perfect, but week 2 only 1/3 (33% < 80%) breaks the chain that
    # ends at the current week — even though week 3 itself is complete.
    _build_plan(conn, pid, matched={1: {0, 1, 2}, 2: {0}, 3: {0, 1, 2}})
    s = _week_stats(conn, pid, 3)
    # Current week qualifies (1), but the walk back stops at week 2.
    assert s["streak_weeks"] == 1, s["streak_weeks"]


def test_streak_forgives_two_thirds_is_below_80() -> None:
    conn = _fresh_conn()
    pid = _make_plan(conn)
    # 2/3 = 67% is under the 80% bar, so it does NOT keep the streak alive.
    _build_plan(conn, pid, matched={1: {0, 1, 2}, 2: {0, 1}, 3: {0, 1, 2}})
    s = _week_stats(conn, pid, 3)
    assert s["streak_weeks"] == 1, s["streak_weeks"]


TESTS = [
    test_current_plan_week_finds_today,
    test_current_plan_week_none_outside,
    test_incomplete_week_counts,
    test_complete_week_flag,
    test_week_distance_time_load_sums,
    test_plan_distance_cumulative,
    test_streak_counts_prior_complete_weeks,
    test_streak_includes_current_once_complete,
    test_streak_breaks_on_sub_threshold_week,
    test_streak_forgives_two_thirds_is_below_80,
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
