"""Body / wellbeing check-in — interactive body-map module.

The runner taps an interactive front+back body diagram to log how their
body actually feels. Each entry is a structured record: region · side ·
issue type · severity 1-10 · optional anatomical structure name · note.
Active issues persist as a daily-updatable list with a trend curve;
resolved issues feed a history timeline and a trouble-zone heatmap.

The active-issue list IS the source of body state across the app:

- Daily coach prescription softens on any active issue ≥ 5/10.
- LLM coach voice picks up active issues + recent resolved + heatmap
  top zones as ground truth in the cached profile prompt.
- Strength sessions (v1.1) skip exercises that load affected regions.
- Plan re-flex (v1.1) softens on a worsening trend.

No background worker — the 14-day auto-archive runs lazily on every
`active_issues(conn)` read. Matches `vdot_detection` pattern. See
`docs/body-wellbeing-checkin.md` for the full design brief.
"""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any


# ── Canonical region keys (15) ───────────────────────────────────────
# Front: 7 paired (foot, ankle, shin, knee, quad, hip_flexor, shoulder).
# Back:  5 paired (heel, achilles, calf, hamstring, glute) +
#        3 midline (neck, upper_back, lower_back).
# Side is encoded as a property on each issue, not duplicate region keys.

REGIONS: tuple[str, ...] = (
    # Front
    "shoulder",
    "hip_flexor",
    "quad",
    "knee",
    "shin",
    "ankle",
    "foot",
    # Back
    "neck",
    "upper_back",
    "lower_back",
    "glute",
    "hamstring",
    "calf",
    "achilles",
    "heel",
)

MIDLINE_REGIONS: frozenset[str] = frozenset({"neck", "upper_back", "lower_back"})


# ── Issue taxonomy ───────────────────────────────────────────────────
# Six types. `key` is what's stored; `label` is the English display
# string and the i18n lookup key (translation dict resolves at render).

ISSUE_TYPES: tuple[tuple[str, str], ...] = (
    ("soreness",      "Soreness"),
    ("tight",         "Tight / stiff"),
    ("sharp",         "Sharp pain"),
    ("dull_ache",     "Dull ache"),
    ("numb",          "Numb / tingling"),
    ("known_injury",  "Known injury"),
)

ISSUE_TYPE_KEYS: frozenset[str] = frozenset(k for k, _ in ISSUE_TYPES)


# ── Per-region structure-name autocomplete library ────────────────────
# Surfaced as a <datalist> on the entry panel. Runners can also enter
# freeform structures — these are the suggestions, not the closed set.

STRUCTURE_LIBRARY: dict[str, tuple[str, ...]] = {
    "foot":        ("Plantar fascia", "Metatarsals", "Arch", "Big toe", "Forefoot"),
    "heel":        ("Heel pad", "Heel spur", "Calcaneus"),
    "ankle":       ("Peroneal", "Posterior tib", "Anterior compartment", "Deltoid lig", "ATFL"),
    "achilles":    ("Achilles tendon", "Insertion", "Retrocalcaneal bursa"),
    "shin":        ("Tibialis anterior", "Posterior tib", "Bone (stress)"),
    "calf":        ("Gastrocnemius", "Soleus"),
    "knee":        ("IT band", "Patellar tendon", "Meniscus", "MCL", "LCL", "Patella", "Quad tendon"),
    "quad":        ("Rectus femoris", "Vastus medialis", "Vastus lateralis", "Quad tendon"),
    "hamstring":   ("Biceps femoris", "Semitendinosus", "Hamstring origin"),
    "hip_flexor":  ("Iliopsoas", "Rectus femoris", "TFL", "Sartorius"),
    "glute":       ("Glute med", "Glute max", "Piriformis"),
    "lower_back":  ("Lumbar erectors", "SI joint", "QL"),
    "upper_back":  ("Trap", "Rhomboid", "Erectors"),
    "neck":        ("Cervical", "SCM"),
    "shoulder":    ("AC joint", "Rotator cuff", "Deltoid"),
}


