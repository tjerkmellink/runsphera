"""SQLite schema and connection helper.

Tables: activities, daily_metrics, training_readiness, training_status,
ingestion_runs. Every data row carries a `raw_json` column so any field we
don't surface yet stays available without a re-fetch.
"""
from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

from dotenv import load_dotenv

# Set of DB-file paths whose schema + migrations have already been
# applied in this process. Schema apply needs a write lock; running it
# on every `connect()` was contending with the long sync transaction
# and causing "database is locked" errors on concurrent readers. Apply
# once per path per process, then reuse. Lock guards against the race
# where two threads both see "not yet applied" and apply twice.
_SCHEMA_INITIALIZED: set[Path] = set()
_SCHEMA_LOCK = threading.Lock()

DEFAULT_DB_PATH = Path("data") / "running_coach.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    activity_id          INTEGER PRIMARY KEY,
    activity_name        TEXT,
    activity_type        TEXT NOT NULL,
    event_type           TEXT,
    start_time_local     TEXT NOT NULL,
    start_time_gmt       TEXT NOT NULL,
    end_time_gmt         TEXT,
    duration_s           REAL,
    moving_duration_s    REAL,
    distance_m           REAL,
    elevation_gain_m     REAL,
    elevation_loss_m     REAL,
    avg_speed_mps        REAL,
    max_speed_mps        REAL,
    calories             REAL,
    avg_hr               REAL,
    max_hr               INTEGER,
    avg_cadence_spm      REAL,
    max_cadence_spm      REAL,
    steps                INTEGER,
    avg_power_w          REAL,
    max_power_w          REAL,
    aerobic_te           REAL,
    anaerobic_te         REAL,
    training_load        REAL,
    vo2max               REAL,
    location_name        TEXT,
    min_temperature_c    REAL,
    max_temperature_c    REAL,
    hr_zone_1_s          REAL,
    hr_zone_2_s          REAL,
    hr_zone_3_s          REAL,
    hr_zone_4_s          REAL,
    hr_zone_5_s          REAL,
    fastest_1k_s         REAL,
    fastest_mile_s       REAL,
    fastest_5k_s         REAL,
    fastest_10k_s        REAL,
    fastest_half_s       REAL,
    body_battery_delta   INTEGER,
    raw_json             TEXT NOT NULL,
    fetched_at           TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_activities_start_time ON activities(start_time_gmt);
CREATE INDEX IF NOT EXISTS idx_activities_type ON activities(activity_type);

