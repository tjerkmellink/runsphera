"""Tiny key/value store for app-level settings (single-row `app_settings` table).

Currently used to remember the Garmin email between sessions so the auth form
can pre-fill it. Never stores the password — only the email and similar
non-sensitive bits.
"""
from __future__ import annotations

import sqlite3


def get_garmin_email(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT garmin_email FROM app_settings WHERE id = 1").fetchone()
    return row["garmin_email"] if row and row["garmin_email"] else None


def set_garmin_email(conn: sqlite3.Connection, email: str | None) -> None:
    conn.execute(
        "UPDATE app_settings SET garmin_email = ?, updated_at = datetime('now') WHERE id = 1",
        (email,),
    )
    conn.commit()


def get_garmin_full_name(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT garmin_full_name FROM app_settings WHERE id = 1").fetchone()
    return row["garmin_full_name"] if row and row["garmin_full_name"] else None


def set_garmin_full_name(conn: sqlite3.Connection, full_name: str | None) -> None:
    if not full_name:
        return  # never wipe an existing name to None
    conn.execute(
        "UPDATE app_settings SET garmin_full_name = ?, updated_at = datetime('now') WHERE id = 1",
        (full_name.strip(),),
    )
    conn.commit()


def garmin_first_name(conn: sqlite3.Connection) -> str | None:
    """Best-effort extraction: 'Jane Doe' -> 'Jane'. Returns None if no name stored."""
    full = get_garmin_full_name(conn)
    if not full:
        return None
    parts = full.strip().split()
    return parts[0] if parts else None


def get_anthropic_key(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT anthropic_api_key FROM app_settings WHERE id = 1").fetchone()
    return row["anthropic_api_key"] if row and row["anthropic_api_key"] else None


def set_anthropic_key(conn: sqlite3.Connection, key: str) -> None:
    key = (key or "").strip()
    if not key:
        return  # never wipe via empty save — use clear_anthropic_key for that
    conn.execute(
        "UPDATE app_settings SET anthropic_api_key = ?, updated_at = datetime('now') WHERE id = 1",
        (key,),
    )
    conn.commit()


def clear_anthropic_key(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE app_settings SET anthropic_api_key = NULL, updated_at = datetime('now') WHERE id = 1"
    )
    conn.commit()


def mask_anthropic_key(key: str | None) -> str:
    """Display-safe rendering: 'sk-ant-api03-...XXXX'. Empty for None."""
    if not key:
        return ""
    if len(key) <= 12:
        return "…" + key[-4:]
    return f"{key[:11]}…{key[-4:]}"


# ── Multi-provider LLM coach ──────────────────────────────────────────
# `llm_provider` selects which provider the coach voice uses. Each
# provider has its own API-key column; switching provider never
# clears another's key. `llm_cache` (the per-day generated coach
# text) is intentionally untouched on provider switch — past
# generations stay readable even after the user moves on.

_VALID_PROVIDERS = ("anthropic", "openai", "gemini")


def get_llm_provider(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT llm_provider FROM app_settings WHERE id = 1").fetchone()
    val = (row["llm_provider"] if row else None) or "anthropic"
    return val if val in _VALID_PROVIDERS else "anthropic"


def set_llm_provider(conn: sqlite3.Connection, provider: str) -> None:
    p = (provider or "").strip().lower()
    if p not in _VALID_PROVIDERS:
        return
    conn.execute(
        "UPDATE app_settings SET llm_provider = ?, updated_at = datetime('now') WHERE id = 1",
        (p,),
    )
    conn.commit()


def get_openai_key(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT openai_api_key FROM app_settings WHERE id = 1").fetchone()
    return row["openai_api_key"] if row and row["openai_api_key"] else None


def set_openai_key(conn: sqlite3.Connection, key: str) -> None:
    key = (key or "").strip()
    if not key:
        return  # never wipe via empty save — use clear_openai_key for that
    conn.execute(
        "UPDATE app_settings SET openai_api_key = ?, updated_at = datetime('now') WHERE id = 1",
        (key,),
    )
    conn.commit()


def clear_openai_key(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE app_settings SET openai_api_key = NULL, updated_at = datetime('now') WHERE id = 1"
    )
    conn.commit()


def get_gemini_key(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT gemini_api_key FROM app_settings WHERE id = 1").fetchone()
    return row["gemini_api_key"] if row and row["gemini_api_key"] else None


def set_gemini_key(conn: sqlite3.Connection, key: str) -> None:
    key = (key or "").strip()
    if not key:
        return
    conn.execute(
        "UPDATE app_settings SET gemini_api_key = ?, updated_at = datetime('now') WHERE id = 1",
        (key,),
    )
    conn.commit()


def clear_gemini_key(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE app_settings SET gemini_api_key = NULL, updated_at = datetime('now') WHERE id = 1"
    )
    conn.commit()


def mask_api_key(key: str | None) -> str:
    """Generic key masking — fewer chars from the start than the
    Anthropic-specific version (since OpenAI / Gemini key prefixes
    are shorter), but the same "show last 4" tail behavior."""
    if not key:
        return ""
    if len(key) <= 8:
        return "…" + key[-4:]
    return f"{key[:5]}…{key[-4:]}"


# Hard cap so a single setting can't blow the LLM context budget. ~1k chars is
# enough for several sentences and still small relative to the runner profile.
ABOUT_YOU_MAX_CHARS = 1000


def get_include_body_in_llm(conn: sqlite3.Connection) -> bool:
    """Whether to splice body-state into the coach's profile prompt.
    Defaults to True for existing rows (added with DEFAULT 1) but we
    treat any non-zero as True defensively."""
    row = conn.execute(
        "SELECT include_body_in_llm FROM app_settings WHERE id = 1"
    ).fetchone()
    if not row:
        return True
    return bool(row["include_body_in_llm"])


def set_include_body_in_llm(conn: sqlite3.Connection, enabled: bool) -> None:
    """Toggle the body-in-LLM opt-out. Caller is responsible for
    invalidating the daily coach cache after a flip."""
    conn.execute(
        "UPDATE app_settings SET include_body_in_llm = ?, updated_at = datetime('now') "
        "WHERE id = 1",
        (1 if enabled else 0,),
    )
    conn.commit()


def get_about_you(conn: sqlite3.Connection) -> str | None:
    row = conn.execute("SELECT about_you FROM app_settings WHERE id = 1").fetchone()
    return row["about_you"] if row and row["about_you"] else None


def set_about_you(conn: sqlite3.Connection, body: str | None) -> None:
    """Save the about-you note. Empty/None clears it."""
    body = (body or "").strip()
    if not body:
        conn.execute(
            "UPDATE app_settings SET about_you = NULL, updated_at = datetime('now') WHERE id = 1"
        )
    else:
        conn.execute(
            "UPDATE app_settings SET about_you = ?, updated_at = datetime('now') WHERE id = 1",
            (body[:ABOUT_YOU_MAX_CHARS],),
        )
    conn.commit()


def get_home_location(conn: sqlite3.Connection) -> dict | None:
    """Return {lat, lon, display_name, country_code} or None when no location set."""
    row = conn.execute(
        "SELECT home_lat, home_lon, home_display_name, home_country_code "
        "FROM app_settings WHERE id = 1"
    ).fetchone()
    if not row or row["home_lat"] is None or row["home_lon"] is None:
        return None
    return {
        "lat": row["home_lat"],
        "lon": row["home_lon"],
        "display_name": row["home_display_name"] or "",
        "country_code": row["home_country_code"],
    }


def set_home_location(
    conn: sqlite3.Connection,
    *,
    lat: float,
    lon: float,
    display_name: str,
    country_code: str | None,
) -> None:
    conn.execute(
        """UPDATE app_settings SET
              home_lat = ?, home_lon = ?,
              home_display_name = ?, home_country_code = ?,
              updated_at = datetime('now')
           WHERE id = 1""",
        (lat, lon, display_name, country_code),
    )
    conn.commit()


def clear_home_location(conn: sqlite3.Connection) -> None:
    conn.execute(
        """UPDATE app_settings SET
              home_lat = NULL, home_lon = NULL,
              home_display_name = NULL, home_country_code = NULL,
              updated_at = datetime('now')
           WHERE id = 1"""
    )
    conn.commit()


# 'auto' follows the OS via prefers-color-scheme; 'light'/'dark' force it.
ALLOWED_THEME_MODES = ("auto", "light", "dark")


def get_theme_mode(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT theme_mode FROM app_settings WHERE id = 1").fetchone()
    mode = (row["theme_mode"] if row else None) or "auto"
    return mode if mode in ALLOWED_THEME_MODES else "auto"


def set_theme_mode(conn: sqlite3.Connection, mode: str) -> None:
    if mode not in ALLOWED_THEME_MODES:
        raise ValueError(f"unknown theme_mode: {mode!r}")
    conn.execute(
        "UPDATE app_settings SET theme_mode = ?, updated_at = datetime('now') WHERE id = 1",
        (mode,),
    )
    conn.commit()


# UI + LLM coach language. 'en' is the source-of-truth language; English
# string literals double as i18n lookup keys (see runsphera/i18n.py).
ALLOWED_LANGUAGES = ("en", "nl")


def get_language(conn: sqlite3.Connection) -> str:
    row = conn.execute("SELECT language FROM app_settings WHERE id = 1").fetchone()
    lang = (row["language"] if row else None) or "en"
    return lang if lang in ALLOWED_LANGUAGES else "en"


def set_language(conn: sqlite3.Connection, lang: str) -> None:
    if lang not in ALLOWED_LANGUAGES:
        raise ValueError(f"unknown language: {lang!r}")
    conn.execute(
        "UPDATE app_settings SET language = ?, updated_at = datetime('now') WHERE id = 1",
        (lang,),
    )
    conn.commit()


# ── Getting-started wizard ─────────────────────────────────────────────
# Tracks the first-run onboarding flow. `status` is the lifecycle:
#   'pending'   — not finished; the wizard auto-opens on the dashboard
#   'dismissed' — user chose "I'll finish later"; never auto-opens again
#   'completed' — user finished the flow
# `step` is the resume point (one of ONBOARDING_STEPS in web/app.py) so
# reopening the wizard picks up where the runner left off. See
# docs/onboarding.md.

ALLOWED_ONBOARDING_STATUS = ("pending", "dismissed", "completed")


def get_onboarding(conn: sqlite3.Connection) -> dict:
    """Return {status, step}. Defaults to a fresh 'pending'/'welcome' if the
    row is somehow missing (shouldn't happen — the row is seeded at create)."""
    row = conn.execute(
        "SELECT onboarding_status, onboarding_step FROM app_settings WHERE id = 1"
    ).fetchone()
    if not row:
        return {"status": "pending", "step": "welcome"}
    return {
        "status": row["onboarding_status"] or "pending",
        "step": row["onboarding_step"] or "welcome",
    }


def set_onboarding_step(conn: sqlite3.Connection, step: str) -> None:
    """Persist the resume point as the runner moves through the wizard."""
    conn.execute(
        "UPDATE app_settings SET onboarding_step = ?, updated_at = datetime('now') WHERE id = 1",
        (step,),
    )
    conn.commit()


def set_onboarding_status(conn: sqlite3.Connection, status: str) -> None:
    if status not in ALLOWED_ONBOARDING_STATUS:
        raise ValueError(f"unknown onboarding status: {status!r}")
    conn.execute(
        "UPDATE app_settings SET onboarding_status = ?, updated_at = datetime('now') WHERE id = 1",
        (status,),
    )
    conn.commit()


# ── Manual fitness baseline (Garmin-less seed) ────────────────────────
# What the runner told us about their fitness when there's no (or not yet
# any) Garmin data: a VDOT estimated from a recent race result plus a
# self-reported weekly volume. Read by plans/service.get_plan_seed as the
# middle rung of its precedence ladder (Garmin-measured → manual → default).

def get_fitness_baseline(conn: sqlite3.Connection) -> dict:
    """Return {vdot, vdot_note, weekly_km} — each None when never set."""
    row = conn.execute(
        "SELECT manual_vdot, manual_vdot_note, manual_weekly_km "
        "FROM app_settings WHERE id = 1"
    ).fetchone()
    if not row:
        return {"vdot": None, "vdot_note": None, "weekly_km": None}
    return {
        "vdot": row["manual_vdot"],
        "vdot_note": row["manual_vdot_note"],
        "weekly_km": row["manual_weekly_km"],
    }


def set_manual_vdot(conn: sqlite3.Connection, vdot: float, note: str | None = None) -> None:
    """Store a manually-derived VDOT (typically from a race result via
    estimate_vdot_from_race). Range-checked so a typo'd race time can't
    poison every generated pace."""
    if not (20 <= vdot <= 85):
        raise ValueError("vdot must be between 20 and 85")
    conn.execute(
        "UPDATE app_settings SET manual_vdot = ?, manual_vdot_note = ?, "
        "updated_at = datetime('now') WHERE id = 1",
        (round(float(vdot), 1), (note or "").strip() or None),
    )
    conn.commit()


def set_manual_weekly_km(conn: sqlite3.Connection, weekly_km: float) -> None:
    if not (0 <= weekly_km <= 300):
        raise ValueError("weekly_km must be between 0 and 300")
    conn.execute(
        "UPDATE app_settings SET manual_weekly_km = ?, updated_at = datetime('now') "
        "WHERE id = 1",
        (round(float(weekly_km), 1),),
    )
    conn.commit()


def get_can_run_10min(conn: sqlite3.Connection) -> bool | None:
    """Self-assessment for plan recommendation. Tri-state: None = never
    answered, True = can run 10 minutes non-stop, False = not yet."""
    row = conn.execute("SELECT can_run_10min FROM app_settings WHERE id = 1").fetchone()
    if not row or row["can_run_10min"] is None:
        return None
    return bool(row["can_run_10min"])


def set_can_run_10min(conn: sqlite3.Connection, flag: bool) -> None:
    conn.execute(
        "UPDATE app_settings SET can_run_10min = ?, updated_at = datetime('now') WHERE id = 1",
        (1 if flag else 0,),
    )
    conn.commit()


def get_garmin_optout(conn: sqlite3.Connection) -> bool:
    """True when the runner explicitly chose to use the app without Garmin."""
    row = conn.execute("SELECT garmin_optout FROM app_settings WHERE id = 1").fetchone()
    return bool(row and row["garmin_optout"])


def set_garmin_optout(conn: sqlite3.Connection, flag: bool) -> None:
    conn.execute(
        "UPDATE app_settings SET garmin_optout = ?, updated_at = datetime('now') WHERE id = 1",
        (1 if flag else 0,),
    )
    conn.commit()


# ── Body profile (Fuel feature) ────────────────────────────────────────
# Physiological inputs that personalise the nutrition engine. Weight is
# the one required field — `get_body_profile` returns None until it's set,
# which the Fuel tab / dashboard tile use to show an empty state. `sex`
# is constrained to the two values the BMR formula distinguishes.

ALLOWED_SEX = ("male", "female")
ALLOWED_DIET_PREFS = ("omnivore", "vegetarian", "vegan")


def get_body_profile(conn: sqlite3.Connection) -> dict | None:
    """Return {weight_kg, height_cm, birth_year, sex, diet_pref, updated_at}
    or None when no weight has been set yet (the gate for the whole feature)."""
    row = conn.execute(
        "SELECT weight_kg, height_cm, birth_year, sex, diet_pref, "
        "       body_profile_updated_at "
        "FROM app_settings WHERE id = 1"
    ).fetchone()
    if not row or row["weight_kg"] is None:
        return None
    return {
        "weight_kg": row["weight_kg"],
        "height_cm": row["height_cm"],
        "birth_year": row["birth_year"],
        "sex": row["sex"],
        "diet_pref": row["diet_pref"],
        "updated_at": row["body_profile_updated_at"],
    }


def set_body_profile(
    conn: sqlite3.Connection,
    *,
    weight_kg: float | None,
    height_cm: float | None = None,
    birth_year: int | None = None,
    sex: str | None = None,
    diet_pref: str | None = None,
) -> None:
    """Persist the body profile. Weight is required and range-checked;
    the rest are optional (the engine degrades — e.g. no BMR without
    height/age, but still estimates run burn from weight alone).

    Raises ValueError on an out-of-range / invalid value so the route can
    surface a friendly error rather than storing junk.
    """
    if weight_kg is None or not (30 <= weight_kg <= 250):
        raise ValueError("weight_kg must be between 30 and 250")
    if height_cm is not None and not (100 <= height_cm <= 250):
        raise ValueError("height_cm must be between 100 and 250")
    if birth_year is not None and not (1900 <= birth_year <= 2025):
        raise ValueError("birth_year out of range")
    if sex is not None and sex not in ALLOWED_SEX:
        raise ValueError(f"sex must be one of {ALLOWED_SEX}")
    if diet_pref is not None and diet_pref not in ALLOWED_DIET_PREFS:
        raise ValueError(f"diet_pref must be one of {ALLOWED_DIET_PREFS}")
    conn.execute(
        """UPDATE app_settings SET
              weight_kg = ?, height_cm = ?, birth_year = ?,
              sex = ?, diet_pref = ?,
              body_profile_updated_at = datetime('now'),
              updated_at = datetime('now')
           WHERE id = 1""",
        (weight_kg, height_cm, birth_year, sex, diet_pref),
    )
    conn.commit()


def db_stats(conn: sqlite3.Connection) -> dict:
    """Snapshot of what's in the local DB — surfaced on the Settings page so
    the runner can see at a glance how much they've accumulated and verify
    nothing's leaving the laptop."""
    import os
    from .db import get_db_path

    path = get_db_path()
    size_bytes = path.stat().st_size if path.exists() else 0
    activity_count = conn.execute(
        "SELECT COUNT(*) FROM activities WHERE activity_type = 'running'"
    ).fetchone()[0]
    diary_count = conn.execute("SELECT COUNT(*) FROM diary_entries").fetchone()[0]
    last_sync_row = conn.execute(
        "SELECT completed_at FROM ingestion_runs "
        "WHERE success = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    first_run_row = conn.execute(
        "SELECT MIN(date(start_time_local)) AS first_date "
        "FROM activities WHERE activity_type = 'running'"
    ).fetchone()
    return {
        "path": str(path),
        "path_short": str(path).replace(os.path.expanduser("~"), "~"),
        "size_bytes": size_bytes,
        "size_human": f"{size_bytes / (1024 * 1024):.1f} MB" if size_bytes else "—",
        "activity_count": activity_count,
        "diary_count": diary_count,
        "last_sync_at": last_sync_row["completed_at"] if last_sync_row else None,
        "first_run_date": first_run_row["first_date"] if first_run_row else None,
    }
