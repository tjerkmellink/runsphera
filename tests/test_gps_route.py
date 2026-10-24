"""Tests for the run-detail route map's data layer (gps_route.py).

Contracts under test: polyline normalization (null-coordinate filtering,
relative-seconds timestamps, the two-point minimum), and the hydrate_route
gating ladder — cached row wins, negative cache never re-fetches,
hasPolyline=False never even calls Garmin, API errors don't poison the
cache, and unauthenticated opens leave the row absent so a later signed-in
open can still fetch.

Run from repo root:
    .venv/Scripts/python.exe tests/test_gps_route.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from running_coach import gps_route  # noqa: E402
from running_coach.db import connect  # noqa: E402


def _fresh_conn():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    return connect(tmp)


def _insert_activity(conn, activity_id: int, has_polyline: bool | None):
    raw: dict = {"activityId": activity_id}
    if has_polyline is not None:
        raw["hasPolyline"] = has_polyline
    conn.execute(
        "INSERT INTO activities (activity_id, activity_type, start_time_local, "
        "start_time_gmt, raw_json) VALUES (?, 'running', '2026-07-19 08:00:00', "
        "'2026-07-19 06:00:00', ?)",
        (activity_id, json.dumps(raw)),
    )
    conn.commit()


class _FakeClient:
    """Stands in for garminconnect.Garmin — records calls, returns a canned
    details payload."""

    def __init__(self, polyline):
        self.polyline = polyline
        self.calls = 0

    def get_activity_details(self, activity_id, maxchart=1, maxpoly=2000):
        self.calls += 1
        return {"geoPolylineDTO": {"polyline": self.polyline}}


def _patch(monkey_client=None, authenticated=True):
    """Point gps_route's Garmin seams at fakes; return the fake client."""
    gps_route.garmin_auth = SimpleNamespace(is_authenticated=lambda: authenticated)
    gps_route.get_client = lambda prompt_mfa=None: monkey_client
    return monkey_client


_POLY = [
    {"lat": 52.5300, "lon": 6.2349, "time": 1_784_466_520_000},
    {"lat": None, "lon": 6.2350, "time": 1_784_466_522_000},  # GPS dropout
    {"lat": 52.5310, "lon": 6.2360, "time": 1_784_466_540_000},
    {"lat": 52.5320, "lon": 6.2370, "time": 1_784_466_580_000},
]


def test_normalize_filters_and_relativizes():
    pts = gps_route.normalize_polyline(_POLY)
    assert len(pts) == 3, f"dropout point should be filtered, got {len(pts)}"
    assert pts[0] == [52.53, 6.2349, 0], f"first point wrong: {pts[0]}"
    assert pts[1][2] == 20, f"relative seconds wrong: {pts[1]}"
    assert pts[2][2] == 60, f"relative seconds wrong: {pts[2]}"


def test_normalize_single_point_is_no_route():
    assert gps_route.normalize_polyline(_POLY[:1]) == []
    assert gps_route.normalize_polyline([]) == []


def test_hydrate_fetches_once_then_serves_cache():
    conn = _fresh_conn()
    _insert_activity(conn, 1, has_polyline=True)
    client = _patch(_FakeClient(_POLY))

    route = gps_route.hydrate_route(conn, 1)
    assert route and route["point_count"] == 3, f"expected 3-point route, got {route}"
    assert client.calls == 1

    route2 = gps_route.hydrate_route(conn, 1)
    assert route2 == route
    assert client.calls == 1, "second open must be served from cache"


def test_hydrate_no_polyline_flag_never_calls_garmin():
    conn = _fresh_conn()
    _insert_activity(conn, 2, has_polyline=False)
    client = _patch(_FakeClient(_POLY))

    assert gps_route.hydrate_route(conn, 2) is None
    assert client.calls == 0, "hasPolyline=False must not hit the API"
    # And the negative cache row exists, so the flag isn't re-parsed either.
    row = conn.execute("SELECT points_json FROM activity_routes WHERE activity_id = 2").fetchone()
    assert row is not None and row["points_json"] is None


def test_hydrate_empty_api_result_negative_caches():
    conn = _fresh_conn()
    _insert_activity(conn, 3, has_polyline=True)  # flag lies; details come back bare
    client = _patch(_FakeClient([]))

    assert gps_route.hydrate_route(conn, 3) is None
    assert client.calls == 1
    assert gps_route.hydrate_route(conn, 3) is None
    assert client.calls == 1, "empty result must be negative-cached"


def test_hydrate_api_error_leaves_no_row():
    conn = _fresh_conn()
    _insert_activity(conn, 4, has_polyline=True)

    class _Boom:
        def get_activity_details(self, *a, **kw):
            raise RuntimeError("garmin down")

    _patch(_Boom())
    assert gps_route.hydrate_route(conn, 4) is None
    row = conn.execute("SELECT 1 FROM activity_routes WHERE activity_id = 4").fetchone()
    assert row is None, "API error must not poison the cache"

    # Garmin comes back → next open succeeds.
    client = _patch(_FakeClient(_POLY))
    route = gps_route.hydrate_route(conn, 4)
    assert route and route["point_count"] == 3


def test_hydrate_unauthenticated_defers():
    conn = _fresh_conn()
    _insert_activity(conn, 5, has_polyline=True)
    client = _patch(_FakeClient(_POLY), authenticated=False)

    assert gps_route.hydrate_route(conn, 5) is None
    assert client.calls == 0
    row = conn.execute("SELECT 1 FROM activity_routes WHERE activity_id = 5").fetchone()
    assert row is None, "signed-out open must not negative-cache"


TESTS = [
    test_normalize_filters_and_relativizes,
    test_normalize_single_point_is_no_route,
    test_hydrate_fetches_once_then_serves_cache,
    test_hydrate_no_polyline_flag_never_calls_garmin,
    test_hydrate_empty_api_result_negative_caches,
    test_hydrate_api_error_leaves_no_row,
    test_hydrate_unauthenticated_defers,
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
