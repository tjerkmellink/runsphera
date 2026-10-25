"""GPS route (track polyline) for running activities — the run-detail map.

Garmin's activity *summary* payload never carries the track; coordinates
live behind a second endpoint (`/activity-service/activity/{id}/details`,
`Garmin.get_activity_details`). We fetch that lazily the first time the
runner opens a run's detail modal — mirroring how `_hydrate_garmin_feel`
works — normalise the polyline to compact `[lat, lon, t_rel_s]` triples
and cache it in `activity_routes` forever: a finished run's track never
changes.

Gating (why a treadmill run costs zero API calls):

1. The summary raw_json we already store has a `hasPolyline` flag. False →
   negative-cache immediately, no network.
2. A row with NULL `points_json` means "asked Garmin, nothing came back" —
   also never re-asked.
3. API errors store nothing, so a transient failure retries on the next
   modal open.

See docs/route-map.md.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from . import garmin as garmin_auth
from .garmin import _refuse_mfa, get_client

# Garmin downsamples server-side to at most this many points. ~2000 keeps a
# marathon's shape smooth while the stored JSON stays around 60 KB.
_MAX_POLYLINE_POINTS = 2000
# We don't need the chart metric streams (pace/HR sampling) in Phase 1 —
# request the legal minimum so the details payload stays small.
_MIN_CHART_POINTS = 1


def get_route(conn: sqlite3.Connection, activity_id: int) -> dict[str, Any] | None:
    """Cached route for an activity, or None when absent / negative-cached.

    Returns `{"points_json": str, "point_count": int}` — points_json is the
    ready-to-embed JSON array of [lat, lon, t_rel_s] triples.
    """
    row = conn.execute(
        "SELECT points_json, point_count FROM activity_routes WHERE activity_id = ?",
        (activity_id,),
    ).fetchone()
    if not row or not row["points_json"]:
        return None
    return {"points_json": row["points_json"], "point_count": row["point_count"]}


def _route_checked(conn: sqlite3.Connection, activity_id: int) -> bool:
    """True when a cache row exists at all (positive OR negative)."""
    row = conn.execute(
        "SELECT 1 FROM activity_routes WHERE activity_id = ?", (activity_id,)
    ).fetchone()
    return row is not None


def _has_polyline_flag(conn: sqlite3.Connection, activity_id: int) -> bool:
    """Cheap pre-gate: Garmin's `hasPolyline` from the stored summary JSON.

    Missing flag defaults to True — better one wasted details call than a
    run whose map never shows because an old payload lacked the field.
    """
    row = conn.execute(
        "SELECT raw_json FROM activities WHERE activity_id = ?", (activity_id,)
    ).fetchone()
    if not row:
        return False
    try:
        raw = json.loads(row["raw_json"])
    except (TypeError, ValueError):
        return False
    flag = raw.get("hasPolyline")
    return True if flag is None else bool(flag)


def _store(
    conn: sqlite3.Connection,
    activity_id: int,
    points: list[list[float]] | None,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO activity_routes (activity_id, points_json, point_count) "
        "VALUES (?, ?, ?)",
        (
            activity_id,
            json.dumps(points, separators=(",", ":")) if points else None,
            len(points) if points else 0,
        ),
    )
    conn.commit()


def normalize_polyline(polyline: list[dict[str, Any]]) -> list[list[float]]:
    """Garmin polyline DTOs → compact [lat, lon, t_rel_s] triples.

    - Drops points without coordinates (Garmin marks GPS dropouts null).
    - Coordinates rounded to 6 decimals (~0.1 m) to keep the JSON small.
    - `t_rel_s` is whole seconds since the first kept point — the replay
      animation scales it, so absolute epoch times are dead weight.
    """
    out: list[list[float]] = []
    t0: float | None = None
    for p in polyline:
        lat, lon = p.get("lat"), p.get("lon")
        if lat is None or lon is None:
            continue
        t_ms = p.get("time")
        if t0 is None:
            t0 = t_ms if t_ms is not None else 0
        t_rel = int(round((t_ms - t0) / 1000.0)) if t_ms is not None else 0
        out.append([round(float(lat), 6), round(float(lon), 6), t_rel])
    # A "route" of one point (GPS caught a single fix indoors) renders as
    # nothing useful — treat it as no route.
    return out if len(out) >= 2 else []


def fetch_route(client: Any, activity_id: int) -> list[list[float]]:
    """Pull + normalise the track from Garmin. Raises on API failure."""
    details = client.get_activity_details(
        activity_id, maxchart=_MIN_CHART_POINTS, maxpoly=_MAX_POLYLINE_POINTS
    )
    geo = (details or {}).get("geoPolylineDTO") or {}
    return normalize_polyline(geo.get("polyline") or [])


def hydrate_route(conn: sqlite3.Connection, activity_id: int) -> dict[str, Any] | None:
    """The full lazy flow for the run-detail modal: cache → gate → fetch.

    Never raises — the modal renders fine without a map; an API hiccup just
    means no Route tab this open and a retry on the next one.
    """
    cached = get_route(conn, activity_id)
    if cached:
        return cached
    if _route_checked(conn, activity_id):
        return None  # negative cache: known GPS-less activity
    if not _has_polyline_flag(conn, activity_id):
        _store(conn, activity_id, None)  # summary says no track — never ask
        return None
    if not garmin_auth.is_authenticated():
        return None  # no token: don't negative-cache, retry once signed in
    try:
        points = fetch_route(get_client(prompt_mfa=_refuse_mfa), activity_id)
        _store(conn, activity_id, points or None)
    except Exception:  # noqa: BLE001 — best-effort, same posture as feel/RPE
        return None
    return get_route(conn, activity_id)