-- Per-lap (per-km) breakdown of running activities, pulled from Garmin's
-- /activity/{id}/splits endpoint. Each row is one auto-lap. `intensity_type`
-- reflects the watch's classification: WARMUP / ACTIVE / COOLDOWN / RECOVERY
-- on activities that came from a pushed structured workout; plain ACTIVE on
-- free runs. Used to judge structured workouts on their *active* block, not
-- the total-run average — see docs/lap-data.md.
CREATE TABLE IF NOT EXISTS activity_laps (
    activity_id        INTEGER NOT NULL,
    lap_index          INTEGER NOT NULL,
    intensity_type     TEXT,
    distance_m         REAL,
    duration_s         REAL,
    moving_duration_s  REAL,
    avg_speed_mps      REAL,
    max_speed_mps      REAL,
    avg_hr             REAL,
    max_hr             REAL,
    elevation_gain_m   REAL,
    elevation_loss_m   REAL,
    avg_cadence_spm    REAL,
    avg_power_w        REAL,
    avg_temperature_c  REAL,
    start_time_local   TEXT,
    raw_json           TEXT NOT NULL,
    fetched_at         TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (activity_id, lap_index),
    FOREIGN KEY (activity_id) REFERENCES activities(activity_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_activity_laps_activity ON activity_laps(activity_id);

-- GPS track for the run-detail map, fetched lazily (first modal open) from
-- Garmin's activity-details endpoint and cached forever — a finished run's
-- track never changes. `points_json` is a compact JSON array of
-- [lat, lon, t_rel_s] triples (Garmin's own ~2000-point downsample).
-- NULL points_json is a *negative* cache: we asked Garmin and no track came
-- back (treadmill/indoor), so we never re-ask. See docs/route-map.md.
CREATE TABLE IF NOT EXISTS activity_routes (
    activity_id  INTEGER PRIMARY KEY,
    points_json  TEXT,
    point_count  INTEGER NOT NULL DEFAULT 0,
    fetched_at   TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (activity_id) REFERENCES activities(activity_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS daily_metrics (
    calendar_date              TEXT PRIMARY KEY,
    total_steps                INTEGER,
    total_distance_m           INTEGER,
    total_kcal                 REAL,
    active_kcal                REAL,
    bmr_kcal                   REAL,
    resting_hr                 INTEGER,
    seven_day_avg_resting_hr   INTEGER,
    min_hr                     INTEGER,
    max_hr                     INTEGER,
    avg_stress                 INTEGER,
    max_stress                 INTEGER,
    body_battery_high          INTEGER,
    body_battery_low           INTEGER,
    body_battery_charged       INTEGER,
    body_battery_drained       INTEGER,
    avg_waking_respiration     REAL,
    moderate_intensity_minutes INTEGER,
    vigorous_intensity_minutes INTEGER,
    floors_ascended            REAL,
    sleep_seconds              INTEGER,
    raw_json                   TEXT NOT NULL,
    fetched_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS training_readiness (
    calendar_date    TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    score            INTEGER,
    level            TEXT,
    feedback_short   TEXT,
    recovery_time_m  REAL,
    acute_load       REAL,
    hrv_weekly_avg   INTEGER,
    valid_sleep      INTEGER,
    input_context    TEXT,
    raw_json         TEXT NOT NULL,
    fetched_at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (calendar_date, timestamp)
);

CREATE TABLE IF NOT EXISTS training_status (
    calendar_date              TEXT PRIMARY KEY,
    training_status            INTEGER,
    training_status_phrase     TEXT,
    fitness_trend              INTEGER,
    sport                      TEXT,
    vo2max_precise             REAL,
    vo2max_date                TEXT,
    monthly_load_aerobic_low   REAL,
    monthly_load_aerobic_high  REAL,
    monthly_load_anaerobic     REAL,
    training_balance_feedback  TEXT,
    acwr_percent               INTEGER,
    acwr_ratio                 REAL,
    acwr_status                TEXT,
    daily_load_acute           REAL,
    daily_load_chronic         REAL,
    raw_json                   TEXT NOT NULL,
    fetched_at                 TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key   TEXT PRIMARY KEY,
    content     TEXT NOT NULL,
    model       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    usage_json  TEXT
);

CREATE TABLE IF NOT EXISTS weather_cache (
    cache_key   TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS race_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id     TEXT UNIQUE,            -- legacy import dedup key; NULL on the shipped curated set
    source          TEXT NOT NULL,           -- 'personal-running-coach' (curated/shipped) | 'user'
    name            TEXT NOT NULL,
    race_date       TEXT NOT NULL,           -- ISO date
    city            TEXT,
    province        TEXT,                    -- 2-letter NL code (NB, NH, ZH, GE, OV, UT, FR, GR, DR, FL, LB, ZE, NL, but really 12 provinces)
    country_code    TEXT NOT NULL DEFAULT 'NL',
    distances_json  TEXT,                    -- JSON array [{"km": 5.0, "label": "5 km"}, ...]
    description     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_race_events_date ON race_events(race_date);
CREATE INDEX IF NOT EXISTS idx_race_events_province ON race_events(province);

CREATE TABLE IF NOT EXISTS runner_races (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id             INTEGER NOT NULL REFERENCES race_events(id) ON DELETE CASCADE,
    plan_id              INTEGER REFERENCES plans(id)               ON DELETE SET NULL,
    chosen_distance_km   REAL,
    chosen_distance_label TEXT,              -- the original label (e.g. "halve marathon")
    is_a_race            INTEGER NOT NULL DEFAULT 0,
    notes                TEXT,
    added_at             TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_runner_races_event ON runner_races(event_id);
CREATE INDEX IF NOT EXISTS idx_runner_races_plan ON runner_races(plan_id);

-- A calendar race event spliced into an active plan, replacing a planned
-- workout (see running_coach/plans/event_swap.py). Stores JSON snapshots of
-- the overwritten rows so the swap is fully reversible: `race_workout_id` is
-- the plan row that became the race (on the event's date), and
-- `displaced_workout_id` is the optional extra session (typically that
-- week's long run) that was converted to a rest day to make room.
CREATE TABLE IF NOT EXISTS plan_event_swaps (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id                 INTEGER NOT NULL REFERENCES plans(id)         ON DELETE CASCADE,
    event_id                INTEGER NOT NULL REFERENCES race_events(id)   ON DELETE CASCADE,
    race_workout_id         INTEGER NOT NULL REFERENCES plan_workouts(id) ON DELETE CASCADE,
    displaced_workout_id    INTEGER REFERENCES plan_workouts(id)          ON DELETE SET NULL,
    race_original_json      TEXT NOT NULL,   -- pre-swap fields of the race row
    displaced_original_json TEXT,            -- pre-swap fields of the displaced row
    chosen_distance_km      REAL,
    chosen_distance_label   TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_plan_event_swaps_plan ON plan_event_swaps(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_event_swaps_race_workout ON plan_event_swaps(race_workout_id);

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ingest_type   TEXT NOT NULL,
    target        TEXT,
    started_at    TEXT NOT NULL,
    completed_at  TEXT,
    success       INTEGER NOT NULL DEFAULT 0,
    rows_upserted INTEGER,
    error         TEXT
);

CREATE TABLE IF NOT EXISTS plans (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_type          TEXT NOT NULL,
    target_distance_km REAL,
    race_date          TEXT,
    target_time_s      INTEGER,
    methodology        TEXT NOT NULL,
    days_per_week      INTEGER NOT NULL,
    long_run_day       INTEGER NOT NULL,
    vdot_at_start      REAL,
    title              TEXT NOT NULL,
    notes              TEXT,
    status             TEXT NOT NULL DEFAULT 'active',
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    deactivated_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_plans_status ON plans(status);

CREATE TABLE IF NOT EXISTS app_settings (
    id                INTEGER PRIMARY KEY CHECK (id = 1),
    garmin_email      TEXT,
    -- Getting-started wizard state. On a FRESH install the row is seeded
    -- here with 'pending', so the wizard auto-opens on first dashboard
    -- visit. Existing databases instead pick up the column via the
    -- migration below, which defaults to 'completed' — so upgrading users
    -- are never shown onboarding for an app they already set up. See
    -- docs/onboarding.md.
    onboarding_status TEXT NOT NULL DEFAULT 'pending',   -- pending | dismissed | completed
    onboarding_step   TEXT NOT NULL DEFAULT 'welcome',   -- resume point
    updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
);
INSERT OR IGNORE INTO app_settings (id) VALUES (1);

CREATE TABLE IF NOT EXISTS diary_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date      TEXT NOT NULL,
    body            TEXT NOT NULL,
    mood            INTEGER,             -- user-set 1..5 (1=💀 .. 5=😄), nullable
    activity_id     INTEGER,             -- optional link to a run
    plan_workout_id INTEGER,             -- optional link to a planned workout
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (activity_id)     REFERENCES activities(activity_id)  ON DELETE SET NULL,
    FOREIGN KEY (plan_workout_id) REFERENCES plan_workouts(id)        ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_diary_entry_date ON diary_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_diary_activity_id ON diary_entries(activity_id);

CREATE TABLE IF NOT EXISTS plan_workouts (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id              INTEGER NOT NULL,
    week_number          INTEGER NOT NULL,
    week_phase           TEXT NOT NULL,
    day_of_week          INTEGER NOT NULL,
    planned_date         TEXT NOT NULL,
    workout_type         TEXT NOT NULL,
    title                TEXT NOT NULL,
    description          TEXT,
    target_distance_km   REAL,
    target_duration_s    INTEGER,
    target_pace_s_per_km INTEGER,
    actual_activity_id   INTEGER,
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_plan_workouts_plan ON plan_workouts(plan_id);
CREATE INDEX IF NOT EXISTS idx_plan_workouts_date ON plan_workouts(planned_date);
"""


def get_db_path() -> Path:
    load_dotenv()
    return Path(os.getenv("RUNNING_COACH_DB", str(DEFAULT_DB_PATH))).expanduser().resolve()


# ALTER statements applied after the schema script. Each one wrapped in try/except so
# re-running is idempotent (SQLite has no IF NOT EXISTS for ADD COLUMN).
_MIGRATIONS: list[str] = [
    "ALTER TABLE plan_workouts ADD COLUMN garmin_workout_id INTEGER",
    "ALTER TABLE plan_workouts ADD COLUMN pushed_at TEXT",
    "ALTER TABLE plan_workouts ADD COLUMN workout_structure TEXT",  # JSON
    "ALTER TABLE plan_workouts ADD COLUMN matched_at TEXT",
    "ALTER TABLE app_settings ADD COLUMN garmin_full_name TEXT",
    "ALTER TABLE activities ADD COLUMN garmin_feel INTEGER",
    "ALTER TABLE activities ADD COLUMN garmin_rpe INTEGER",
    "ALTER TABLE app_settings ADD COLUMN anthropic_api_key TEXT",
    "ALTER TABLE app_settings ADD COLUMN about_you TEXT",
    "ALTER TABLE app_settings ADD COLUMN home_lat REAL",
    "ALTER TABLE app_settings ADD COLUMN home_lon REAL",
    "ALTER TABLE app_settings ADD COLUMN home_display_name TEXT",
    "ALTER TABLE app_settings ADD COLUMN home_country_code TEXT",
    "ALTER TABLE race_events ADD COLUMN organizer_url TEXT",
    "ALTER TABLE race_events ADD COLUMN hero_image_url TEXT",
    "ALTER TABLE race_events ADD COLUMN enriched_at TEXT",
    # DEPRECATED: `theme` column no longer read since the multi-theme
    # system was consolidated to a single Tempo design. Kept in the
    # schema because SQLite ALTER TABLE doesn't reliably support
    # DROP COLUMN across versions; leaving it as dead data is cheaper
    # than the dance. Safe to actually drop in a future schema rebuild.
    "ALTER TABLE app_settings ADD COLUMN theme TEXT NOT NULL DEFAULT 'base'",
    "ALTER TABLE app_settings ADD COLUMN theme_mode TEXT NOT NULL DEFAULT 'auto'",
    # User-picked workout weekdays — CSV of day-of-week ints (Mon=0..Sun=6).
    # Length must equal `days_per_week` and include `long_run_day`. NULL on
    # rows from before this column existed; the generator falls back to the
    # legacy fixed slot pattern in that case.
    "ALTER TABLE plans ADD COLUMN workout_days TEXT",
    # UI + LLM coach language. 'en' = English (default, source of truth),
    # 'nl' = Nederlands. See running_coach/i18n.py for how it's resolved.
    "ALTER TABLE app_settings ADD COLUMN language TEXT NOT NULL DEFAULT 'en'",
    # Toggle: add optional bodyweight core/strength sessions on rest days.
    # When 1, the scheduler auto-assigns sessions from `strength_workouts`
    # to future rest days; when 0, future sessions are cleared (past stays
    # for history). See running_coach/strength/ for the library + rotation.
    "ALTER TABLE plans ADD COLUMN include_optional_strength INTEGER NOT NULL DEFAULT 0",
    # Garmin-push state on strength sessions — mirrors the analogous columns
    # on plan_workouts. `garmin_workout_id` is Garmin's `workoutId` from the
    # upload response; `pushed_at` records when we last shipped it to the
    # watch. Both cleared when the runner unpushes or when we delete + re-push.
    "ALTER TABLE plan_strength_sessions ADD COLUMN garmin_workout_id INTEGER",
    "ALTER TABLE plan_strength_sessions ADD COLUMN pushed_at TEXT",
    # `actual_activity_id` is the matched Garmin "strength_training" activity
    # FK to activities.activity_id. Set by the strength matcher (see
    # `running_coach/strength/matcher.py`) when Garmin's activity payload
    # echoes our pushed workoutId back. Completion is also stamped on
    # `completed_at` at the same time. NULL on unmatched / not-yet-done.
    "ALTER TABLE plan_strength_sessions ADD COLUMN actual_activity_id INTEGER",
    # Curated event calendar cleanup: drop all hardloopkalender provenance now
    # that the app ships a frozen, self-branded set. Relabel the source, clear
    # the legacy import dedup key, and drop the `url` column entirely (the
    # organiser site lives in `organizer_url`). Idempotent: the UPDATEs match
    # nothing on re-run, and the DROP raises "no such column" the second time,
    # which `_apply_migrations` swallows.
    "UPDATE race_events SET source = 'personal-running-coach' WHERE source = 'hardloopkalender'",
    "UPDATE race_events SET external_id = NULL WHERE external_id IS NOT NULL",
    "ALTER TABLE race_events DROP COLUMN url",
    # Multi-provider LLM coach. `llm_provider` is the active selection
    # ('anthropic' / 'openai' / 'gemini'); existing rows default to
    # 'anthropic' to preserve current behavior on migration. Each
    # provider has its own API-key column — switching provider never
    # clears another provider's key (or `llm_cache`) so the user can
    # flip back without re-entering credentials.
    "ALTER TABLE app_settings ADD COLUMN llm_provider TEXT NOT NULL DEFAULT 'anthropic'",
    "ALTER TABLE app_settings ADD COLUMN openai_api_key TEXT",
    "ALTER TABLE app_settings ADD COLUMN gemini_api_key TEXT",
    # Garmin's race-time predictions for the canonical distances —
    # regression-based numbers calibrated against millions of finishers,
    # more honest for amateurs than Daniels' physiological formula
    # (especially at marathon distance). Synced once per day alongside
    # training_status. Each value is the predicted finish in SECONDS.
    "ALTER TABLE training_status ADD COLUMN race_pred_5k_s INTEGER",
    "ALTER TABLE training_status ADD COLUMN race_pred_10k_s INTEGER",
    "ALTER TABLE training_status ADD COLUMN race_pred_half_s INTEGER",
    "ALTER TABLE training_status ADD COLUMN race_pred_marathon_s INTEGER",
    # Auto-VDOT-suggestion state — per activity. Once an activity has
    # been used to (a) apply a VDOT update to the plan or (b) explicitly
    # dismissed, we never re-suggest off it. Both columns nullable.
    "ALTER TABLE activities ADD COLUMN vdot_suggestion_dismissed_at TEXT",
    "ALTER TABLE activities ADD COLUMN vdot_suggestion_applied_at TEXT",
    # Body / wellbeing — privacy opt-out for the LLM coach. When 0, the
    # body block is omitted from the cached profile prompt. Default 1
    # (opted in) so existing runners get the smarter coach by default;
    # the Settings card lets anyone turn it off.
    "ALTER TABLE app_settings ADD COLUMN include_body_in_llm INTEGER NOT NULL DEFAULT 1",
    # Body profile — physiological inputs the Fuel feature needs to turn
    # calorie burn into eat/drink targets. Manual entry is first-class
    # (the feature works with zero Garmin); the Settings card offers an
    # optional Garmin pre-fill. Birth *year* (not full DOB) is enough for
    # the BMR age term and is less sensitive. `sex` drives the BMR
    # constant + sweat-rate. `diet_pref` is reserved for Phase 2 meal
    # assembly. See docs/nutrition-fueling.md.
    "ALTER TABLE app_settings ADD COLUMN weight_kg REAL",
    "ALTER TABLE app_settings ADD COLUMN height_cm REAL",
    "ALTER TABLE app_settings ADD COLUMN birth_year INTEGER",
    "ALTER TABLE app_settings ADD COLUMN sex TEXT",
    "ALTER TABLE app_settings ADD COLUMN diet_pref TEXT",
    "ALTER TABLE app_settings ADD COLUMN body_profile_updated_at TEXT",
    # Getting-started wizard. Added to EXISTING databases with a
    # 'completed' default so upgrading users (who already configured the
    # app) never see onboarding. Fresh installs get the column from the
    # base SCHEMA above with a 'pending' default instead, which is what
    # makes the wizard auto-open on first run. See docs/onboarding.md.
    "ALTER TABLE app_settings ADD COLUMN onboarding_status TEXT NOT NULL DEFAULT 'completed'",
    "ALTER TABLE app_settings ADD COLUMN onboarding_step TEXT NOT NULL DEFAULT 'welcome'",
    # Methodology sub-plan selector (e.g. Higdon experience tier). NULL for
    # plans created before this column / for methodologies without variants;
    # the engine treats NULL as its own default. See docs/higdon.md.
    "ALTER TABLE plans ADD COLUMN variant TEXT",
    # Manual fitness baseline — the Garmin-less seed for plan generation.
    # `manual_vdot` is estimated from a recent race result (Daniels formula);
    # `manual_vdot_note` records the human basis ("10 km in 52:30") for
    # display. `manual_weekly_km` is self-reported volume. Garmin-measured
    # data, when present, still wins — see plans/service.get_plan_seed.
    "ALTER TABLE app_settings ADD COLUMN manual_vdot REAL",
    "ALTER TABLE app_settings ADD COLUMN manual_vdot_note TEXT",
    "ALTER TABLE app_settings ADD COLUMN manual_weekly_km REAL",
    # 1 = the runner explicitly chose to use the app without Garmin (wizard
    # "I don't use Garmin"). The dashboard then stops redirecting signed-out
    # visits to /auth. Cleared again on a successful Garmin login.
    "ALTER TABLE app_settings ADD COLUMN garmin_optout INTEGER NOT NULL DEFAULT 0",
    # Self-assessment for plan recommendation: "Can you currently run
    # 10 minutes non-stop?" Tri-state — NULL = never asked (existing users),
    # 1 = yes, 0 = not yet. Read by plans/recommend.py.
    "ALTER TABLE app_settings ADD COLUMN can_run_10min INTEGER",
]


# ────────────────────────────────────────────────────────────────────
# Strength sessions schema — appended to SCHEMA at module load. Tables
# created alongside the running ones so `connect()` brings them up in
# one shot.

_STRENGTH_SCHEMA = """
-- Library of canonical bodyweight core/strength sessions. Seeded from
-- running_coach/strength/library.py on first run when empty. `structure`
-- is the JSON blob describing the blocks → exercises → supersets shape
-- that the detail modal renders (see strength/library.py for the shape).
CREATE TABLE IF NOT EXISTS strength_workouts (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    slug              TEXT UNIQUE NOT NULL,
    title             TEXT NOT NULL,
    category          TEXT NOT NULL,         -- 'core+hamstrings', 'full_body', 'hip_stability', 'plyo', 'recovery'
    duration_min_lo   INTEGER NOT NULL,
    duration_min_hi   INTEGER NOT NULL,
    equipment         TEXT NOT NULL DEFAULT 'bodyweight',
    notes             TEXT,
    structure         TEXT NOT NULL,         -- JSON: {"blocks": [...]}
    created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Per-plan schedule: links a strength workout to a rest day on a plan.
-- Optional by definition — every row here is *additive* to the plan's
-- rest day, never replacing the running schedule. `completed_at` set
-- when the runner marks done; null otherwise.
CREATE TABLE IF NOT EXISTS plan_strength_sessions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id             INTEGER NOT NULL,
    strength_workout_id INTEGER NOT NULL,
    planned_date        TEXT NOT NULL,
    completed_at        TEXT,
    notes               TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(plan_id, planned_date),
    FOREIGN KEY (plan_id) REFERENCES plans(id) ON DELETE CASCADE,
    FOREIGN KEY (strength_workout_id) REFERENCES strength_workouts(id)
);
CREATE INDEX IF NOT EXISTS idx_plan_strength_sessions_plan_date
    ON plan_strength_sessions(plan_id, planned_date);
"""

SCHEMA = SCHEMA + _STRENGTH_SCHEMA


# Body / wellbeing check-in — interactive body-map where the runner logs
# how their body actually feels. Active issues feed the daily coach
# prescription, strength-session avoidance (v1.1), and the post-marathon
# Day-1-2 triage. See docs/body-wellbeing-checkin.md for the design brief.

_BODY_SCHEMA = """
-- One row per logged issue. Current severity is the most-recent
-- body_severity_log row for this issue; we never denormalize. `side`
-- is 'left'/'right' for paired regions or 'midline' for neck/back.
-- `resolved_at` NULL means open; setting it (and `resolved_reason`)
-- soft-closes the issue. Schema-level CHECK constraints catch any
-- bad enum value at write time.
CREATE TABLE IF NOT EXISTS body_issues (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    region          TEXT    NOT NULL,
    side            TEXT    NOT NULL CHECK (side IN ('left','right','midline')),
    issue_type      TEXT    NOT NULL CHECK (issue_type IN
                        ('soreness','tight','sharp','dull_ache','numb','known_injury')),
    structure_name  TEXT,
    note            TEXT,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    resolved_at     TEXT,
    resolved_reason TEXT CHECK (resolved_reason IN
                        ('manual','auto_idle','severity_zero') OR resolved_reason IS NULL),
    last_nudge_at   TEXT,
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_body_issues_active
    ON body_issues(resolved_at) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_body_issues_region ON body_issues(region, side);
CREATE INDEX IF NOT EXISTS idx_body_issues_created ON body_issues(created_at);

-- Severity audit log. Every severity update appends here, including the
-- initial value at creation time. Trend curves + the
-- severity-zero-for-2-days soft-prompt logic read from this table.
-- ON DELETE CASCADE keeps the log clean if an issue is ever hard-deleted
-- (not a normal flow — UI does soft "resolve").
CREATE TABLE IF NOT EXISTS body_severity_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id     INTEGER NOT NULL REFERENCES body_issues(id) ON DELETE CASCADE,
    severity     INTEGER NOT NULL CHECK (severity BETWEEN 0 AND 10),
    recorded_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_body_severity_issue
    ON body_severity_log(issue_id, recorded_at);

-- "I'm all good right now" timestamps from the dashboard daily-check-in
-- prompt. Useful negative-case data: N consecutive clear days is itself
-- a signal the LLM can lean on ("12 days clear · 0 active issues").
CREATE TABLE IF NOT EXISTS body_clear_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_body_clear_date ON body_clear_logs(recorded_at);
"""

SCHEMA = SCHEMA + _BODY_SCHEMA


def _apply_migrations(conn: sqlite3.Connection) -> None:
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError as exc:
            msg = str(exc).lower()
            # "duplicate column name" → ADD COLUMN already applied.
            # "no such column"        → DROP COLUMN already applied (idempotent re-run).
            if "duplicate column name" in msg or "no such column" in msg:
                continue
            raise
    conn.commit()


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open the DB, ensuring the schema exists. Caller is responsible for closing."""
    if path is None:
        path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # Concurrency PRAGMAs:
    #   - WAL journal mode lets many readers proceed concurrently with a
    #     single writer instead of the default rollback journal's
    #     exclusive locking. One-time DB-file setting; idempotent re-apply.
    #   - busy_timeout makes contending statements wait up to N ms for the
    #     lock rather than failing immediately (default is 0).
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    # Schema apply runs once per DB-file per process. Re-running
    # `executescript(SCHEMA)` on every connect was contending with
    # in-flight write transactions (long syncs) and causing readers
    # to fail with "database is locked" — busy_timeout alone wasn't
    # enough since a single sync transaction can outlast 5s.
    if path not in _SCHEMA_INITIALIZED:
        with _SCHEMA_LOCK:
            if path not in _SCHEMA_INITIALIZED:
                conn.executescript(SCHEMA)
                _apply_migrations(conn)
                _SCHEMA_INITIALIZED.add(path)
    # Seed the strength-workout library on first run. Idempotent: only
    # runs when `strength_workouts` is empty, so re-opening is cheap.
    try:
        from .strength import service as _strength_service
        _strength_service.seed_library_if_empty(conn)
    except Exception:  # noqa: BLE001 — seeding shouldn't break the app open
        pass
    # Seed the curated race calendar on first run (empty table only), so a
    # fresh clone ships with a populated /calendar. Idempotent + safe.
    try:
        from . import race_calendar as _race_calendar
        _race_calendar.seed_events_if_empty(conn)
    except Exception:  # noqa: BLE001 — same posture as the strength seeder
        pass
    return conn
