"""Build a demo database for screenshots and local exploration.

Screenshots of a real instance would publish real health data — paces, race
goals, diary entries, body check-ins. This builds a self-contained database
from synthetic data instead, so the README can show the app without showing
anyone's training history.

It is also the honest way to keep screenshots current: regenerate the
database, retake the shots, rather than cropping an old image.

    .venv\\Scripts\\python.exe -m scripts.seed_demo
    $env:RUNNING_COACH_DB = "$PWD\\data\\demo.db"
    .venv\\Scripts\\python.exe -m runsphera.web

The runner is fictional and the numbers are plausible rather than copied
from anyone: VDOT 46 puts the easy pace near 5:50/km, which is an ordinary
mid-pack amateur. Nothing here touches the real database unless you point
``--db`` at it, which the script refuses to do.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runsphera import settings as app_settings  # noqa: E402
from runsphera.db import connect, get_db_path  # noqa: E402
from runsphera.plans import service as plan_service  # noqa: E402
from runsphera.plans.matcher import match_plan_workouts  # noqa: E402

# A fictional runner. Deliberately not a real name from this project.
RUNNER_NAME = "Alex Doe"
VDOT = 46.0
RACE_NAME = "City Half Marathon"
HOME = "Rotterdam, Netherlands"

# Weeks of activity history before today. Enough for the dashboard charts and
# the acute/chronic load ratio to have something real to say.
HISTORY_WEEKS = 10

_rng = random.Random(20261025)  # fixed seed: same demo every run


def _easy_pace_s() -> int:
    """Daniels E pace for VDOT 46, near enough for synthetic runs."""
    from runsphera.plans.daniels import _paces_for_vdot
    return _paces_for_vdot(VDOT)["E"]


def _activity(conn: sqlite3.Connection, when: datetime, km: float,
              pace_s: int, name: str, *, quality: bool = False) -> int:
    """One synthetic run. Returns its activity_id."""
    duration = km * pace_s
    aid = int(when.timestamp())
    avg_hr = (158 if quality else 141) + _rng.randint(-4, 4)
    # Zone split: quality sessions sit higher for longer.
    z = ([0.10, 0.25, 0.30, 0.28, 0.07] if quality
         else [0.18, 0.55, 0.22, 0.05, 0.00])
    conn.execute(
        """INSERT OR REPLACE INTO activities
           (activity_id, activity_name, activity_type, start_time_local,
            start_time_gmt, duration_s, moving_duration_s, distance_m,
            elevation_gain_m, avg_speed_mps, calories, avg_hr, max_hr,
            avg_cadence_spm, aerobic_te, anaerobic_te, training_load, vo2max,
            hr_zone_1_s, hr_zone_2_s, hr_zone_3_s, hr_zone_4_s, hr_zone_5_s,
            raw_json)
           VALUES (?,?,'running',?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            aid, name, when.isoformat(sep=" ", timespec="seconds"),
            when.isoformat(sep=" ", timespec="seconds"),
            duration, duration, km * 1000.0,
            round(km * _rng.uniform(4, 9), 1),
            1000.0 / pace_s, km * 62.0,
            avg_hr, avg_hr + _rng.randint(8, 16),
            round(_rng.uniform(168, 176), 1),
            round(3.4 if quality else 2.6, 1),
            round(1.8 if quality else 0.4, 1),
            round(km * (9.5 if quality else 6.0), 1),
            None,  # per-activity vo2max: Garmin only fills this sometimes
            *[round(duration * f, 1) for f in z],
            "{}",
        ),
    )
    return aid


