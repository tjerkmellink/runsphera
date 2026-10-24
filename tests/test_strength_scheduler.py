"""Tests for the strength-session rotation scheduler.

The scheduler walks a plan's future workouts and stamps one canonical
strength session onto each rest day. Two behaviors worth guarding:

1. **Rotation**: cycles through `library.ROTATION_SLUGS` in order across
   consecutive rest days that don't follow quality.
2. **Recovery override**: a rest day that follows tempo / intervals /
   long / race gets ``recovery_mobility`` instead of the next rotation
   slot — that's the "easy after hard" coaching rule.

Tests use an in-memory SQLite via `connect()` against a `:memory:` path
override so they don't touch the real DB.

Run with:
    .venv/Scripts/python.exe tests/test_strength_scheduler.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _fresh_db():
    """Spin up a fresh SQLite DB in a temp file. Returns (conn, path).
    The path stays around for the duration of the test process so the
    connection stays valid; tempfile.NamedTemporaryFile + delete=False
    so Windows doesn't complain about the open handle.
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["RUNNING_COACH_DB"] = path
    from running_coach.db import connect
    conn = connect()
    return conn, path


def _make_plan(conn, workouts: list[tuple[str, str]]) -> int:
    """Create a plan with a sequence of (planned_date, workout_type)
    workouts. Returns the plan id. Skips the engine; just stamps rows."""
    cur = conn.execute(
        """INSERT INTO plans
           (goal_type, methodology, days_per_week, long_run_day, status, title)
           VALUES ('marathon', 'daniels', 5, 6, 'active', 'test plan')"""
    )
    plan_id = cur.lastrowid
    for i, (d, wtype) in enumerate(workouts):
        conn.execute(
            """INSERT INTO plan_workouts
               (plan_id, week_number, week_phase, day_of_week, planned_date,
                workout_type, title)
               VALUES (?, ?, 'base', ?, ?, ?, ?)""",
            (plan_id, 1 + i // 7, i % 7, d, wtype, f"{wtype} {i}"),
        )
    conn.commit()
    return plan_id


def _assignments(conn, plan_id: int) -> list[tuple[str, str]]:
    """Return [(planned_date, slug), ...] for the plan's assigned sessions."""
    rows = conn.execute(
        """SELECT pss.planned_date, sw.slug
           FROM plan_strength_sessions pss
           JOIN strength_workouts sw ON sw.id = pss.strength_workout_id
           WHERE pss.plan_id = ?
           ORDER BY pss.planned_date""",
        (plan_id,),
    ).fetchall()
    return [(r["planned_date"], r["slug"]) for r in rows]


# ── Tests ─────────────────────────────────────────────────────────

def test_rotation_walks_all_slugs_in_order():
    """Consecutive rest days (no quality preceding) walk through every
    rotation slug in declaration order, then wrap. The rotation has 5
    slugs (everything in LIBRARY except recovery_mobility); this test
    seeds 6 rest days to exercise one full lap + a wrap."""
    from running_coach.strength.library import ROTATION_SLUGS
    n_rotation = len(ROTATION_SLUGS)

    conn, _ = _fresh_db()
    today = date(2030, 1, 6)
    # Day 0 is "easy" so prev_type isn't quality.
    # Days 1..n_rotation+1 are all rest (one full lap + 1 wrap).
    n_rest = n_rotation + 1
    workouts = [(str(today + timedelta(days=i)),
                 "easy" if i == 0 else "rest")
                for i in range(n_rest + 1)]
    plan_id = _make_plan(conn, workouts)

    from running_coach.strength import scheduler
    n = scheduler.assign_for_plan(conn, plan_id, today_iso=str(today))

    assigned = _assignments(conn, plan_id)
    assert n == n_rest and len(assigned) == n_rest, f"expected {n_rest}, got {n} / {assigned}"
    slugs = [s for _, s in assigned]
    # Full lap, then first slug again.
    expected = list(ROTATION_SLUGS) + [ROTATION_SLUGS[0]]
    assert slugs == expected, f"rotation order wrong: {slugs}"


def test_recovery_overrides_after_quality():
    """A rest day immediately after a tempo / intervals / long / race
    becomes recovery_mobility, not the next rotation slot."""
    conn, _ = _fresh_db()
    today = date(2030, 1, 6)
    # Mix: easy, tempo, rest (← should be recovery), rest, intervals, rest, long, rest, easy, rest
    workouts = [
        (str(today + timedelta(days=0)), "easy"),
        (str(today + timedelta(days=1)), "tempo"),
        (str(today + timedelta(days=2)), "rest"),       # → recovery (after tempo)
        (str(today + timedelta(days=3)), "rest"),       # → rotation[0]
        (str(today + timedelta(days=4)), "intervals"),
        (str(today + timedelta(days=5)), "rest"),       # → recovery (after intervals)
        (str(today + timedelta(days=6)), "long"),
        (str(today + timedelta(days=7)), "rest"),       # → recovery (after long)
        (str(today + timedelta(days=8)), "easy"),
        (str(today + timedelta(days=9)), "rest"),       # → rotation[1] (after easy)
    ]
    plan_id = _make_plan(conn, workouts)

    from running_coach.strength import scheduler
    scheduler.assign_for_plan(conn, plan_id, today_iso=str(today))

    by_date = dict(_assignments(conn, plan_id))
    assert by_date[str(today + timedelta(days=2))] == "recovery_mobility"
    assert by_date[str(today + timedelta(days=3))] == "core_hamstrings"
    assert by_date[str(today + timedelta(days=5))] == "recovery_mobility"
    assert by_date[str(today + timedelta(days=7))] == "recovery_mobility"
    assert by_date[str(today + timedelta(days=9))] == "full_body_strength"


def test_re_run_is_idempotent():
    """Running assign twice produces the same result — no duplicates,
    no rotation-offset drift."""
    conn, _ = _fresh_db()
    today = date(2030, 1, 6)
    workouts = [(str(today + timedelta(days=i)),
                 "easy" if i == 0 else "rest") for i in range(4)]
    plan_id = _make_plan(conn, workouts)

    from running_coach.strength import scheduler
    scheduler.assign_for_plan(conn, plan_id, today_iso=str(today))
    first = _assignments(conn, plan_id)

    scheduler.assign_for_plan(conn, plan_id, today_iso=str(today))
    second = _assignments(conn, plan_id)

    assert first == second, f"not idempotent\nfirst:  {first}\nsecond: {second}"


def test_clear_future_keeps_past():
    """Toggling the plan off clears future sessions but leaves past ones
    in place (history). Use a future today_iso to simulate this — anything
    < today_iso is 'past' and should survive."""
    conn, _ = _fresh_db()
    today = date(2030, 1, 6)
    workouts = [(str(today + timedelta(days=i)),
                 "easy" if i == 0 else "rest") for i in range(4)]
    plan_id = _make_plan(conn, workouts)

    from running_coach.strength import scheduler, service
    scheduler.assign_for_plan(conn, plan_id, today_iso=str(today))
    assert len(_assignments(conn, plan_id)) == 3, "seed didn't write 3"

    # Pretend "today" is now day +2. Day +1 is in the past, days +2/+3 are future.
    cutoff = str(today + timedelta(days=2))
    result = service.clear_future_sessions(conn, plan_id, cutoff)
    remaining = _assignments(conn, plan_id)
    assert result["deleted"] == 2, f"expected 2 cleared, got {result}"
    assert len(remaining) == 1, f"past should survive, got {remaining}"
    assert remaining[0][0] == str(today + timedelta(days=1)), remaining


class _DeleteFails:
    def delete_workout(self, wid):
        raise RuntimeError("garmin 503")


class _DeleteOk:
    def __init__(self):
        self.deleted = []

    def delete_workout(self, wid):
        self.deleted.append(wid)


def test_clear_future_keeps_a_session_completed_today():
    """`planned_date >= today` used to delete a session finished this morning.

    The docstring promised to keep history; it kept only *yesterday's*.
    """
    conn, _ = _fresh_db()
    today = date(2030, 1, 6)
    workouts = [(str(today + timedelta(days=i)),
                 "easy" if i == 0 else "rest") for i in range(4)]
    plan_id = _make_plan(conn, workouts)

    from running_coach.strength import scheduler, service
    scheduler.assign_for_plan(conn, plan_id, today_iso=str(today))
    # Complete the session scheduled for the cutoff day itself.
    cutoff = str(today + timedelta(days=2))
    conn.execute(
        "UPDATE plan_strength_sessions SET completed_at = datetime('now') "
        "WHERE plan_id = ? AND planned_date = ?",
        (plan_id, cutoff),
    )
    conn.commit()

    result = service.clear_future_sessions(conn, plan_id, cutoff)

    assert result["kept_completed"] == 1, result
    survivors = [d for d, _ in _assignments(conn, plan_id)]
    assert cutoff in survivors, "deleted a session completed today"


def test_clear_future_keeps_pushed_sessions_garmin_refuses():
    """Deleting the row would strand the workout on the watch forever."""
    conn, _ = _fresh_db()
    today = date(2030, 1, 6)
    workouts = [(str(today + timedelta(days=i)),
                 "easy" if i == 0 else "rest") for i in range(4)]
    plan_id = _make_plan(conn, workouts)

    from running_coach.strength import scheduler, service
    scheduler.assign_for_plan(conn, plan_id, today_iso=str(today))
    cutoff = str(today + timedelta(days=2))
    conn.execute(
        "UPDATE plan_strength_sessions SET garmin_workout_id = 555 "
        "WHERE plan_id = ? AND planned_date = ?",
        (plan_id, cutoff),
    )
    conn.commit()

    result = service.clear_future_sessions(conn, plan_id, cutoff, client=_DeleteFails())

    assert result["kept_pushed"] == 1, result
    survivors = [d for d, _ in _assignments(conn, plan_id)]
    assert cutoff in survivors, "stranded a pushed session on the watch"


def test_clear_future_releases_pushed_sessions_then_deletes():
    conn, _ = _fresh_db()
    today = date(2030, 1, 6)
    workouts = [(str(today + timedelta(days=i)),
                 "easy" if i == 0 else "rest") for i in range(4)]
    plan_id = _make_plan(conn, workouts)

    from running_coach.strength import scheduler, service
    scheduler.assign_for_plan(conn, plan_id, today_iso=str(today))
    cutoff = str(today + timedelta(days=2))
    conn.execute(
        "UPDATE plan_strength_sessions SET garmin_workout_id = 555 "
        "WHERE plan_id = ? AND planned_date = ?",
        (plan_id, cutoff),
    )
    conn.commit()
    client = _DeleteOk()

    result = service.clear_future_sessions(conn, plan_id, cutoff, client=client)

    assert client.deleted == [555], "Garmin copy was not released"
    assert result["deleted"] == 2 and result["kept_pushed"] == 0, result


def test_clear_future_without_a_client_keeps_pushed_rows():
    """No auth means nothing was removed from Garmin."""
    conn, _ = _fresh_db()
    today = date(2030, 1, 6)
    workouts = [(str(today + timedelta(days=i)),
                 "easy" if i == 0 else "rest") for i in range(4)]
    plan_id = _make_plan(conn, workouts)

    from running_coach.strength import scheduler, service
    scheduler.assign_for_plan(conn, plan_id, today_iso=str(today))
    cutoff = str(today + timedelta(days=2))
    conn.execute(
        "UPDATE plan_strength_sessions SET garmin_workout_id = 555 "
        "WHERE plan_id = ? AND planned_date = ?",
        (plan_id, cutoff),
    )
    conn.commit()

    result = service.clear_future_sessions(conn, plan_id, cutoff)

    assert result["kept_pushed"] == 1, result


def test_seed_library_idempotent():
    """seed_library_if_empty is a no-op once the table is populated.
    The expected row count tracks `library.LIBRARY` so this test stays
    correct as sessions get added."""
    from running_coach.strength import library, service
    expected = len(library.LIBRARY)

    conn, _ = _fresh_db()
    # First connect already seeded (via db.connect). Verify count.
    n = conn.execute("SELECT COUNT(*) AS c FROM strength_workouts").fetchone()["c"]
    assert n == expected, f"expected {expected} library entries, got {n}"
    inserted = service.seed_library_if_empty(conn)
    assert inserted == 0, f"second call should insert 0, got {inserted}"
    assert conn.execute("SELECT COUNT(*) AS c FROM strength_workouts").fetchone()["c"] == expected


# ──────────────────────────────────────────────────────────────────

TESTS = [
    test_rotation_walks_all_slugs_in_order,
    test_recovery_overrides_after_quality,
    test_re_run_is_idempotent,
    test_clear_future_keeps_past,
    test_clear_future_keeps_a_session_completed_today,
    test_clear_future_keeps_pushed_sessions_garmin_refuses,
    test_clear_future_releases_pushed_sessions_then_deletes,
    test_clear_future_without_a_client_keeps_pushed_rows,
    test_seed_library_idempotent,
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