# ── Lifecycle constants ───────────────────────────────────────────────
# Tunable; if suggestions feel too eager or too quiet, nudge these.

NUDGE_DAYS = 10            # Show "still bothering you?" on active card
AUTO_ARCHIVE_DAYS = 14     # Auto-close stale issues
CLEAR_SOFT_PROMPT_DAYS = 2 # Severity 0 for N days → "cleared up?" prompt
DAILY_PROMPT_THROTTLE_HOURS = 12


# ── Severity bands ────────────────────────────────────────────────────
# Match the design-system severity palette: 1-3 mild green, 4-6 amber,
# 7-10 red. The 0 band is for "cleared up" issues still on the active
# list awaiting a close prompt.

def severity_band(severity: int) -> str:
    """Return 'cleared' / 'mild' / 'mod' / 'severe' for a severity 0-10."""
    if severity <= 0:
        return "cleared"
    if severity <= 3:
        return "mild"
    if severity <= 6:
        return "mod"
    return "severe"


def severity_band_num(severity: int) -> int:
    """Return 0/1/2/3 for severity bands. Used by CSS hooks like
    `.sev-2`, `.big-sev.s3`, etc. Mirrors the band() helper in
    the design's body-page.js."""
    if severity <= 0:
        return 0
    if severity <= 3:
        return 1
    if severity <= 6:
        return 2
    return 3


def severity_band_label(band: int) -> str:
    """Design's band labels: 1 → MONITOR, 2 → MANAGE, 3 → REST + PHYSIO."""
    return {1: "MONITOR", 2: "MANAGE", 3: "REST + PHYSIO"}.get(band, "")


def side_label(side: str) -> str:
    """DB form 'left' → 'Right' for display (viewer-left = person's Right).

    Note: the canonical convention everywhere is the runner's-perspective
    side. Our DB stores it that way ('left' = runner's left calf). Design
    label-casing flips here only for the eyebrow line. Midline regions
    return empty string (no side prefix)."""
    if side == "midline":
        return ""
    return side.capitalize()


def slug_label(region: str) -> str:
    """Turn 'hip_flexor' into 'Hip flexor' for UI display."""
    return region.replace("_", " ").capitalize()


def design_key(region: str, side: str) -> str:
    """('hip_flexor', 'left') → 'front:hipflexor-L'. Wraps body_svg's helper.

    Available to templates as a Jinja global so they can compose
    data-region="..." attributes that match the design's hooks."""
    from running_coach import body_svg
    return body_svg.to_design_key(region, side)


def region_face(region: str) -> str:
    """'calf' → 'back', 'quad' → 'front'. Wraps body_svg's helper."""
    from running_coach import body_svg
    return body_svg.region_face(region)


# ── Writes ────────────────────────────────────────────────────────────

def record_issue(
    conn: sqlite3.Connection,
    *,
    region: str,
    side: str,
    issue_type: str,
    severity: int,
    structure_name: str | None = None,
    note: str | None = None,
) -> int:
    """Create a new issue + its first severity log entry in one transaction.

    Returns the new issue id. Raises ValueError on unknown region / side
    / issue_type or out-of-range severity (defence-in-depth on top of
    the schema CHECK constraints).
    """
    _validate_region_side(region, side)
    if issue_type not in ISSUE_TYPE_KEYS:
        raise ValueError(f"unknown issue_type: {issue_type!r}")
    if not 1 <= severity <= 10:
        raise ValueError(f"severity must be 1-10 at creation, got {severity}")

    cur = conn.execute(
        """INSERT INTO body_issues
               (region, side, issue_type, structure_name, note)
           VALUES (?, ?, ?, ?, ?)""",
        (region, side, issue_type, structure_name or None, note or None),
    )
    issue_id = cur.lastrowid
    conn.execute(
        "INSERT INTO body_severity_log (issue_id, severity) VALUES (?, ?)",
        (issue_id, severity),
    )
    conn.commit()
    return int(issue_id)


