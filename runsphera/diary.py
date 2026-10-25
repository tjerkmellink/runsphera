"""Runner's diary — free-text notes optionally linked to a run or a planned workout.

A diary entry has:
  - body (required, non-empty)
  - mood (optional, 1..5)
  - entry_date (when the entry is *for* — defaults to today, or the activity's
    date when linked to a run)
  - activity_id (optional FK to activities)
  - plan_workout_id (optional FK to plan_workouts)

Entries linked to an activity are 1:1 with that activity in v1 — upserting on
the same `activity_id` updates the existing entry. Free-standing entries (no
activity link) are unique per row.
"""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any


# Mapping for the 5-emoji mood dial used in the UI.
MOOD_EMOJI = {1: "💀", 2: "😣", 3: "😐", 4: "🙂", 5: "😄"}
MOOD_LABEL = {1: "exhausted", 2: "tough", 3: "okay", 4: "good", 5: "great"}


def mood_emoji(value: int | None) -> str:
    if value is None or value not in MOOD_EMOJI:
        return ""
    return MOOD_EMOJI[value]


def mood_label(value: int | None) -> str:
    if value is None or value not in MOOD_LABEL:
        return ""
    return MOOD_LABEL[value]


# Garmin's `directWorkoutFeel` (0-100) maps to a 5-step "Very weak → Very strong" dial.
_FEEL_LABELS = [
    (20,  "Very weak"),
    (40,  "Weak"),
    (60,  "OK"),
    (80,  "Strong"),
    (101, "Very strong"),
]

# Garmin's `directWorkoutRpe` (0-100) maps to a 1-10 RPE scale (Borg-like).
_RPE_LABELS = {
    1: "very light", 2: "light", 3: "moderate", 4: "moderate", 5: "somewhat hard",
    6: "hard",       7: "hard",  8: "very hard", 9: "very hard", 10: "max effort",
}


def garmin_feel_label(value: int | None) -> str:
    if value is None:
        return ""
    for threshold, label in _FEEL_LABELS:
        if value < threshold:
            return label
    return _FEEL_LABELS[-1][1]


def garmin_rpe_label(value: int | None) -> str:
    """Returns 'RPE 8 — very hard' style string."""
    if value is None:
        return ""
    rpe = max(1, min(10, round(value / 10)))
    return f"RPE {rpe} — {_RPE_LABELS[rpe]}"


def get_entry_for_activity(conn: sqlite3.Connection, activity_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM diary_entries WHERE activity_id = ? ORDER BY updated_at DESC LIMIT 1",
        (activity_id,),
    ).fetchone()
    return dict(row) if row else None


