"""Per-lap analysis for running activities.

Reads the `activity_laps` table populated by the ingest (Garmin's per-km
`lapDTOs`) and produces:

- `get_laps(conn, activity_id)`: raw ordered laps with display-ready pace.
- `group_segments(laps)`: consecutive same-intensity laps merged into
  warmup/active/cooldown/recovery blocks.
- `active_block_summary(conn, activity_id)`: the one number coach feedback
  really cares about — actual pace + HR of the workout's *active* portion,
  ignoring warmup/cooldown drag on the total-run average.

Why this module exists: a structured tempo session is 1.5 km easy + 3 km @ T
pace + 1.5 km easy. The total-run average pace mixes all three, which makes
the runner look slower than they actually executed the tempo block. Judging
adherence requires segmenting the actual splits against the planned
warmup/active/cooldown structure and only comparing target pace to the
active segment's pace. See docs/lap-data.md.
"""
from __future__ import annotations

import sqlite3
from typing import Any


def get_laps(conn: sqlite3.Connection, activity_id: int) -> list[dict[str, Any]]:
    """Return ordered laps for an activity with derived `pace_s_per_km`.

    Empty list when no laps are stored — newly synced runs always have laps
    (the ingest fetches them), but older runs that pre-date the lap-ingest
    feature won't until a backfill or modal-open refetch lands them.
    """
    rows = conn.execute(
        "SELECT * FROM activity_laps WHERE activity_id = ? ORDER BY lap_index",
        (activity_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        lap = dict(r)
        lap.pop("raw_json", None)
        speed = lap.get("avg_speed_mps") or 0
        # Pace is meaningless on zero-speed (paused) laps — surface None so the
        # UI can render a dash instead of an infinity glyph.
        lap["pace_s_per_km"] = int(1000.0 / speed) if speed > 0 else None
        out.append(lap)
    return out


# Intensity values from Garmin's lap data: WARMUP / ACTIVE / COOLDOWN /
# RECOVERY / INTERVAL / REST. We treat anything that isn't an explicit phase
# marker as ACTIVE (free runs come back as all-ACTIVE; the watch only emits
# the other labels when a structured workout drives it).
_INTENSITY_ORDER = ("WARMUP", "ACTIVE", "RECOVERY", "COOLDOWN", "INTERVAL", "REST")


def group_segments(laps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse consecutive same-`intensity_type` laps into one segment dict.

    Each segment carries:
      intensity_type, distance_m, duration_s, avg_pace_s_per_km, avg_hr,
      max_hr, lap_indexes (list[int]).

    For an unstructured run every lap is "ACTIVE" so this returns a single
    segment. For a pushed tempo workout it returns 3 segments
    (WARMUP/ACTIVE/COOLDOWN); for intervals more (WARMUP, ACTIVE/RECOVERY
    pairs, COOLDOWN).
    """
    if not laps:
        return []

    segments: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for lap in laps:
        itype = lap.get("intensity_type") or "ACTIVE"
        if current is None or current["intensity_type"] != itype:
            current = {
                "intensity_type":     itype,
                "distance_m":         0.0,
                "duration_s":         0.0,
                # `hr_seconds` is the duration-weighted-HR accumulator; we
                # divide it out at the end so a 100m walk-cooldown lap doesn't
                # dominate a 1km cooldown lap with the same nominal avg HR.
                "hr_seconds":         0.0,
                "hr_total_duration":  0.0,
                "max_hr":             None,
                "lap_indexes":        [],
            }
            segments.append(current)
        current["distance_m"] += lap.get("distance_m") or 0
        dur = lap.get("duration_s") or 0
        current["duration_s"] += dur
        hr = lap.get("avg_hr")
        if hr is not None and dur:
            current["hr_seconds"] += hr * dur
            current["hr_total_duration"] += dur
        mx = lap.get("max_hr")
        if mx is not None and (current["max_hr"] is None or mx > current["max_hr"]):
            current["max_hr"] = mx
        current["lap_indexes"].append(int(lap["lap_index"]))

    for seg in segments:
        if seg["duration_s"] and seg["distance_m"]:
            seg["avg_pace_s_per_km"] = int(seg["duration_s"] * 1000.0 / seg["distance_m"])
        else:
            seg["avg_pace_s_per_km"] = None
        seg["avg_hr"] = (
            seg["hr_seconds"] / seg["hr_total_duration"]
            if seg["hr_total_duration"] else None
        )
        # Hide the accumulators — callers want the derived avg only.
        seg.pop("hr_seconds", None)
        seg.pop("hr_total_duration", None)
    return segments


def active_block_summary(
    conn: sqlite3.Connection,
    activity_id: int,
) -> dict[str, Any] | None:
    """Return the actual ACTIVE-block stats for a structured workout, or None
    when the activity has no laps / no distinct active phase.

    For a tempo session this gives {distance_m, duration_s, avg_pace_s_per_km,
    avg_hr, max_hr} of just the 3 km tempo portion — the pace the coach
    actually wants to judge against the target. For an unstructured run there
    is no separately-tagged active block (all laps are ACTIVE), so this
    returns None and the caller should fall back to total-run averages.
    """
    laps = get_laps(conn, activity_id)
    if not laps:
        return None
    segments = group_segments(laps)
    if not segments:
        return None
    # If there's exactly one segment and it's ACTIVE, the run was unstructured
    # — no meaningful "active block" to extract.
    if len(segments) == 1 and segments[0]["intensity_type"] == "ACTIVE":
        return None
    # Sum across ACTIVE segments (intervals can have multiple ACTIVE blocks
    # separated by RECOVERY).
    active = [s for s in segments if s["intensity_type"] == "ACTIVE"]
    if not active:
        return None
    total_d = sum(s["distance_m"] for s in active)
    total_t = sum(s["duration_s"] for s in active)
    hr_secs = sum(
        (s["avg_hr"] or 0) * s["duration_s"] for s in active if s.get("avg_hr")
    )
    hr_total_dur = sum(s["duration_s"] for s in active if s.get("avg_hr"))
    max_hr = max((s["max_hr"] for s in active if s.get("max_hr") is not None), default=None)
    return {
        "n_segments":         len(active),
        "distance_m":         total_d,
        "duration_s":         total_t,
        "avg_pace_s_per_km":  int(total_t * 1000.0 / total_d) if total_d and total_t else None,
        "avg_hr":             hr_secs / hr_total_dur if hr_total_dur else None,
        "max_hr":             max_hr,
    }
