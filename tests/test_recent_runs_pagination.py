"""Tests for the dashboard recent-runs pager (2026-07-26).

Covers analytics.recent_runs(offset=...) + analytics.count_runs(), which back
the "Newer / Older" pager on the dashboard (10 per page, up to 5 pages / 50
runs). Builds a synthetic set of running activities in a fresh DB so the
ordering + offset windows are explicit.

Run from repo root:
    .venv/Scripts/python.exe tests/test_recent_runs_pagination.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach import analytics  # noqa: E402
from running_coach.db import connect  # noqa: E402


def _fresh_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return connect(tmp)


def _seed_runs(conn, count: int) -> None:
    """Insert `count` running activities, oldest first. activity_id N is the
    Nth run; higher id == more recent (start times march forward), so DESC by
    start_time_gmt yields id count..1."""
    for i in range(1, count + 1):
        # Zero-padded day keeps GMT strings lexically sortable == chronological.
        stamp = f"2026-01-{i:02d}T06:00:00"
        conn.execute(
            """INSERT INTO activities
                   (activity_id, activity_name, activity_type,
                    start_time_local, start_time_gmt, distance_m, duration_s,
                    raw_json)
               VALUES (?, ?, 'running', ?, ?, ?, ?, '{}')""",
            (i, f"Run {i}", stamp, stamp, 10000, 3000),
        )
    conn.commit()


def test_count_runs_ignores_non_running():
    conn = _fresh_conn()
    _seed_runs(conn, 12)
    conn.execute(
        """INSERT INTO activities
               (activity_id, activity_name, activity_type,
                start_time_local, start_time_gmt, distance_m, duration_s,
                raw_json)
           VALUES (999, 'Yoga', 'yoga', '2026-02-01T06:00:00',
                   '2026-02-01T06:00:00', 0, 1800, '{}')""",
    )
    conn.commit()
    assert analytics.count_runs(conn) == 12, analytics.count_runs(conn)


def test_first_page_is_newest_ten():
    conn = _fresh_conn()
    _seed_runs(conn, 25)
    page1 = analytics.recent_runs(conn, n=10, offset=0)
    ids = [r["activity_id"] for r in page1]
    # Newest first: ids 25..16.
    assert ids == list(range(25, 15, -1)), ids


def test_offset_walks_back_without_overlap():
    conn = _fresh_conn()
    _seed_runs(conn, 25)
    page1 = {r["activity_id"] for r in analytics.recent_runs(conn, n=10, offset=0)}
    page2 = {r["activity_id"] for r in analytics.recent_runs(conn, n=10, offset=10)}
    assert not (page1 & page2), page1 & page2
    page2_ids = [r["activity_id"] for r in analytics.recent_runs(conn, n=10, offset=10)]
    assert page2_ids == list(range(15, 5, -1)), page2_ids


def test_last_partial_page():
    conn = _fresh_conn()
    _seed_runs(conn, 25)
    page3 = analytics.recent_runs(conn, n=10, offset=20)
    ids = [r["activity_id"] for r in page3]
    assert ids == [5, 4, 3, 2, 1], ids


def test_offset_beyond_data_is_empty():
    conn = _fresh_conn()
    _seed_runs(conn, 12)
    assert analytics.recent_runs(conn, n=10, offset=20) == []


TESTS = [
    test_count_runs_ignores_non_running,
    test_first_page_is_newest_ten,
    test_offset_walks_back_without_overlap,
    test_last_partial_page,
    test_offset_beyond_data_is_empty,
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
