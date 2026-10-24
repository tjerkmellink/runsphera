"""Race calendar: list / favorite / enrich events.

The app ships with a curated set (seeded on first run from
`running_coach/data/curated_events.json`); runners can add their own events
manually (`source='user'`). Enrichment scrapes an organiser site for a
description + hero image.

Distances are stored as a JSON array `[{km, label}, ...]` since most NL races
offer multiple distances at the same event (5k/10k/half on the same day).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from datetime import date
from html import unescape
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


# ---- Distance → plan goal mapping -------------------------------------------

# Canonical distance constants in km.
HALF_MARATHON_KM = 21.0975
MARATHON_KM = 42.195

# Distance → plan goal_type. None means "custom / pick manually" (parkrun, trail,
# ultra, etc.). Tolerance allows for the standard race distances even when the
# rounded label differs (e.g. "21,1 km" should still register as a half).
_DISTANCE_TO_GOAL: list[tuple[float, float, str]] = [
    # (km, tolerance, goal_type)
    (5.0,             0.10, "5k"),
    (10.0,            0.15, "10k"),
    (15.0,            0.20, "15k"),
    (HALF_MARATHON_KM, 0.30, "half_marathon"),
    (MARATHON_KM,      0.50, "marathon"),
]


def goal_type_for_distance(km: float) -> str | None:
    """Map a distance in km to one of the plan engine's goal_type strings, or
    None if the distance doesn't correspond to a supported plan goal."""
    if km is None:
        return None
    for target, tol, goal in _DISTANCE_TO_GOAL:
        if abs(km - target) <= tol:
            return goal
    return None


_PROVINCE_NAMES: dict[str, str] = {
    "NB": "Noord-Brabant", "NH": "Noord-Holland", "ZH": "Zuid-Holland",
    "GE": "Gelderland",    "OV": "Overijssel",    "UT": "Utrecht",
    "FR": "Friesland",     "GR": "Groningen",     "DR": "Drenthe",
    "FL": "Flevoland",     "LB": "Limburg",       "ZE": "Zeeland",
}


def province_name(code: str | None) -> str:
    if not code:
        return ""
    return _PROVINCE_NAMES.get(code.upper(), code)


def _normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ---- DB writes --------------------------------------------------------------

def add_user_event(
    conn: sqlite3.Connection,
    *,
    name: str,
    race_date: date,
    distance_km: float,
    distance_label: str | None = None,
    city: str | None = None,
    country_code: str = "NL",
    organizer_url: str | None = None,
    description: str | None = None,
) -> int:
    """Insert a manually-added event. Returns its new id."""
    distances_json = json.dumps(
        [{"km": round(distance_km, 3), "label": distance_label or f"{distance_km:g} km"}],
        ensure_ascii=False,
    )
    cur = conn.execute(
        """INSERT INTO race_events
             (source, name, race_date, city, country_code,
              distances_json, organizer_url, description)
           VALUES ('user', ?, ?, ?, ?, ?, ?, ?)""",
        (name, race_date.isoformat(), city, country_code,
         distances_json, organizer_url, description),
    )
    conn.commit()
    return cur.lastrowid


# ---- DB reads ---------------------------------------------------------------