def update_severity(conn: sqlite3.Connection, issue_id: int, severity: int) -> None:
    """Append a new severity reading to the audit log.

    Severity 0 is allowed on updates (triggers the cleared-up soft prompt
    when sustained CLEAR_SOFT_PROMPT_DAYS) but rejected at creation time
    by record_issue.
    """
    if not 0 <= severity <= 10:
        raise ValueError(f"severity must be 0-10, got {severity}")
    conn.execute(
        "INSERT INTO body_severity_log (issue_id, severity) VALUES (?, ?)",
        (issue_id, severity),
    )
    conn.execute(
        "UPDATE body_issues SET updated_at = datetime('now') WHERE id = ?",
        (issue_id,),
    )
    conn.commit()


def update_issue_fields(
    conn: sqlite3.Connection,
    issue_id: int,
    *,
    issue_type: str | None = None,
    structure_name: str | None = None,
    note: str | None = None,
) -> None:
    """Edit the issue's type / structure name / note. Pass None to skip a field."""
    sets: list[str] = []
    params: list[Any] = []
    if issue_type is not None:
        if issue_type not in ISSUE_TYPE_KEYS:
            raise ValueError(f"unknown issue_type: {issue_type!r}")
        sets.append("issue_type = ?")
        params.append(issue_type)
    if structure_name is not None:
        sets.append("structure_name = ?")
        params.append(structure_name.strip() or None)
    if note is not None:
        sets.append("note = ?")
        params.append(note.strip() or None)
    if not sets:
        return
    sets.append("updated_at = datetime('now')")
    params.append(issue_id)
    conn.execute(
        f"UPDATE body_issues SET {', '.join(sets)} WHERE id = ?",
        params,
    )
    conn.commit()


def resolve_issue(
    conn: sqlite3.Connection, issue_id: int, *, reason: str = "manual"
) -> None:
    """Soft-close an issue. `reason` is one of manual / auto_idle / severity_zero."""
    if reason not in ("manual", "auto_idle", "severity_zero"):
        raise ValueError(f"unknown resolve reason: {reason!r}")
    conn.execute(
        """UPDATE body_issues
              SET resolved_at = datetime('now'),
                  resolved_reason = ?,
                  updated_at = datetime('now')
            WHERE id = ? AND resolved_at IS NULL""",
        (reason, issue_id),
    )
    conn.commit()


def unresolve_issue(conn: sqlite3.Connection, issue_id: int) -> None:
    """Reopen a previously resolved issue (manual undo)."""
    conn.execute(
        """UPDATE body_issues
              SET resolved_at = NULL,
                  resolved_reason = NULL,
                  updated_at = datetime('now')
            WHERE id = ?""",
        (issue_id,),
    )
    conn.commit()


def record_clear(conn: sqlite3.Connection) -> None:
    """Log an 'I'm all good right now' timestamp."""
    conn.execute("INSERT INTO body_clear_logs DEFAULT VALUES")
    conn.commit()


def mark_nudged(conn: sqlite3.Connection, issue_id: int) -> None:
    """Record that the 'still bothering you?' nudge was shown for this issue."""
    conn.execute(
        "UPDATE body_issues SET last_nudge_at = datetime('now') WHERE id = ?",
        (issue_id,),
    )
    conn.commit()


# ── Lifecycle ─────────────────────────────────────────────────────────

def auto_archive_stale(conn: sqlite3.Connection) -> int:
    """Auto-close issues idle ≥ AUTO_ARCHIVE_DAYS days. Returns rows
    changed, or -1 if a write lock blocks the UPDATE.

    Opportunistic: a lock-contention failure (e.g. mid-sync) is swallowed
    so the read path never crashes. `active_issues` always filters stale
    rows in-memory for visible correctness regardless of whether this
    write actually landed — the next call will retry.
    """
    try:
        cur = conn.execute(
            """UPDATE body_issues
                  SET resolved_at = datetime('now'),
                      resolved_reason = 'auto_idle',
                      updated_at = datetime('now')
                WHERE resolved_at IS NULL
                  AND id NOT IN (
                      SELECT issue_id FROM body_severity_log
                       WHERE recorded_at >= datetime('now', ?)
                  )""",
            (f"-{AUTO_ARCHIVE_DAYS} days",),
        )
        conn.commit()
        return cur.rowcount
    except sqlite3.OperationalError:
        return -1