def _daily_metrics(conn: sqlite3.Connection, day: date, ran: bool) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO daily_metrics
           (calendar_date, total_steps, resting_hr, seven_day_avg_resting_hr,
            avg_stress, body_battery_high, body_battery_low, raw_json)
           VALUES (?,?,?,?,?,?,?,'{}')""",
        (
            day.isoformat(),
            _rng.randint(11000, 16000) if ran else _rng.randint(5000, 8000),
            _rng.randint(47, 52), 49,
            _rng.randint(22, 38),
            _rng.randint(82, 96), _rng.randint(14, 28),
        ),
    )


def _readiness(conn: sqlite3.Connection, day: date, score: int | None = None) -> None:
    """Garmin's daily training-readiness score.

    Without a row here the dashboard's readiness tile renders an em dash and
    the race-readiness breakdown has nothing to weigh.
    """
    score = score if score is not None else _rng.randint(62, 88)
    level = ("high" if score >= 75 else "moderate" if score >= 50 else "low")
    conn.execute(
        """INSERT OR REPLACE INTO training_readiness
           (calendar_date, timestamp, score, level, feedback_short,
            recovery_time_m, hrv_weekly_avg, valid_sleep, raw_json)
           VALUES (?,?,?,?,?,?,?,1,'{}')""",
        (day.isoformat(), f"{day.isoformat()}T06:30:00",
         score, level,
         "READY" if score >= 75 else "MODERATE",
         float(_rng.randint(0, 14) * 60), _rng.randint(52, 68)),
    )


def _training_status(conn: sqlite3.Connection, day: date,
                     acute: float, chronic: float) -> None:
    ratio = round(acute / chronic, 2) if chronic else 1.0
    status = "productive" if 0.8 <= ratio <= 1.3 else "maintaining"
    conn.execute(
        """INSERT OR REPLACE INTO training_status
           (calendar_date, training_status_phrase, vo2max_precise, vo2max_date,
            acwr_ratio, acwr_percent, acwr_status, daily_load_acute,
            daily_load_chronic, raw_json)
           VALUES (?,?,?,?,?,?,?,?,?,'{}')""",
        # create_plan reads VDOT from here (get_plan_seed -> _garmin_vdot),
        # so keep it equal to VDOT or the generated plan won't match the
        # paces this script claims the demo runner trains at.
        (day.isoformat(), status, VDOT, day.isoformat(),
         ratio, int(ratio * 100),
         "optimal" if 0.8 <= ratio <= 1.3 else "low",
         round(acute, 1), round(chronic, 1)),
    )


def seed(db_path: Path) -> None:
    conn = connect(db_path)
    today = date.today()
    easy = _easy_pace_s()

    # ── the runner ───────────────────────────────────────────────────────
    app_settings.set_garmin_full_name(conn, RUNNER_NAME)
    app_settings.set_about_you(
        conn,
        "Building toward a half marathon. Work travel midweek, so that day "
        "is usually a rest or an easy shakeout.",
    )
    try:
        app_settings.set_home_location(conn, HOME, 51.92, 4.48)
    except TypeError:
        pass  # signature differs; location is cosmetic for screenshots

    # A seeded instance is not a fresh install: skip the first-run wizard so
    # the dashboard isn't covered by a welcome dialog.
    app_settings.set_onboarding_status(conn, "completed")

    # The header reads "no data yet — click Sync from Garmin" until an ingest
    # has been recorded. Synthetic history is still history.
    conn.execute(
        """INSERT INTO ingestion_runs
           (ingest_type, target, started_at, completed_at, success, rows_upserted)
           VALUES ('full', 'demo', datetime('now','-1 hour'),
                   datetime('now','-1 hour'), 1, ?)""",
        (HISTORY_WEEKS * 4,),
    )

    # ── the training week ────────────────────────────────────────────────
    # Anchor the long run on *today's* weekday. The dashboard's flagship
    # aside — and with it the race countdown and readiness breakdown — only
    # renders on a day that has a session, so a demo seeded on a rest day
    # would quietly lose the best card on the page. Anchoring keeps the
    # screenshots reproducible whatever day the script runs.
    LONG = today.weekday()
    QUALITY = (LONG + 3) % 7          # mid-week, well clear of the long run
    EASY_A = (LONG + 1) % 7
    EASY_B = (LONG + 5) % 7
    WORKOUT_DAYS = sorted({LONG, QUALITY, EASY_A, EASY_B})

    # ── activity history ─────────────────────────────────────────────────
    acute = chronic = 0.0
    for back in range(HISTORY_WEEKS * 7, 0, -1):
        day = today - timedelta(days=back)
        dow = day.weekday()
        load = 0.0
        if dow in (EASY_A, EASY_B):
            km = round(_rng.uniform(7, 9), 1)
            _activity(conn, datetime.combine(day, datetime.min.time().replace(hour=18)),
                      km, easy + _rng.randint(-6, 10), "Evening Run")
            load = km * 6.0
        elif dow == QUALITY:
            km = round(_rng.uniform(8, 11), 1)
            _activity(conn, datetime.combine(day, datetime.min.time().replace(hour=18)),
                      km, easy - _rng.randint(35, 55), "Threshold Session",
                      quality=True)
            load = km * 9.5
        elif dow == LONG:
            km = round(_rng.uniform(14, 19), 1)
            _activity(conn, datetime.combine(day, datetime.min.time().replace(hour=9)),
                      km, easy + _rng.randint(0, 12), "Long Run")
            load = km * 6.5
        _daily_metrics(conn, day, ran=load > 0)
        _readiness(conn, day)
        acute = acute * 0.87 + load * 0.13
        chronic = chronic * 0.97 + load * 0.03
        _training_status(conn, day, acute, chronic)
    _daily_metrics(conn, today, ran=False)
    _readiness(conn, today, score=78)  # today's tile gets a settled number
    _training_status(conn, today, acute, chronic)
    conn.commit()

    # ── the plan ─────────────────────────────────────────────────────────
    # Start it in the past so the plans page shows completed weeks, an
    # in-progress week, and upcoming ones — the interesting state.
    start = today - timedelta(days=today.weekday() + 28)
    race = start + timedelta(weeks=14) - timedelta(days=1)
    plan_id = plan_service.create_plan(
        conn,
        goal_type="half_marathon",
        methodology_id="daniels",
        race_date=race,
        target_time_s=None,
        days_per_week=len(WORKOUT_DAYS),
        long_run_day=LONG,
        workout_days=WORKOUT_DAYS,
        title=RACE_NAME,
        start_date=start,
    )  # VDOT and weekly baseline are derived from the seeded history above
    conn.commit()

    # Match history to the plan so adherence pills and execution scores render.
    match_plan_workouts(conn, plan_id)
    conn.commit()

    # ── the A-race ───────────────────────────────────────────────────────
    # The dashboard countdown card only appears when the active plan has a
    # linked race (race_for_active_plan). Without this the flagship aside
    # falls back to the daily tip and the readiness scoring never shows.
    conn.execute(
        """INSERT INTO race_events
           (source, name, race_date, city, country_code, distances_json,
            description)
           VALUES ('user', ?, ?, 'Rotterdam', 'NL', ?, ?)""",
        (RACE_NAME, race.isoformat(),
         json.dumps([{"km": 21.0975, "label": "half marathon"}]),
         "A flat half along the river — a fast course and the goal "
         "race this block was built around."),
    )
    event_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.execute(
        """INSERT INTO runner_races
           (event_id, plan_id, chosen_distance_km, chosen_distance_label,
            is_a_race)
           VALUES (?, ?, 21.0975, 'half marathon', 1)""",
        (event_id, plan_id),
    )
    conn.commit()

    # ── a couple of diary entries ────────────────────────────────────────
    for back, mood, note in (
        (2, 4, "Legs felt good. Held the threshold blocks without forcing it."),
        (6, 3, "Windy out by the river — ran by effort rather than pace."),
    ):
        conn.execute(
            "INSERT INTO diary_entries (entry_date, mood, body) VALUES (?,?,?)",
            ((today - timedelta(days=back)).isoformat(), mood, note),
        )
    conn.commit()

    n_act = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    n_pw = conn.execute("SELECT COUNT(*) FROM plan_workouts WHERE plan_id = ?",
                        (plan_id,)).fetchone()[0]
    n_done = conn.execute(
        "SELECT COUNT(*) FROM plan_workouts WHERE plan_id = ? "
        "AND actual_activity_id IS NOT NULL", (plan_id,)).fetchone()[0]
    conn.close()

    print(f"  runner:     {RUNNER_NAME} (VDOT {VDOT:g})")
    print(f"  activities: {n_act}")
    print(f"  plan:       {RACE_NAME} — {n_pw} workouts, {n_done} matched")
    print(f"  database:   {db_path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/demo.db",
                    help="where to write (default: data/demo.db)")
    args = ap.parse_args()

    target = Path(args.db).expanduser().resolve()
    if target == get_db_path().resolve():
        print("Refusing to seed over the configured database.", file=sys.stderr)
        print(f"  {target}", file=sys.stderr)
        return 1
    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    print("Seeding demo database...")
    seed(target)
    print("\nRun it:")
    print(f'  $env:RUNNING_COACH_DB = "{target}"')
    print("  .venv\\Scripts\\python.exe -m runsphera.web")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
