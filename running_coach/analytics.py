"""Read-only queries on the running coach DB. Returns plain dicts/lists for templates."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any


def current_state(conn: sqlite3.Connection) -> dict[str, Any]:
    """Most recent training status and most recent readiness reading."""
    ts = conn.execute(
        "SELECT * FROM training_status ORDER BY calendar_date DESC LIMIT 1"
    ).fetchone()
    rdy = conn.execute(
        "SELECT * FROM training_readiness ORDER BY timestamp DESC LIMIT 1"
    ).fetchone()
    last_run = conn.execute(
        "SELECT * FROM ingestion_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "training_status": dict(ts) if ts else None,
        "latest_readiness": dict(rdy) if rdy else None,
        "last_ingest": dict(last_run) if last_run else None,
    }


def weekly_mileage(conn: sqlite3.Connection, weeks: int = 12) -> list[dict[str, Any]]:
    """Running km per ISO week, oldest first. Includes zero-volume weeks."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    out: list[dict[str, Any]] = []
    for i in range(weeks - 1, -1, -1):
        week_start = monday - timedelta(weeks=i)
        week_end = week_start + timedelta(days=7)
        row = conn.execute(
            """SELECT
                   COALESCE(SUM(distance_m), 0) AS dist_m,
                   COALESCE(SUM(duration_s), 0) AS dur_s,
                   COUNT(*) AS n_runs
               FROM activities
               WHERE activity_type = 'running'
                 AND date(start_time_local) >= ?
                 AND date(start_time_local) <  ?""",
            (week_start.isoformat(), week_end.isoformat()),
        ).fetchone()
        out.append({
            "week_start": week_start.isoformat(),
            "km": (row["dist_m"] or 0) / 1000.0,
            "runs": row["n_runs"],
            "duration_min": (row["dur_s"] or 0) / 60.0,
        })
    return out