# ── Reads ─────────────────────────────────────────────────────────────

def active_issues(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """All currently-open issues, newest-most-severe first.

    Calls auto_archive_stale first so stale issues don't appear here.
    Each row carries:
      - id, region, side, issue_type, structure_name, note
      - created_at, updated_at, last_nudge_at
      - current_severity (latest log row)
      - days_open (whole days since created)
      - days_since_update (whole days since last log)
      - trend ('improving' | 'steady' | 'worsening' | 'new')
      - prev_severity (one log entry before current, for sparkline tail)
      - nudge_due (bool — idle ≥ NUDGE_DAYS)
      - cleared_soft_prompt (bool — severity 0 for ≥ CLEAR_SOFT_PROMPT_DAYS)
    """
    auto_archive_stale(conn)

    rows = conn.execute(
        """SELECT i.id, i.region, i.side, i.issue_type, i.structure_name,
                  i.note, i.created_at, i.updated_at, i.last_nudge_at,
                  (SELECT severity FROM body_severity_log
                    WHERE issue_id = i.id
                    ORDER BY recorded_at DESC, id DESC LIMIT 1) AS current_severity,
                  (SELECT recorded_at FROM body_severity_log
                    WHERE issue_id = i.id
                    ORDER BY recorded_at DESC, id DESC LIMIT 1) AS last_log_at,
                  (SELECT severity FROM body_severity_log
                    WHERE issue_id = i.id
                    ORDER BY recorded_at DESC, id DESC LIMIT 1 OFFSET 1) AS prev_severity
             FROM body_issues i
            WHERE i.resolved_at IS NULL
            ORDER BY current_severity DESC, i.created_at ASC""",
    ).fetchall()

    out: list[dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        cur_sev = d.get("current_severity") or 0
        prev_sev = d.get("prev_severity")
        d["severity_band"] = severity_band(cur_sev)
        d["days_open"] = _days_since(d.get("created_at"))
        d["days_since_update"] = _days_since(d.get("last_log_at"))
        # In-memory stale filter — keeps visible correctness independent
        # of whether auto_archive_stale's UPDATE landed (it may have been
        # blocked by a write lock; we'll retry next time).
        if (d["days_since_update"] is not None
                and d["days_since_update"] >= AUTO_ARCHIVE_DAYS):
            continue
        d["trend"] = _trend(cur_sev, prev_sev)
        d["nudge_due"] = (
            d["days_since_update"] is not None
            and d["days_since_update"] >= NUDGE_DAYS
        )
        d["cleared_soft_prompt"] = _is_cleared_soft_prompt(conn, d["id"])
        # Last ~10 severity readings, oldest-first, for the sparkline.
        # N is small (active issues rarely > 5-6) so N+1 is fine.
        trail_rows = conn.execute(
            """SELECT severity FROM body_severity_log
                WHERE issue_id = ?
                ORDER BY recorded_at DESC, id DESC LIMIT 10""",
            (d["id"],),
        ).fetchall()
        d["severity_trail"] = [int(t["severity"]) for t in reversed(trail_rows)]
        # Design key — 'front:hipflexor-L', 'back:neck', etc. Used by
        # the new diagram's data-region hooks + glow ellipse anchors.
        d["design_key"] = design_key(d["region"], d["side"])
        d["face"] = region_face(d["region"])
        d["severity_band_num"] = severity_band_num(d.get("current_severity") or 0)
        out.append(d)
    return out


def streak_days(conn: sqlite3.Connection) -> int:
    """Consecutive days at the end of which the runner's worst active
    severity was ≤3 (mild band). Powers the green 'N days without a
    flag' chip in the active section header."""
    # Walk back day-by-day. A day "counts" if there exists no severity_log
    # entry with severity ≥ 4 in the last 24h ending at the cursor.
    days = 0
    cursor = conn.execute("SELECT date('now') AS today").fetchone()
    if not cursor:
        return 0
    while days < 365:  # cap so we never loop unbounded
        hit = conn.execute(
            """SELECT 1 FROM body_severity_log
                WHERE severity >= 4
                  AND date(recorded_at) = date('now', ?)
                LIMIT 1""",
            (f"-{days} days",),
        ).fetchone()
        if hit:
            break
        days += 1
    return days


def recent_resolved(
    conn: sqlite3.Connection, days: int = 30
) -> list[dict[str, Any]]:
    """Resolved issues from the last N days, newest-resolved first.

    Each row carries `created_at` + `resolved_at` so the history view
    can render the open-span ("open 12 days"). `month_key` /
    `month_label` are pre-computed for the timeline's month grouping.
    """
    rows = conn.execute(
        f"""SELECT id, region, side, issue_type, structure_name, note,
                   created_at, resolved_at, resolved_reason,
                   (SELECT MAX(severity) FROM body_severity_log
                     WHERE issue_id = body_issues.id) AS peak_severity
              FROM body_issues
             WHERE resolved_at IS NOT NULL
               AND resolved_at >= datetime('now', '-{int(days)} days')
             ORDER BY resolved_at DESC""",
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        d["days_since_resolved"] = _days_since(d.get("resolved_at"))
        d["days_open"] = _span_days(d.get("created_at"), d.get("resolved_at"))
        d["design_key"] = design_key(d["region"], d["side"])
        d["face"] = region_face(d["region"])
        d["severity_band_num"] = severity_band_num(d.get("peak_severity") or 0)
        # Month grouping for the timeline view. month_key sorts naturally
        # ("2026-05" → "2026-04"), month_label is what the UI renders.
        d["month_key"], d["month_label"] = _month_bucket(d.get("resolved_at"))
        out.append(d)
    return out


def heatmap_by_design_key(
    conn: sqlite3.Connection, window_days: int = 90
) -> dict[str, float]:
    """Per-side heatmap intensities normalised 0..1, keyed by design key
    ('front:knee-R', 'back:calf-L'). Matches the design's HEAT data shape.

    Intensity = peak_severity_for_this_side / max_peak_across_all_sides.
    Sides with no issues in the window are absent from the dict.
    """
    rows = conn.execute(
        f"""SELECT i.region, i.side,
                   COALESCE(MAX(p.peak), 0) AS peak
              FROM body_issues i
              JOIN (SELECT issue_id, MAX(severity) AS peak
                      FROM body_severity_log
                     WHERE recorded_at >= datetime('now', '-{int(window_days)} days')
                     GROUP BY issue_id) p ON p.issue_id = i.id
             GROUP BY i.region, i.side""",
    ).fetchall()
    if not rows:
        return {}
    by_side: dict[str, int] = {}
    for r in rows:
        peak = int(r["peak"] or 0)
        if peak == 0:
            continue
        key = design_key(r["region"], r["side"])
        by_side[key] = max(by_side.get(key, 0), peak)
    if not by_side:
        return {}
    max_peak = max(by_side.values())
    if max_peak == 0:
        return {}
    return {k: round(v / max_peak, 3) for k, v in by_side.items()}


def heatmap_aggregates(
    conn: sqlite3.Connection, window_days: int = 90
) -> dict[str, dict[str, Any]]:
    """Per-region aggregate severity over the window.

    Returns {region_key: {count, peak_sum, max_severity, sides: {left, right, midline}}}.
    `peak_sum` = sum of peak severities per issue that touched the region in
    the window — the intensity the heatmap renders against the max across
    regions for normalization.
    """
    rows = conn.execute(
        f"""SELECT i.region, i.side,
                   COUNT(DISTINCT i.id) AS issue_count,
                   COALESCE(SUM(p.peak), 0) AS peak_sum,
                   COALESCE(MAX(p.peak), 0) AS max_severity
              FROM body_issues i
              JOIN (SELECT issue_id, MAX(severity) AS peak
                      FROM body_severity_log
                     WHERE recorded_at >= datetime('now', '-{int(window_days)} days')
                     GROUP BY issue_id) p ON p.issue_id = i.id
             GROUP BY i.region, i.side""",
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = _row_to_dict(r)
        region = d["region"]
        slot = out.setdefault(
            region,
            {"count": 0, "peak_sum": 0, "max_severity": 0,
             "sides": {"left": 0, "right": 0, "midline": 0}},
        )
        slot["count"] += int(d["issue_count"])
        slot["peak_sum"] += int(d["peak_sum"])
        slot["max_severity"] = max(slot["max_severity"], int(d["max_severity"]))
        slot["sides"][d["side"]] = slot["sides"].get(d["side"], 0) + int(d["issue_count"])
    return out


def latest_clear_log(conn: sqlite3.Connection) -> dict[str, Any] | None:
    """Most-recent 'all good' check-in, or None."""
    row = conn.execute(
        "SELECT id, recorded_at FROM body_clear_logs ORDER BY recorded_at DESC LIMIT 1",
    ).fetchone()
    return _row_to_dict(row) if row else None


def latest_severity_log_for_issue(
    conn: sqlite3.Connection, region: str, side: str
) -> dict[str, Any] | None:
    """Lookup the active issue (if any) for a region+side. Used by the entry
    panel to decide between 'new' and 'update existing'."""
    row = conn.execute(
        """SELECT id, region, side, issue_type, structure_name, note,
                  (SELECT severity FROM body_severity_log
                    WHERE issue_id = body_issues.id
                    ORDER BY recorded_at DESC, id DESC LIMIT 1) AS current_severity
             FROM body_issues
            WHERE region = ? AND side = ? AND resolved_at IS NULL
            ORDER BY created_at DESC LIMIT 1""",
        (region, side),
    ).fetchone()
    return _row_to_dict(row) if row else None


# ── Dashboard widget summary ─────────────────────────────────────────

def dashboard_summary(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compact context for the dashboard 'Body status' widget.

    Returns:
      - top_issues: up to 2 active issues, highest-severity first
      - active_count: total active issues
      - all_clear: True if no active issues
      - show_daily_prompt: True if no body update in DAILY_PROMPT_THROTTLE_HOURS
        (so the runner sees the 'Anything new today?' banner)
      - last_clear_at: ISO timestamp of last 'all good' log, or None
    """
    issues = active_issues(conn)
    last_clear = latest_clear_log(conn)
    last_clear_at = last_clear["recorded_at"] if last_clear else None

    # Show the daily prompt unless the runner already touched body data
    # in the throttle window — either logged/updated an issue OR tapped
    # 'all good'. Onboarding zero-state suppresses the banner too.
    last_issue_update = conn.execute(
        "SELECT MAX(updated_at) AS t FROM body_issues",
    ).fetchone()
    last_issue_update_at = last_issue_update["t"] if last_issue_update else None

    most_recent_touch = _max_iso(last_issue_update_at, last_clear_at)
    show_daily_prompt = _hours_since(most_recent_touch) is None or (
        _hours_since(most_recent_touch) >= DAILY_PROMPT_THROTTLE_HOURS
    )

    # Suppress daily prompt for true first-runners (no clear logs ever +
    # no issues ever) — the Body tab's onboarding zero-state explainer
    # is the better entry point.
    any_body_data = conn.execute(
        "SELECT EXISTS(SELECT 1 FROM body_issues) "
        "    OR EXISTS(SELECT 1 FROM body_clear_logs) AS has_data",
    ).fetchone()
    has_data = bool(any_body_data["has_data"]) if any_body_data else False
    if not has_data:
        show_daily_prompt = False

    return {
        "top_issues": issues[:2],
        "active_count": len(issues),
        "all_clear": len(issues) == 0,
        "show_daily_prompt": show_daily_prompt,
        "last_clear_at": last_clear_at,
        "any_body_data": has_data,
    }


# ── LLM context block ────────────────────────────────────────────────

def context_for_llm(conn: sqlite3.Connection) -> str | None:
    """Render the body block for the cached profile prompt.

    Returns None if there's nothing useful to say (no active issues, no
    recent resolved, no flare-up pattern in the last 90 days). The caller
    is responsible for the opt-out gate (Settings → include_body_in_llm).
    """
    active = active_issues(conn)
    resolved = recent_resolved(conn, days=30)
    heatmap = heatmap_aggregates(conn, window_days=90)
    # Suppress block when the picture is empty — a clean bill of health
    # doesn't need to take up tokens.
    if not active and not resolved and not any(v["count"] for v in heatmap.values()):
        return None

    lines: list[str] = []
    if active:
        lines.append("ACTIVE BODY ISSUES (treat as ground truth, runner-reported):")
        for i in active:
            side = "" if i["side"] == "midline" else f"{i['side']} "
            region = slug_label(i["region"])
            ttype = next((lbl for k, lbl in ISSUE_TYPES if k == i["issue_type"]), i["issue_type"])
            line = (
                f"  - {side}{region} · {ttype.lower()} · {i.get('current_severity', '?')}/10 · "
                f"{i.get('days_open', 0)} days · trend {i.get('trend', 'steady')}"
            )
            if i.get("structure_name"):
                line += f" · {i['structure_name']}"
            if i.get("note"):
                note = i["note"].strip().replace("\n", " ")
                if len(note) > 80:
                    note = note[:77] + "..."
                line += f' · note "{note}"'
            lines.append(line)
    if resolved:
        lines.append("RECENTLY RESOLVED (last 30 days):")
        for r in resolved:
            side = "" if r["side"] == "midline" else f"{r['side']} "
            region = slug_label(r["region"])
            ttype = next((lbl for k, lbl in ISSUE_TYPES if k == r["issue_type"]), r["issue_type"])
            reason = r.get("resolved_reason", "manual")
            days = r.get("days_since_resolved", 0)
            lines.append(
                f"  - {side}{region} · {ttype.lower()} · resolved {days} days ago ({reason})"
            )

    # Heatmap: surface only regions with ≥ 2 flare-ups in the window —
    # one-off complaints aren't pattern signal.
    flare_zones = sorted(
        ((r, v) for r, v in heatmap.items() if v["count"] >= 2),
        key=lambda kv: kv[1]["peak_sum"],
        reverse=True,
    )[:3]
    if flare_zones:
        lines.append("RECENT BODY HEATMAP (top zones, last 90d):")
        for region, agg in flare_zones:
            lines.append(
                f"  - {slug_label(region)} — {agg['count']} flare-ups"
            )

    return "\n".join(lines) if lines else None


# ── Run-detail auto-suggest heuristic ────────────────────────────────

def should_suggest_after_run(run: dict[str, Any] | None) -> bool:
    """Returns True when a completed run's effort/feel mismatch warrants
    prompting 'Anything bothering you?' in the run-detail modal.

    Triggers:
      - The run is matched to a plan workout typed 'easy' / 'recovery' AND
        Garmin RPE ≥ 8 (rescaled 1-10).
      - No matched plan workout BUT avg HR is mostly Z1-Z2 (recovery zone)
        AND RPE ≥ 8.
      - Garmin feel = 'Very strong' (felt easy) but actual avg pace was
        substantially slower than the runner's recent easy-pace baseline.
        Implementation note: rather than chase a baseline here, we read
        the matched plan target pace if present and trigger when actual
        is > 30 s/km slower despite high `feel`.

    Returns False on no run, no signals, or when any signal is missing.
    """
    if not run:
        return False

    rpe = run.get("garmin_rpe")
    # garmin_feel is stored as an int 0-100 (Garmin's scale). 0 = very weak,
    # 50 = normal, 100 = very strong. We compare numerically; the older
    # string-label assumption crashed on any non-None int.
    feel_n = run.get("garmin_feel")
    matched_type_raw = run.get("plan_workout_type") or run.get("workout_type") or ""
    matched_type = matched_type_raw.lower() if isinstance(matched_type_raw, str) else ""
    actual_pace_s = run.get("actual_pace_s_per_km") or run.get("pace_s_per_km")
    target_pace_s = run.get("target_pace_s_per_km")
    avg_hr_zone_avg = run.get("avg_hr_zone")  # float 1.0-5.0 if computed upstream

    # Trigger 1: high RPE on an easy/recovery run
    if rpe is not None and rpe >= 8:
        if matched_type in ("easy", "recovery"):
            return True
        # Fallback when no plan match — proxy via HR zone
        if matched_type == "" and avg_hr_zone_avg is not None and avg_hr_zone_avg <= 2.5:
            return True

    # Trigger 2: 'strong'-or-better feel (>= 75) but actual pace materially
    # slower than target — feels easy on paper but legs were dragging.
    if (feel_n is not None and feel_n >= 75
            and target_pace_s and actual_pace_s
            and actual_pace_s - target_pace_s > 30):
        return True

    return False


# ── Internal helpers ─────────────────────────────────────────────────

def _validate_region_side(region: str, side: str) -> None:
    if region not in REGIONS:
        raise ValueError(f"unknown region: {region!r}")
    if region in MIDLINE_REGIONS:
        if side != "midline":
            raise ValueError(f"midline region {region!r} requires side='midline'")
    else:
        if side not in ("left", "right"):
            raise ValueError(f"paired region {region!r} requires side in (left, right)")


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {}
    return {k: row[k] for k in row.keys()}


def _span_days(start_iso: str | None, end_iso: str | None) -> int | None:
    """Whole days between two ISO timestamps. None if either is invalid."""
    if not start_iso or not end_iso:
        return None
    try:
        a = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
        b = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return max(0, (b.date() - a.date()).days)


_MONTH_LABELS_EN = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _month_bucket(iso_ts: str | None) -> tuple[str, str]:
    """('2026-05-14...' → ('2026-05', 'MAY 2026')) for history grouping.
    Returns ('', '—') on invalid input."""
    if not iso_ts:
        return "", "—"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return "", "—"
    return f"{dt.year:04d}-{dt.month:02d}", f"{_MONTH_LABELS_EN[dt.month - 1].upper()} {dt.year}"


def _days_since(iso_ts: str | None) -> int | None:
    """Whole days between an ISO timestamp and now. None if invalid."""
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    # SQLite datetime('now') is naive UTC; treat the row as UTC if naive.
    if dt.tzinfo is None:
        ref = datetime.utcnow()
    else:
        ref = datetime.now(dt.tzinfo)
    return max(0, (ref.date() - dt.date()).days)


def _hours_since(iso_ts: str | None) -> float | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        ref = datetime.utcnow()
    else:
        ref = datetime.now(dt.tzinfo)
    return max(0.0, (ref - dt).total_seconds() / 3600.0)


def _max_iso(a: str | None, b: str | None) -> str | None:
    if a and b:
        return a if a >= b else b
    return a or b


def _trend(current: int | None, prev: int | None) -> str:
    if current is None:
        return "new"
    if prev is None:
        return "new"
    if current < prev:
        return "improving"
    if current > prev:
        return "worsening"
    return "steady"


def _is_cleared_soft_prompt(conn: sqlite3.Connection, issue_id: int) -> bool:
    """True when the last two distinct calendar days of severity logs were both 0."""
    rows = conn.execute(
        """SELECT severity, recorded_at
             FROM body_severity_log
            WHERE issue_id = ?
            ORDER BY recorded_at DESC, id DESC
            LIMIT 5""",
        (issue_id,),
    ).fetchall()
    if not rows:
        return False
    # Group readings by calendar date; check the most-recent N days are all 0.
    seen_dates: list[date] = []
    by_date: dict[date, int] = {}
    for r in rows:
        try:
            d = datetime.fromisoformat(str(r["recorded_at"]).replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            continue
        if d not in by_date:
            by_date[d] = int(r["severity"])
            seen_dates.append(d)
        if len(seen_dates) >= CLEAR_SOFT_PROMPT_DAYS:
            break
    if len(seen_dates) < CLEAR_SOFT_PROMPT_DAYS:
        return False
    return all(by_date[d] == 0 for d in seen_dates[:CLEAR_SOFT_PROMPT_DAYS])