def get_entry(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM diary_entries WHERE id = ?", (entry_id,)).fetchone()
    return dict(row) if row else None


def upsert_for_activity(
    conn: sqlite3.Connection,
    activity_id: int,
    body: str,
    mood: int | None,
    entry_date: str | None = None,
) -> dict:
    """One entry per activity. Saves or updates. Empty body deletes the entry."""
    body = (body or "").strip()
    if not body and mood is None:
        # Treat as a delete request
        conn.execute("DELETE FROM diary_entries WHERE activity_id = ?", (activity_id,))
        conn.commit()
        return {"deleted": True, "activity_id": activity_id}

    existing = get_entry_for_activity(conn, activity_id)

    # Default entry_date: prefer the activity's start date if available.
    if not entry_date:
        row = conn.execute(
            "SELECT date(start_time_local) AS d FROM activities WHERE activity_id = ?",
            (activity_id,),
        ).fetchone()
        entry_date = (row["d"] if row and row["d"] else date.today().isoformat())

    if existing:
        conn.execute(
            """UPDATE diary_entries
               SET body = ?, mood = ?, entry_date = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (body, mood, entry_date, existing["id"]),
        )
        entry_id = existing["id"]
    else:
        cur = conn.execute(
            """INSERT INTO diary_entries (entry_date, body, mood, activity_id)
               VALUES (?, ?, ?, ?)""",
            (entry_date, body, mood, activity_id),
        )
        entry_id = cur.lastrowid
    conn.commit()
    return dict(
        conn.execute("SELECT * FROM diary_entries WHERE id = ?", (entry_id,)).fetchone()
    )


def get_entry_with_links(conn: sqlite3.Connection, entry_id: int) -> dict | None:
    """Same shape as list_entries() rows — joined linked-activity + linked-workout."""
    row = conn.execute(
        """SELECT de.*,
                  a.activity_name        AS linked_activity_name,
                  a.start_time_local     AS linked_activity_start,
                  a.distance_m           AS linked_activity_distance_m,
                  pw.title               AS linked_workout_title,
                  pw.workout_type        AS linked_workout_type
           FROM diary_entries de
           LEFT JOIN activities a    ON a.activity_id = de.activity_id
           LEFT JOIN plan_workouts pw ON pw.id = de.plan_workout_id
           WHERE de.id = ?""",
        (entry_id,),
    ).fetchone()
    return dict(row) if row else None


def update_entry(
    conn: sqlite3.Connection,
    entry_id: int,
    body: str,
    mood: int | None,
) -> dict | None:
    """Update body + mood of an existing entry. Empty body + no mood deletes the
    row, matching the upsert convention used elsewhere. Returns the updated dict
    or None if the entry was deleted (or didn't exist)."""
    body = (body or "").strip()
    if not body and mood is None:
        conn.execute("DELETE FROM diary_entries WHERE id = ?", (entry_id,))
        conn.commit()
        return None
    conn.execute(
        """UPDATE diary_entries
           SET body = ?, mood = ?, updated_at = datetime('now')
           WHERE id = ?""",
        (body, mood, entry_id),
    )
    conn.commit()
    return get_entry_with_links(conn, entry_id)


def list_entries(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    """All entries, reverse-chronological by entry_date, plus joined activity name + plan workout title."""
    rows = conn.execute(
        """SELECT de.*,
                  a.activity_name        AS linked_activity_name,
                  a.start_time_local     AS linked_activity_start,
                  a.distance_m           AS linked_activity_distance_m,
                  pw.title               AS linked_workout_title,
                  pw.workout_type        AS linked_workout_type
           FROM diary_entries de
           LEFT JOIN activities a    ON a.activity_id = de.activity_id
           LEFT JOIN plan_workouts pw ON pw.id = de.plan_workout_id
           ORDER BY de.entry_date DESC, de.updated_at DESC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def group_by_iso_week(entries: list[dict]) -> list[dict]:
    """Group entries into weekly buckets for the Diary tab.

    Returns list of {week_label, week_start, entries}.
    """
    from datetime import datetime, timedelta
    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for e in entries:
        try:
            d = datetime.strptime(e["entry_date"][:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        iso_year, iso_week, _ = d.isocalendar()
        key = (iso_year, iso_week)
        if key not in buckets:
            monday = d - timedelta(days=d.weekday())
            buckets[key] = {
                "week_label": f"Week of {monday.strftime('%a %d %b %Y')}",
                "week_start": monday.isoformat(),
                "entries": [],
            }
        buckets[key]["entries"].append(e)
    return [buckets[k] for k in sorted(buckets.keys(), reverse=True)]


def split_headline(body: str | None) -> tuple[str, str]:
    """Split a body into (headline, rest). Headline = first sentence or first
    line, capped at ~90 chars. Rest = remainder of the body.

    Used by the Tempo diary feed to render a punchy editorial title above the
    muted body excerpt, mirroring how the design treats entries with
    self-curated first lines ("Tempo morning — green light. Legs felt...").
    """
    if not body:
        return ("", "")
    body = body.strip()
    if not body:
        return ("", "")

    # Find the first natural break — newline beats period if both present.
    candidates: list[int] = []
    nl = body.find("\n")
    if 0 <= nl <= 110:
        candidates.append(nl)
    # Match period + whitespace (avoids cutting on decimals or abbreviations
    # like "5.30am"). +1 so the period is included in the headline.
    for marker in (". ", ".\n", ".\t"):
        idx = body.find(marker)
        if 0 <= idx <= 110:
            candidates.append(idx + 1)
    if candidates:
        cut = min(candidates)
        headline = body[:cut].strip()
        rest = body[cut:].lstrip(". \n\t")
        if headline:
            return (headline, rest)

    # No natural break inside the window — fall back to length-based cut.
    if len(body) <= 90:
        return (body, "")
    return (body[:87].rstrip() + "…", body[87:].lstrip())


def entry_streak(entries: list[dict], today: date | None = None) -> dict:
    """Current streak (consecutive calendar days ending today with ≥1 entry)
    and all-time longest streak.

    Returns {"current": int, "longest": int, "longest_month": str | None}
    where `longest_month` is the month-year string (e.g. 'Apr') of the day
    the longest streak ended.
    """
    today = today or date.today()
    # Build a set of entry dates for O(1) lookups.
    entry_dates: set[date] = set()
    for e in entries:
        try:
            entry_dates.add(date.fromisoformat(e["entry_date"][:10]))
        except (ValueError, TypeError):
            pass

    if not entry_dates:
        return {"current": 0, "longest": 0, "longest_month": None}

    # Current streak — walk backwards from today.
    current = 0
    d = today
    while d in entry_dates:
        current += 1
        d -= timedelta(days=1)

    # Longest streak — scan over the full sorted date set.
    sorted_dates = sorted(entry_dates)
    longest = 0
    longest_month: str | None = None
    run = 1
    for i in range(1, len(sorted_dates)):
        if (sorted_dates[i] - sorted_dates[i - 1]).days == 1:
            run += 1
        else:
            if run > longest:
                longest = run
                longest_month = sorted_dates[i - 1].strftime("%b")
            run = 1
    # Check the last run.
    if run > longest:
        longest = run
        longest_month = sorted_dates[-1].strftime("%b")

    return {"current": current, "longest": longest, "longest_month": longest_month}


# ---- Freestanding entries (not tied to an activity or planned workout) -----

def get_entry_for_date(conn: sqlite3.Connection, entry_date: str) -> dict | None:
    """One freestanding entry per calendar date — for the dashboard's 'Today's note' card."""
    row = conn.execute(
        """SELECT * FROM diary_entries
           WHERE entry_date = ? AND activity_id IS NULL AND plan_workout_id IS NULL
           ORDER BY updated_at DESC LIMIT 1""",
        (entry_date,),
    ).fetchone()
    return dict(row) if row else None


def upsert_for_date(
    conn: sqlite3.Connection,
    entry_date: str,
    body: str,
    mood: int | None,
) -> dict | None:
    """Save (or update) the freestanding diary entry for a given date.
    Empty body AND no mood → deletes the entry."""
    body = (body or "").strip()
    if not body and mood is None:
        conn.execute(
            """DELETE FROM diary_entries
               WHERE entry_date = ? AND activity_id IS NULL AND plan_workout_id IS NULL""",
            (entry_date,),
        )
        conn.commit()
        return None

    existing = get_entry_for_date(conn, entry_date)
    if existing:
        conn.execute(
            """UPDATE diary_entries
               SET body = ?, mood = ?, updated_at = datetime('now')
               WHERE id = ?""",
            (body, mood, existing["id"]),
        )
        entry_id = existing["id"]
    else:
        cur = conn.execute(
            """INSERT INTO diary_entries (entry_date, body, mood)
               VALUES (?, ?, ?)""",
            (entry_date, body, mood),
        )
        entry_id = cur.lastrowid
    conn.commit()
    return dict(conn.execute("SELECT * FROM diary_entries WHERE id = ?", (entry_id,)).fetchone())