def acute_load_series(conn: sqlite3.Connection, days: int = 28) -> list[dict[str, Any]]:
    """Daily acute / chronic training load over the last N days, plus the
    "optimal range" band Garmin uses on its training-load chart.

    Both `daily_load_acute` and `daily_load_chronic` are written by Garmin
    onto `training_status` once per sync, so we just slice the most recent
    N days here — no rolling math needed locally.

    Optimal range bounds: chronic × 0.8 (lower) and chronic × 1.5 (upper).
    These match Garmin's ACWR-status thresholds observed in the data:
    LOW below ~0.8, OPTIMAL within ~0.8-1.5, HIGH above ~1.5.
    """
    rows = conn.execute(
        """SELECT calendar_date, daily_load_acute, daily_load_chronic
           FROM training_status
           WHERE calendar_date >= date('now', ?)
             AND daily_load_acute IS NOT NULL
           ORDER BY calendar_date""",
        (f"-{days} days",),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        acute = float(r["daily_load_acute"] or 0)
        chronic = float(r["daily_load_chronic"] or 0)
        out.append({
            "date":     r["calendar_date"],
            "acute":    acute,
            "chronic":  chronic,
            "low_band":  chronic * 0.8,
            "high_band": chronic * 1.5,
        })
    return out


def hr_zone_totals(conn: sqlite3.Connection, days: int = 7) -> dict[str, float]:
    """Total seconds in each HR zone across runs in the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    row = conn.execute(
        """SELECT
               COALESCE(SUM(hr_zone_1_s), 0) AS z1,
               COALESCE(SUM(hr_zone_2_s), 0) AS z2,
               COALESCE(SUM(hr_zone_3_s), 0) AS z3,
               COALESCE(SUM(hr_zone_4_s), 0) AS z4,
               COALESCE(SUM(hr_zone_5_s), 0) AS z5
           FROM activities
           WHERE activity_type = 'running'
             AND date(start_time_local) >= ?""",
        (since,),
    ).fetchone()
    return {f"z{i}": float(row[f"z{i}"] or 0) for i in range(1, 6)}


def recent_runs(
    conn: sqlite3.Connection, n: int = 10, offset: int = 0
) -> list[dict[str, Any]]:
    # Left-join the matched planned workout (when one exists) so the
    # dashboard's recent-runs table can color each row by intent —
    # easy / tempo / intervals / long / race / rest. NULL workout_type
    # means the run wasn't tied to a plan (manual / unscheduled).
    # `offset` powers the dashboard pager (page 2 → offset 10, etc.).
    rows = conn.execute(
        """SELECT a.activity_id, a.activity_name, a.start_time_local,
                  a.distance_m, a.duration_s, a.avg_hr, a.training_load,
                  pw.workout_type
           FROM activities a
           LEFT JOIN plan_workouts pw ON pw.actual_activity_id = a.activity_id
           WHERE a.activity_type = 'running'
           ORDER BY a.start_time_gmt DESC
           LIMIT ? OFFSET ?""",
        (n, offset),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        km = (r["distance_m"] or 0) / 1000.0
        dur_s = r["duration_s"] or 0
        pace = (dur_s / 60.0) / km if km > 0 else None
        out.append({
            "activity_id": r["activity_id"],
            "name": r["activity_name"],
            "date": r["start_time_local"][:10],
            "km": km,
            "duration_s": dur_s,
            "pace": fmt_pace(pace) if pace else "—",
            "avg_hr": r["avg_hr"],
            "training_load": r["training_load"],
            "workout_type": r["workout_type"],
        })
    return out


def count_runs(conn: sqlite3.Connection) -> int:
    """Total running activities — lets the dashboard pager know when to
    stop offering an "older" page."""
    return conn.execute(
        "SELECT COUNT(*) FROM activities WHERE activity_type = 'running'"
    ).fetchone()[0]


def run_detail(conn: sqlite3.Connection, activity_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM activities WHERE activity_id = ?", (activity_id,)
    ).fetchone()
    if not row:
        return None
    r = dict(row)
    r.pop("raw_json", None)

    km = (r["distance_m"] or 0) / 1000.0
    dur_s = r["duration_s"] or 0
    pace = (dur_s / 60.0) / km if km > 0 else None
    r["km"] = km
    r["duration_s"] = dur_s
    r["pace"] = fmt_pace(pace) if pace else "—"

    total_z = sum((r.get(f"hr_zone_{i}_s") or 0) for i in range(1, 6))
    zone_labels = {1: "Z1 Recovery", 2: "Z2 Easy", 3: "Z3 Aerobic", 4: "Z4 Threshold", 5: "Z5 VO₂"}
    zone_colors = {1: "#9fd9b0", 2: "#7ec8e3", 3: "#f6c95b", 4: "#f08f54", 5: "#d6534d"}
    zones = []
    for i in range(1, 6):
        secs = r.get(f"hr_zone_{i}_s") or 0
        zones.append({
            "n": i,
            "label": zone_labels[i],
            "color": zone_colors[i],
            "seconds": secs,
            "pct": (secs / total_z * 100) if total_z else 0,
        })
    r["hr_zones"] = zones
    r["has_hr_zones"] = total_z > 0

    splits = []
    for label, key in [
        ("1 km", "fastest_1k_s"),
        ("1 mile", "fastest_mile_s"),
        ("5 km", "fastest_5k_s"),
        ("10 km", "fastest_10k_s"),
        ("Half marathon", "fastest_half_s"),
    ]:
        v = r.get(key)
        if v:
            splits.append({"label": label, "time": fmt_duration(v)})
    r["fastest_splits"] = splits

    # Per-lap pace chart + phase summary. `laps` is the raw bar data; `lap_chart`
    # is the pre-computed render-ready shape (height ratios, target-line position)
    # so the template stays declarative.
    from . import laps as laps_module
    raw_laps = laps_module.get_laps(conn, activity_id)
    r["laps"] = raw_laps
    r["segments"] = laps_module.group_segments(raw_laps) if raw_laps else []
    r["active_block"] = laps_module.active_block_summary(conn, activity_id)
    # Matched plan workout — drives the modal's "vs prescription" callout
    # (target pace, target distance) and the kicker label ("RUN DEBRIEF · TEMPO").
    r["matched_workout"] = _matched_plan_workout(conn, activity_id)
    target_pace_s = (
        r["matched_workout"]["target_pace_s_per_km"]
        if r["matched_workout"] else None
    )
    r["lap_chart"] = _build_lap_chart(raw_laps, target_pace_s)

    # Prescription verdict — the compact chip that replaced the old
    # active-block callout card in the modal's v2 layout.
    r["verdict"] = _verdict(r["active_block"], target_pace_s)

    # Finish clock time for the Replay map footer (start + duration).
    r["finish_time"] = None
    if r.get("start_time_local") and dur_s:
        try:
            started = datetime.strptime(r["start_time_local"][:19], "%Y-%m-%d %H:%M:%S")
            r["finish_time"] = (started + timedelta(seconds=int(dur_s))).strftime("%H:%M")
        except ValueError:
            pass

    # VO₂max movement vs the previous run that carried a reading. Compared
    # on the rounded display values so 48.9 → 49.1 doesn't read as "+0".
    r["vo2max_delta"] = None
    if r.get("vo2max"):
        prev = conn.execute(
            "SELECT vo2max FROM activities "
            "WHERE activity_type = 'running' AND vo2max IS NOT NULL "
            "  AND start_time_gmt < ? "
            "ORDER BY start_time_gmt DESC LIMIT 1",
            (r["start_time_gmt"],),
        ).fetchone()
        if prev:
            r["vo2max_delta"] = int(round(r["vo2max"]) - round(prev["vo2max"]))

    r["te_label"] = _te_label(r.get("aerobic_te"))

    return r


# Garmin's standard aerobic training-effect bands.
_TE_BANDS = [
    (1.0, "No benefit"),
    (2.0, "Minor benefit"),
    (3.0, "Maintaining"),
    (4.0, "Improving"),
    (5.0, "Highly improving"),
]


def _te_label(te: float | None) -> str | None:
    if te is None:
        return None
    for upper, label in _TE_BANDS:
        if te < upper:
            return label
    return "Overreaching"


def _verdict(
    active_block: dict[str, Any] | None,
    target_pace_s: int | None,
) -> dict[str, Any] | None:
    """Active-block pace vs prescription, as chip-ready data.

    `delta` is signed seconds/km (positive = slower than target); `good`
    follows the house rule that up to 5 s/km over is still "inside the
    window". None when the run was unstructured or targetless.
    """
    if not active_block or not target_pace_s:
        return None
    pace = active_block.get("avg_pace_s_per_km")
    if not pace:
        return None
    delta = pace - target_pace_s
    return {"delta": delta, "good": delta <= 5}


def run_verdict(conn: sqlite3.Connection, activity_id: int) -> dict[str, Any] | None:
    """Standalone verdict lookup for routes that don't build the full
    run_detail dict (the coach-reaction lazy/refresh endpoints — the chip
    renders inside the reaction's attribution row, so every partial that
    re-renders it needs the verdict too)."""
    from . import laps as laps_module
    ab = laps_module.active_block_summary(conn, activity_id)
    mw = _matched_plan_workout(conn, activity_id)
    return _verdict(ab, mw["target_pace_s_per_km"] if mw else None)


def _matched_plan_workout(
    conn: sqlite3.Connection,
    activity_id: int,
) -> dict[str, Any] | None:
    """Fields we need from the matched plan workout in one query — keeps
    run_detail's downstream callers from refetching."""
    row = conn.execute(
        "SELECT workout_type, title, description, target_distance_km, "
        "       target_pace_s_per_km, target_duration_s "
        "FROM plan_workouts WHERE actual_activity_id = ? LIMIT 1",
        (activity_id,),
    ).fetchone()
    return dict(row) if row else None


_INTENSITY_COLORS = {
    "WARMUP":   "#7ec8e3",
    "ACTIVE":   "#f08f54",
    "COOLDOWN": "#9fd9b0",
    "RECOVERY": "#cbd5e1",
    "INTERVAL": "#f08f54",
    "REST":     "#cbd5e1",
}


def _build_lap_chart(
    laps: list[dict[str, Any]],
    target_pace_s: int | None,
) -> dict[str, Any] | None:
    """Render-ready data for the lap-pace chart.

    Each lap becomes a bar with:
      - `flex` (proportional to distance) so the strip x-axis is distance-based
      - `pace_pct` (0–100) — bar height; faster = shorter bar so a tempo dip
        looks like a U-shape, matching every running app's pace chart convention
      - `color` from intensity_type
      - `tooltip` for hover.

    Returns None when there are no laps (older runs that pre-date lap ingest).
    """
    if not laps:
        return None
    paces = [l["pace_s_per_km"] for l in laps if l.get("pace_s_per_km")]
    if not paces:
        return None
    # Floor + ceiling for the y-axis. Pad 5% on each end so bars never touch
    # the chart edge (and target line stays visible when at the extreme).
    p_min = min(paces)
    p_max = max(paces)
    span = max(p_max - p_min, 1)
    floor_s = p_min - span * 0.05
    ceil_s  = p_max + span * 0.05
    # If a target pace is set and falls outside the run's range, widen the
    # axis so the dashed line is still on-screen.
    if target_pace_s:
        floor_s = min(floor_s, target_pace_s - span * 0.1)
        ceil_s  = max(ceil_s,  target_pace_s + span * 0.1)
    chart_span = ceil_s - floor_s

    bars = []
    for lap in laps:
        p = lap.get("pace_s_per_km")
        # Bar height: faster lap = TALLER bar. We map (slowest..fastest) to
        # (0..100%), so the active block of a tempo workout towers above the
        # short warmup/cooldown bars — the silhouette every running app uses
        # ("spike in the middle"), and aligns with the intuition that taller
        # bar = stronger effort.
        height_pct = ((ceil_s - p) / chart_span * 100) if p else 0
        itype = (lap.get("intensity_type") or "ACTIVE").upper()
        pace_str = f"{p // 60}:{p % 60:02d}/km" if p else "—"
        bars.append({
            "lap_index":    lap["lap_index"],
            "distance_m":   lap.get("distance_m") or 0,
            "pace_str":     pace_str,
            "intensity":    itype,
            "color":        _INTENSITY_COLORS.get(itype, "#94a3b8"),
            "height_pct":   round(height_pct, 1),
            "flex":         max(int(lap.get("distance_m") or 0), 1),
            "avg_hr":       lap.get("avg_hr"),
            "tooltip":      _lap_tooltip(lap, pace_str),
        })

    target_pct = None
    if target_pace_s:
        target_pct = round((ceil_s - target_pace_s) / chart_span * 100, 1)

    return {
        "bars":         bars,
        "top_pace":     _fmt_pace_secs(int(floor_s)),  # fastest at TOP of axis
        "bottom_pace":  _fmt_pace_secs(int(ceil_s)),   # slowest at BOTTOM
        "target_pace_s": target_pace_s,
        "target_pct":   target_pct,
        "target_str":   _fmt_pace_secs(target_pace_s) if target_pace_s else None,
    }


def _lap_tooltip(lap: dict, pace_str: str) -> str:
    d_km = (lap.get("distance_m") or 0) / 1000.0
    bits = [f"Lap {lap['lap_index']}", f"{d_km:.2f} km", pace_str]
    if lap.get("avg_hr"):
        bits.append(f"HR {int(lap['avg_hr'])}")
    if lap.get("intensity_type") and lap["intensity_type"] != "ACTIVE":
        bits.append(lap["intensity_type"].lower())
    return " · ".join(bits)


def _fmt_pace_secs(s: int | None) -> str | None:
    if s is None:
        return None
    return f"{s // 60}:{s % 60:02d}/km"


def fmt_pace(min_per_km: float) -> str:
    mins = int(min_per_km)
    secs = int(round((min_per_km - mins) * 60))
    if secs == 60:
        mins += 1
        secs = 0
    return f"{mins}:{secs:02d}/km"


def fmt_duration(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_pace_s(secs_per_km: int | None) -> str:
    """e.g. 318 -> '5:18/km'. None -> '—'."""
    if not secs_per_km:
        return "—"
    m, s = divmod(int(secs_per_km), 60)
    return f"{m}:{s:02d}/km"


# ── Locale-aware date/time labels ────────────────────────────────────
# Hand-rolled tables (rather than CPython's locale module, which depends
# on the host OS having the locale installed and isn't reliable across
# Windows / Linux / macOS dev machines). Adding a language: extend each
# of these dicts + the date-format strings below.

_DAY_LABELS_LONG = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "nl": ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"],
}
_DAY_LABELS_SHORT = {
    "en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
    "nl": ["ma",  "di",  "wo",  "do",  "vr",  "za",  "zo"],
}
_MONTH_LABELS_LONG = {
    "en": ["January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"],
    "nl": ["januari", "februari", "maart", "april", "mei", "juni",
           "juli", "augustus", "september", "oktober", "november", "december"],
}
_MONTH_LABELS_SHORT = {
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    "nl": ["jan", "feb", "mrt", "apr", "mei", "jun",
           "jul", "aug", "sep", "okt", "nov", "dec"],
}


def fmt_date_long(iso: str, locale: str = "en") -> str:
    """Full long-form date for headlines + countdowns.

      en: '2026-08-23' -> 'Sun 23 Aug 2026'  (short day + short month)
      nl: '2026-08-23' -> 'zondag 23 augustus 2026'  (full day + full month)

    Returns the input verbatim on parse failure so a render never crashes.
    """
    from datetime import date as _date
    try:
        d = _date.fromisoformat(iso[:10])
    except Exception:  # noqa: BLE001
        return iso
    if locale == "nl":
        day  = _DAY_LABELS_LONG["nl"][d.weekday()]
        mon  = _MONTH_LABELS_LONG["nl"][d.month - 1]
        return f"{day} {d.day} {mon} {d.year}"
    # English (default) — kept identical to the previous behavior.
    day = _DAY_LABELS_SHORT["en"][d.weekday()]
    mon = _MONTH_LABELS_SHORT["en"][d.month - 1]
    return f"{day} {d.day:02d} {mon} {d.year}"


def fmt_dow_short(iso: str, locale: str = "en") -> str:
    """Short day-of-week label from an ISO date.

      en: '2026-08-23' -> 'Sun'
      nl: '2026-08-23' -> 'zo'

    Replaces the brittle `fmt_date_long(iso)[:3]` slice that used to
    work only for the English "Sun 23 Aug 2026" shape.
    """
    from datetime import date as _date
    try:
        d = _date.fromisoformat(iso[:10])
    except Exception:  # noqa: BLE001
        return ""
    table = _DAY_LABELS_SHORT.get(locale) or _DAY_LABELS_SHORT["en"]
    return table[d.weekday()]


def fmt_month_short(iso: str, locale: str = "en") -> str:
    """Short month label from an ISO date.

      en: '2026-08-23' -> 'Aug'
      nl: '2026-08-23' -> 'aug'
    """
    from datetime import date as _date
    try:
        d = _date.fromisoformat(iso[:10])
    except Exception:  # noqa: BLE001
        return ""
    table = _MONTH_LABELS_SHORT.get(locale) or _MONTH_LABELS_SHORT["en"]
    return table[d.month - 1]


def fmt_date_short(iso: str, locale: str = "en") -> str:
    """Compact date form for table cells + tight UI slots.

      en: '2026-06-04' -> '2026-06-04'  (ISO — already compact)
      nl: '2026-06-04' -> '04-06-2026'  (DD-MM-YYYY, Dutch convention)
    """
    from datetime import date as _date
    try:
        d = _date.fromisoformat(iso[:10])
    except Exception:  # noqa: BLE001
        return iso
    if locale == "nl":
        return f"{d.day:02d}-{d.month:02d}-{d.year}"
    return d.isoformat()


def fmt_date_range(start_iso: str, end_iso: str, locale: str = "en") -> str:
    """Mon-Sun range label used by the weekly recap. Day name + day +
    month for both ends; year shown only on the end:

      en: 'Mon 25 May – Sun 31 May 2026'
      nl: 'maandag 25 mei – zondag 31 mei 2026'
    """
    from datetime import date as _date
    try:
        a = _date.fromisoformat(start_iso[:10])
        b = _date.fromisoformat(end_iso[:10])
    except Exception:  # noqa: BLE001
        return f"{start_iso} – {end_iso}"
    if locale == "nl":
        dn = _DAY_LABELS_LONG["nl"]
        mn = _MONTH_LABELS_LONG["nl"]
        return f"{dn[a.weekday()]} {a.day} {mn[a.month - 1]} – {dn[b.weekday()]} {b.day} {mn[b.month - 1]} {b.year}"
    ds = _DAY_LABELS_SHORT["en"]
    ms = _MONTH_LABELS_SHORT["en"]
    return f"{ds[a.weekday()]} {a.day:02d} {ms[a.month - 1]} – {ds[b.weekday()]} {b.day:02d} {ms[b.month - 1]} {b.year}"


def fmt_local_dt(iso: str | None, fmt: str | None = None, locale: str = "en") -> str:
    """Render a SQLite-produced UTC timestamp as server-local time.

    SQLite's `datetime('now')` returns a UTC string ('YYYY-MM-DD HH:MM:SS')
    without timezone info. Rendering it raw shows UTC, which for a runner
    in Amsterdam (UTC+2 in summer) means a 22:19 sync displays as 20:19.
    This helper parses the naive string, attaches UTC, converts to the
    local zone, and formats.

    Default format follows the locale's convention:
      en → '2026-06-07 14:30' (ISO date)
      nl → '07-06-2026 14:30' (DD-MM-YYYY)
    Pass an explicit `fmt` to override (e.g. `fmt="%H:%M"` for a bare clock).
    Returns the input on parse failure so we never crash a render.
    """
    if not iso:
        return ""
    from datetime import datetime as _dt, timezone as _tz
    try:
        # SQLite uses space; ISO uses T. fromisoformat handles both since 3.11.
        dt = _dt.fromisoformat(iso.replace(" ", "T", 1))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_tz.utc)
        local_dt = dt.astimezone()
    except Exception:  # noqa: BLE001
        return iso
    if fmt is not None:
        return local_dt.strftime(fmt)
    # No explicit format → use the locale's default
    if locale == "nl":
        return local_dt.strftime("%d-%m-%Y %H:%M")
    return local_dt.strftime("%Y-%m-%d %H:%M")


def day_label(dow: int, locale: str = "en") -> str:
    """Short weekday label, 0=Monday … 6=Sunday."""
    labels = _DAY_LABELS_SHORT.get(locale) or _DAY_LABELS_SHORT["en"]
    return labels[dow] if 0 <= dow <= 6 else str(dow)