def _hydrate(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["distances"] = json.loads(d.pop("distances_json") or "[]")
    except (TypeError, ValueError):
        d["distances"] = []
    return d


def list_events(
    conn: sqlite3.Connection,
    *,
    today_iso: str | None = None,
    country_code: str | None = None,
    distance_min: float | None = None,
    distance_max: float | None = None,
    limit: int = 500,
) -> list[dict]:
    """Future-leaning list of events. By default: today onwards, all countries.

    `distance_min` / `distance_max` filter on the event having *at least one*
    distance in the given range. Use to e.g. show "marathon-ish events" or
    "halves and longer".
    """
    if today_iso is None:
        today_iso = date.today().isoformat()
    rows = conn.execute(
        """SELECT * FROM race_events
           WHERE race_date >= ?
             AND (? IS NULL OR country_code = ?)
           ORDER BY race_date, name
           LIMIT ?""",
        (today_iso, country_code, country_code, limit),
    ).fetchall()
    out: list[dict] = []
    for row in rows:
        ev = _hydrate(row)
        if distance_min is not None or distance_max is not None:
            kms = [d.get("km") for d in ev["distances"] if d.get("km") is not None]
            keep = False
            for km in kms:
                if distance_min is not None and km < distance_min:
                    continue
                if distance_max is not None and km > distance_max:
                    continue
                keep = True
                break
            if not keep:
                continue
        out.append(ev)
    return out


def get_event(conn: sqlite3.Connection, event_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM race_events WHERE id = ?", (event_id,)).fetchone()
    return _hydrate(row) if row else None


def group_by_month(events: list[dict]) -> list[dict]:
    """Bucket events into month groups for the template. Returns ordered list
    of {label, events}."""
    from datetime import datetime as _dt
    out: dict[str, dict] = {}
    for ev in events:
        try:
            d = _dt.strptime(ev["race_date"][:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        key = f"{d.year}-{d.month:02d}"
        if key not in out:
            out[key] = {
                "key": key,
                "label": d.strftime("%B %Y"),
                "events": [],
            }
        out[key]["events"].append(ev)
    return [out[k] for k in sorted(out.keys())]


def _category_for_distance(km: float | None) -> str:
    """Bucket a distance to one of: 5k, 10k, 15k, half, marathon, ultra, short, other."""
    if km is None:
        return "other"
    if km <= 3.5:
        return "short"
    if 4.5 <= km <= 5.5:
        return "5k"
    if 9.0 <= km <= 11.0:
        return "10k"
    if 14.0 <= km <= 17.0:
        return "15k"
    if 20.0 <= km <= 23.0:
        return "half"
    if 40.0 <= km <= 50.0:
        return "marathon"
    if km > 50.0:
        return "ultra"
    return "other"


def primary_category(event: dict) -> str:
    """The 'flavor' of the event — used for chip coloring in the agenda view.
    Picks the longest distance among supported plan distances; otherwise the
    longest distance overall."""
    dists = event.get("distances") or []
    if not dists:
        return "other"
    # Prefer the longest plan-supported distance; otherwise the longest overall.
    supported = [d for d in dists if goal_type_for_distance(d.get("km") or 0)]
    pool = supported if supported else dists
    longest = max((d.get("km") or 0) for d in pool)
    return _category_for_distance(longest)


def build_month_grids(events: list[dict]) -> list[dict]:
    """Build per-month calendar grids (Mon-Sun rows) populated with events.

    Returns ordered list of:
      { key, label, year, month, weeks: [[ {date, day_num, in_month, events}, ... ], ...] }
    """
    from datetime import datetime as _dt, date as _date, timedelta as _td
    by_month = group_by_month(events)
    grids: list[dict] = []
    for bucket in by_month:
        year, month = int(bucket["key"][:4]), int(bucket["key"][5:7])
        # Anchor on the first of the month, walk back to the previous Monday.
        first = _date(year, month, 1)
        # Last day of month: jump to first of next, subtract one.
        if month == 12:
            next_first = _date(year + 1, 1, 1)
        else:
            next_first = _date(year, month + 1, 1)
        last = next_first - _td(days=1)
        start = first - _td(days=first.weekday())            # Monday on/before the 1st
        end = last + _td(days=6 - last.weekday())             # Sunday on/after the last

        # Index events by date for O(1) lookup.
        by_date: dict[str, list[dict]] = {}
        for ev in bucket["events"]:
            by_date.setdefault(ev["race_date"][:10], []).append(ev)

        weeks: list[list[dict]] = []
        cur = start
        while cur <= end:
            row: list[dict] = []
            for _ in range(7):
                row.append({
                    "date": cur.isoformat(),
                    "day_num": cur.day,
                    "in_month": cur.month == month,
                    "is_today": cur == _date.today(),
                    "events": by_date.get(cur.isoformat(), []),
                })
                cur += _td(days=1)
            weeks.append(row)
        grids.append({
            "key": bucket["key"],
            "label": bucket["label"],
            "year": year,
            "month": month,
            "weeks": weeks,
        })
    return grids


# ---- runner_races (favorites) -----------------------------------------------

def favorite(
    conn: sqlite3.Connection,
    event_id: int,
    *,
    chosen_distance_km: float | None = None,
    chosen_distance_label: str | None = None,
    plan_id: int | None = None,
    is_a_race: bool = False,
    notes: str | None = None,
) -> int:
    """Save an event to the runner's calendar. Returns the runner_races id."""
    cur = conn.execute(
        """INSERT INTO runner_races
             (event_id, plan_id, chosen_distance_km, chosen_distance_label,
              is_a_race, notes)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (event_id, plan_id, chosen_distance_km, chosen_distance_label,
         1 if is_a_race else 0, notes),
    )
    conn.commit()
    return cur.lastrowid


def unfavorite(conn: sqlite3.Connection, runner_race_id: int) -> None:
    conn.execute("DELETE FROM runner_races WHERE id = ?", (runner_race_id,))
    conn.commit()


def is_favorited(conn: sqlite3.Connection, event_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM runner_races WHERE event_id = ? LIMIT 1", (event_id,)
    ).fetchone()
    return bool(row)


def delete_event(conn: sqlite3.Connection, event_id: int) -> dict:
    """Permanently remove a race_event. Refuses when the event is favorited
    so the runner doesn't silently lose saved races (FK is ON DELETE CASCADE,
    which would do it without warning otherwise).

    Returns {"deleted": bool, "reason": str | None}."""
    if is_favorited(conn, event_id):
        return {"deleted": False, "reason": "Event is saved — remove from your calendar first."}
    cur = conn.execute("DELETE FROM race_events WHERE id = ?", (event_id,))
    conn.commit()
    if cur.rowcount == 0:
        return {"deleted": False, "reason": "Event not found."}
    return {"deleted": True, "reason": None}


def export_curated_events(conn: sqlite3.Connection) -> list[dict]:
    """Snapshot race_events as a shippable, provenance-free curated set.

    This is the freeze step behind the committed `running_coach/data/curated_events.json`.
    It does the cleaning **in-memory** — the source DB is never mutated.

    Rules:
    - **Enriched-only.** Only events with an `organizer_url` (a real race website)
      ship. Bare rows without an organiser link are dropped.
    - **No legacy provenance.** `external_id` is dropped; `source` is set to
      `personal-running-coach`. (The `url` column no longer exists.)
    - **Portable images only.** Local `/event-images/…` hero paths are dropped
      (those files are gitignored, so they'd 404 on a fresh clone); external
      `http(s)` hero URLs are kept. Fresh installs re-acquire local images via
      the enrich flow.
    - Runtime/identity fields (id, created_at, updated_at, enriched_at) are
      stripped so the JSON is stable across exports of the same content.
    """
    rows = conn.execute(
        "SELECT * FROM race_events "
        "WHERE organizer_url IS NOT NULL AND organizer_url != '' "
        "ORDER BY race_date, name"
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = _hydrate(r)
        for k in ("id", "created_at", "updated_at", "enriched_at"):
            d.pop(k, None)
        # Drop legacy provenance entirely.
        d.pop("external_id", None)
        d["source"] = "personal-running-coach"
        # Keep only externally-resolvable hero images; local downloads don't ship.
        hero = d.get("hero_image_url") or ""
        if hero and not hero.startswith(("http://", "https://")):
            d.pop("hero_image_url", None)
        # Drop empty optional fields to keep the JSON tight.
        for k in list(d.keys()):
            if d[k] in (None, "", []):
                d.pop(k)
        out.append(d)
    return out


def seed_events_if_empty(conn: sqlite3.Connection) -> int:
    """Populate `race_events` from the committed curated set on first run.

    Mirrors the strength-library seeder: only runs when `race_events` is empty,
    so it never clobbers a user's imported/enriched catalogue. Reads
    `running_coach/data/curated_events.json` (the frozen, shippable
    set produced by `export_curated_events`). Returns the number of rows
    inserted (0 when the table is already populated or the file is absent).
    """
    row = conn.execute("SELECT COUNT(*) AS n FROM race_events").fetchone()
    if row and row["n"] > 0:
        return 0
    seed_path = Path(__file__).parent / "data" / "curated_events.json"
    if not seed_path.exists():
        return 0
    try:
        events = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    n = 0
    for e in events:
        distances_json = json.dumps(e.get("distances", []), ensure_ascii=False)
        conn.execute(
            """INSERT INTO race_events
                 (source, name, race_date, city, province, country_code,
                  distances_json, description, organizer_url, hero_image_url)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                e.get("source", "personal-running-coach"), e.get("name"), e.get("race_date"),
                e.get("city"), e.get("province"), e.get("country_code", "NL"),
                distances_json, e.get("description"),
                e.get("organizer_url"), e.get("hero_image_url"),
            ),
        )
        n += 1
    conn.commit()
    return n


def race_for_active_plan(conn: sqlite3.Connection, plan_id: int) -> dict | None:
    """The A-race linked to an active plan, if one exists.

    Used for the dashboard's race-day countdown — when the active plan
    has a saved race attached via `runner_races.plan_id`, that event is
    the headliner. Returns None for stay-fit plans or plans without a
    linked race (countdown card falls back to the daily bonus tip).
    """
    row = conn.execute(
        """SELECT rr.id           AS runner_race_id,
                  rr.chosen_distance_km,
                  rr.chosen_distance_label,
                  rr.is_a_race,
                  rr.plan_id,
                  rr.added_at,
                  re.*
           FROM runner_races rr
           JOIN race_events re ON re.id = rr.event_id
           WHERE rr.plan_id = ?
           ORDER BY rr.is_a_race DESC, re.race_date ASC
           LIMIT 1""",
        (plan_id,),
    ).fetchone()
    return _hydrate(row) if row else None


def list_favorites(
    conn: sqlite3.Connection,
    *,
    today_iso: str | None = None,
    upcoming_only: bool = True,
) -> list[dict]:
    """Return the runner's saved events with joined event details."""
    if today_iso is None:
        today_iso = date.today().isoformat()
    sql = """SELECT rr.id           AS runner_race_id,
                    rr.chosen_distance_km,
                    rr.chosen_distance_label,
                    rr.is_a_race,
                    rr.plan_id,
                    rr.added_at,
                    re.*
             FROM runner_races rr
             JOIN race_events re ON re.id = rr.event_id"""
    if upcoming_only:
        sql += " WHERE re.race_date >= ?"
    sql += " ORDER BY re.race_date, re.name"
    rows = conn.execute(sql, (today_iso,) if upcoming_only else ()).fetchall()
    return [_hydrate(r) for r in rows]


# ---- Enrichment: scrape organiser site + local image download ---------------

# Where downloaded event images live. Served via FastAPI's StaticFiles mount.
EVENT_IMAGE_DIR = Path("data") / "event_images"

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
_HTTP_TIMEOUT_S = 10
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB ceiling on downloaded hero images
_ALLOWED_IMAGE_TYPES = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg",
    "image/png": ".png",  "image/webp": ".webp",
    "image/gif": ".gif",
}

_META_RE = re.compile(
    r"""<meta\s+(?:property|name)\s*=\s*["']([^"']+)["']"""
    r"""\s+content\s*=\s*["']([^"']*)["']""",
    re.IGNORECASE,
)
_META_RE_REV = re.compile(
    r"""<meta\s+content\s*=\s*["']([^"']*)["']\s+"""
    r"""(?:property|name)\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_CANONICAL_RE = re.compile(
    r"""<link[^>]+rel\s*=\s*["']canonical["'][^>]+href\s*=\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title[^>]*>(.+?)</title>", re.DOTALL | re.IGNORECASE)
_H1_RE = re.compile(r"<h1[^>]*>(.+?)</h1>", re.DOTALL | re.IGNORECASE)
_P_RE = re.compile(r"<p[^>]*>(.+?)</p>", re.DOTALL | re.IGNORECASE)


def _fetch_text(url: str, max_bytes: int = 2_000_000) -> str | None:
    """GET `url` with a browser UA. Caps body size so we don't hang on huge pages."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            raw = resp.read(max_bytes + 1)
            if len(raw) > max_bytes:
                log.warning("page too large, truncated: %s", url)
                raw = raw[:max_bytes]
            ct = resp.headers.get("Content-Type", "")
            # Charset detection from header; default utf-8 (covers most modern sites).
            charset = "utf-8"
            for part in ct.split(";"):
                p = part.strip().lower()
                if p.startswith("charset="):
                    charset = p.split("=", 1)[1].strip() or "utf-8"
            return raw.decode(charset, errors="replace")
    except Exception as exc:  # noqa: BLE001 — fail soft
        log.warning("scrape fetch failed: %s (%s)", url, exc)
        return None


def _extract_meta_tags(html: str) -> dict[str, str]:
    """Pull og:* and twitter:* meta tags (and a few other names) into a dict."""
    out: dict[str, str] = {}
    for key, val in _META_RE.findall(html):
        out.setdefault(key.lower().strip(), unescape(val).strip())
    # Some pages write the attributes in the reverse order — handle both.
    for val, key in _META_RE_REV.findall(html):
        out.setdefault(key.lower().strip(), unescape(val).strip())
    return out


def _strip_inline_tags(html: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", html, flags=re.IGNORECASE)
    s = re.sub(r"<[^>]+>", "", s)
    return _normalize_ws(unescape(s))


def scrape_event_page(url: str) -> dict | None:
    """Fetch an organiser's event page and extract canonical URL, title,
    description, and hero image URL. Returns None on network/parse failure.

    Tries og:* tags first, then twitter:* tags, then falls back to a `<title>`
    + first `<h1>`/`<p>` heuristic. Hero image URL is resolved to an absolute
    URL against the page's base."""
    if not url:
        return None
    html = _fetch_text(url)
    if not html:
        return None

    meta = _extract_meta_tags(html)
    canon = _CANONICAL_RE.search(html)
    canonical_url = unescape(canon.group(1).strip()) if canon else url

    title_meta = (
        meta.get("og:title")
        or meta.get("twitter:title")
    )
    if not title_meta:
        tm = _TITLE_RE.search(html)
        if tm:
            title_meta = _strip_inline_tags(tm.group(1))[:200]

    description = (
        meta.get("og:description")
        or meta.get("twitter:description")
        or meta.get("description")
    )
    if not description:
        h1m = _H1_RE.search(html)
        pm = _P_RE.search(html)
        bits = []
        if h1m:
            bits.append(_strip_inline_tags(h1m.group(1)))
        if pm:
            bits.append(_strip_inline_tags(pm.group(1)))
        description = " — ".join(b for b in bits if b) or None
    if description:
        description = description[:1000].strip()

    image_url = (
        meta.get("og:image")
        or meta.get("og:image:secure_url")
        or meta.get("twitter:image")
        or meta.get("twitter:image:src")
    )
    if image_url:
        image_url = urllib.parse.urljoin(canonical_url, image_url.strip())

    return {
        "organizer_url": canonical_url,
        "title": title_meta or None,
        "description": description,
        "image_url": image_url,
    }


def _safe_image_filename(event_id: int, image_url: str, ext: str) -> str:
    """Stable filename that survives repeated enrichments and varies if the
    image URL changes. `event-<id>-<8charhash><ext>`."""
    h = hashlib.sha1(image_url.encode("utf-8", errors="replace")).hexdigest()[:8]
    return f"event-{event_id}-{h}{ext}"


def download_event_image(event_id: int, image_url: str) -> str | None:
    """Download an image to data/event_images/. Returns the in-app URL
    ('/event-images/<filename>') on success, or None. Fails soft on any error.

    On success, also removes any stale image files for the same event_id (older
    enrichments with a different source URL)."""
    if not image_url:
        return None
    try:
        req = urllib.request.Request(image_url, headers={"User-Agent": _BROWSER_UA})
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            ext = _ALLOWED_IMAGE_TYPES.get(content_type)
            if not ext:
                log.warning("image content-type rejected: %s (%s)", content_type, image_url)
                return None
            content_length = int(resp.headers.get("Content-Length") or 0)
            if content_length and content_length > _MAX_IMAGE_BYTES:
                log.warning("image too large: %d bytes (%s)", content_length, image_url)
                return None
            data = resp.read(_MAX_IMAGE_BYTES + 1)
            if len(data) > _MAX_IMAGE_BYTES:
                log.warning("image too large (read): %s", image_url)
                return None
    except Exception as exc:  # noqa: BLE001
        log.warning("image download failed: %s (%s)", image_url, exc)
        return None

    EVENT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    filename = _safe_image_filename(event_id, image_url, ext)
    path = EVENT_IMAGE_DIR / filename
    # Remove any prior images for this event so we don't accumulate orphans.
    for old in EVENT_IMAGE_DIR.glob(f"event-{event_id}-*"):
        if old.name != filename:
            try:
                old.unlink()
            except OSError:
                pass
    try:
        path.write_bytes(data)
    except OSError as exc:
        log.warning("image write failed: %s (%s)", path, exc)
        return None
    return f"/event-images/{filename}"


def save_enrichment(
    conn: sqlite3.Connection,
    event_id: int,
    *,
    organizer_url: str | None = None,
    description: str | None = None,
    hero_image_url: str | None = None,
) -> dict | None:
    """Write enrichment fields to an event. Only non-None fields are updated —
    pass None to leave existing values alone. Empty string clears a field."""
    fields: list[str] = []
    values: list[Any] = []
    if organizer_url is not None:
        fields.append("organizer_url = ?")
        values.append(organizer_url.strip() or None)
    if description is not None:
        fields.append("description = ?")
        values.append(description.strip() or None)
    if hero_image_url is not None:
        fields.append("hero_image_url = ?")
        values.append(hero_image_url.strip() or None)
    if not fields:
        return get_event(conn, event_id)
    fields.append("enriched_at = datetime('now')")
    fields.append("updated_at = datetime('now')")
    values.append(event_id)
    conn.execute(
        f"UPDATE race_events SET {', '.join(fields)} WHERE id = ?",
        tuple(values),
    )
    conn.commit()
    return get_event(conn, event_id)


def enrich_from_url(
    conn: sqlite3.Connection,
    event_id: int,
    url: str,
) -> tuple[dict | None, str | None]:
    """High-level: scrape `url`, download the hero image, save fields. Returns
    (updated_event, error_message). On success error_message is None."""
    url = (url or "").strip()
    if not url:
        return None, "no_url"
    scraped = scrape_event_page(url)
    if scraped is None:
        return None, "fetch_failed"

    local_image_url: str | None = None
    if scraped["image_url"]:
        local_image_url = download_event_image(event_id, scraped["image_url"])

    updated = save_enrichment(
        conn,
        event_id,
        organizer_url=scraped["organizer_url"],
        description=scraped["description"],
        hero_image_url=local_image_url,
    )
    return updated, None
