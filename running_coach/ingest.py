"""Pull Garmin Connect data into the local SQLite DB.

Idempotent: every upsert is keyed on the natural PK (activity_id, calendar_date,
or (date, timestamp)), so re-running just refreshes existing rows. Per-call
errors are logged and skipped — one bad day doesn't kill the whole run.

Usage:

    python -m running_coach.ingest                # default: 30 activities, 14 days
    python -m running_coach.ingest --days 60      # pull more history
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from typing import Any

from running_coach.db import connect
from running_coach.garmin import get_client
from running_coach.plans import matcher as plan_matcher


def _get(d: Any, *path: str, default: Any = None) -> Any:
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def _activity_row(act: dict) -> dict[str, Any]:
    return {
        "activity_id": act["activityId"],
        "activity_name": act.get("activityName"),
        "activity_type": _get(act, "activityType", "typeKey", default="unknown"),
        "event_type": _get(act, "eventType", "typeKey"),
        "start_time_local": act["startTimeLocal"],
        "start_time_gmt": act["startTimeGMT"],
        "end_time_gmt": act.get("endTimeGMT"),
        "duration_s": act.get("duration"),
        "moving_duration_s": act.get("movingDuration"),
        "distance_m": act.get("distance"),
        "elevation_gain_m": act.get("elevationGain"),
        "elevation_loss_m": act.get("elevationLoss"),
        "avg_speed_mps": act.get("averageSpeed"),
        "max_speed_mps": act.get("maxSpeed"),
        "calories": act.get("calories"),
        "avg_hr": act.get("averageHR"),
        "max_hr": act.get("maxHR"),
        "avg_cadence_spm": act.get("averageRunningCadenceInStepsPerMinute"),
        "max_cadence_spm": act.get("maxRunningCadenceInStepsPerMinute"),
        "steps": act.get("steps"),
        "avg_power_w": act.get("avgPower"),
        "max_power_w": act.get("maxPower"),
        "aerobic_te": act.get("aerobicTrainingEffect"),
        "anaerobic_te": act.get("anaerobicTrainingEffect"),
        "training_load": act.get("activityTrainingLoad"),
        "vo2max": act.get("vO2MaxValue"),
        "location_name": act.get("locationName"),
        "min_temperature_c": act.get("minTemperature"),
        "max_temperature_c": act.get("maxTemperature"),
        "hr_zone_1_s": act.get("hrTimeInZone_1"),
        "hr_zone_2_s": act.get("hrTimeInZone_2"),
        "hr_zone_3_s": act.get("hrTimeInZone_3"),
        "hr_zone_4_s": act.get("hrTimeInZone_4"),
        "hr_zone_5_s": act.get("hrTimeInZone_5"),
        "fastest_1k_s": act.get("fastestSplit_1000"),
        "fastest_mile_s": act.get("fastestSplit_1609"),
        "fastest_5k_s": act.get("fastestSplit_5000"),
        "fastest_10k_s": act.get("fastestSplit_10000"),
        "fastest_half_s": act.get("fastestSplit_21098"),
        "body_battery_delta": act.get("differenceBodyBattery"),
        "raw_json": json.dumps(act),
    }


def _lap_row(activity_id: int, lap: dict) -> dict[str, Any] | None:
    """Map a single lapDTO from Garmin's /activity/{id}/splits response to our
    row schema. Returns None when the lap has no `lapIndex` — that field is
    Garmin's natural per-activity key and we need it for the PK.
    """
    lap_index = lap.get("lapIndex")
    if lap_index is None:
        return None
    return {
        "activity_id":       activity_id,
        "lap_index":         int(lap_index),
        "intensity_type":    lap.get("intensityType"),
        "distance_m":        lap.get("distance"),
        "duration_s":        lap.get("duration"),
        "moving_duration_s": lap.get("movingDuration"),
        "avg_speed_mps":     lap.get("averageSpeed"),
        "max_speed_mps":     lap.get("maxSpeed"),
        "avg_hr":            lap.get("averageHR"),
        "max_hr":            lap.get("maxHR"),
        "elevation_gain_m":  lap.get("elevationGain"),
        "elevation_loss_m":  lap.get("elevationLoss"),
        "avg_cadence_spm":   lap.get("averageRunCadence") or lap.get("averageCadence"),
        "avg_power_w":       lap.get("averagePower"),
        "avg_temperature_c": lap.get("averageTemperature"),
        "start_time_local":  lap.get("startTimeLocal"),
        "raw_json":          json.dumps(lap),
    }


def _daily_metrics_row(stats: dict | None) -> dict[str, Any] | None:
    if not stats or not stats.get("calendarDate"):
        return None
    return {
        "calendar_date": stats["calendarDate"],
        "total_steps": stats.get("totalSteps"),
        "total_distance_m": stats.get("totalDistanceMeters"),
        "total_kcal": stats.get("totalKilocalories"),
        "active_kcal": stats.get("activeKilocalories"),
        "bmr_kcal": stats.get("bmrKilocalories"),
        "resting_hr": stats.get("restingHeartRate"),
        "seven_day_avg_resting_hr": stats.get("lastSevenDaysAvgRestingHeartRate"),
        "min_hr": stats.get("minHeartRate"),
        "max_hr": stats.get("maxHeartRate"),
        "avg_stress": stats.get("averageStressLevel"),
        "max_stress": stats.get("maxStressLevel"),
        "body_battery_high": stats.get("bodyBatteryHighestValue"),
        "body_battery_low": stats.get("bodyBatteryLowestValue"),
        "body_battery_charged": stats.get("bodyBatteryChargedValue"),
        "body_battery_drained": stats.get("bodyBatteryDrainedValue"),
        "avg_waking_respiration": stats.get("avgWakingRespirationValue"),
        "moderate_intensity_minutes": stats.get("moderateIntensityMinutes"),
        "vigorous_intensity_minutes": stats.get("vigorousIntensityMinutes"),
        "floors_ascended": stats.get("floorsAscended"),
        "sleep_seconds": stats.get("sleepingSeconds"),
        "raw_json": json.dumps(stats),
    }


def _readiness_rows(payload: list[dict] | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    rows: list[dict[str, Any]] = []
    for r in payload:
        if not (r.get("calendarDate") and r.get("timestamp")):
            continue
        rows.append({
            "calendar_date": r["calendarDate"],
            "timestamp": r["timestamp"],
            "score": r.get("score"),
            "level": r.get("level"),
            "feedback_short": r.get("feedbackShort"),
            "recovery_time_m": r.get("recoveryTime"),
            "acute_load": r.get("acuteLoad"),
            "hrv_weekly_avg": r.get("hrvWeeklyAverage"),
            "valid_sleep": 1 if r.get("validSleep") else 0,
            "input_context": r.get("inputContext"),
            "raw_json": json.dumps(r),
        })
    return rows


def _race_predictions_row(payload: dict | None) -> dict[str, Any] | None:
    """Extract Garmin's race-prediction snapshot (5k/10k/half/marathon
    finish times in seconds) for upsert into `training_status`.

    Garmin's `/personal-record-service/personal-record/prediction/race` is
    a regression model on actual runner outcomes, calibrated against
    millions of finishers — more honest for amateurs at marathon
    distance than the physiological Daniels formula. Returns None when
    the payload is empty / shaped unexpectedly so the ingest step
    silently falls back to the existing training_status data."""
    if not payload or not payload.get("calendarDate"):
        return None
    return {
        "calendar_date":          payload["calendarDate"],
        "race_pred_5k_s":         payload.get("time5K"),
        "race_pred_10k_s":        payload.get("time10K"),
        "race_pred_half_s":       payload.get("timeHalfMarathon"),
        "race_pred_marathon_s":   payload.get("timeMarathon"),
    }


def _training_status_row(payload: dict | None) -> dict[str, Any] | None:
    """Take the snapshot's own calendarDate as PK so repeat queries are no-op upserts."""
    if not payload:
        return None
    latest_map = _get(payload, "mostRecentTrainingStatus", "latestTrainingStatusData") or {}
    device_data = next(iter(latest_map.values()), None)
    if not device_data or not device_data.get("calendarDate"):
        return None

    load_map = _get(payload, "mostRecentTrainingLoadBalance", "metricsTrainingLoadBalanceDTOMap") or {}
    load_data = next(iter(load_map.values()), {}) if load_map else {}
    acwr = _get(device_data, "acuteTrainingLoadDTO") or {}

    return {
        "calendar_date": device_data["calendarDate"],
        "training_status": device_data.get("trainingStatus"),
        "training_status_phrase": device_data.get("trainingStatusFeedbackPhrase"),
        "fitness_trend": device_data.get("fitnessTrend"),
        "sport": device_data.get("sport"),
        "vo2max_precise": _get(payload, "mostRecentVO2Max", "generic", "vo2MaxPreciseValue"),
        "vo2max_date": _get(payload, "mostRecentVO2Max", "generic", "calendarDate"),
        "monthly_load_aerobic_low": load_data.get("monthlyLoadAerobicLow"),
        "monthly_load_aerobic_high": load_data.get("monthlyLoadAerobicHigh"),
        "monthly_load_anaerobic": load_data.get("monthlyLoadAnaerobic"),
        "training_balance_feedback": load_data.get("trainingBalanceFeedbackPhrase"),
        "acwr_percent": acwr.get("acwrPercent"),
        "acwr_ratio": acwr.get("dailyAcuteChronicWorkloadRatio"),
        "acwr_status": acwr.get("acwrStatus"),
        "daily_load_acute": acwr.get("dailyTrainingLoadAcute"),
        "daily_load_chronic": acwr.get("dailyTrainingLoadChronic"),
        "raw_json": json.dumps(payload),
    }


def _upsert(conn: sqlite3.Connection, table: str, row: dict[str, Any], pk: tuple[str, ...]) -> None:
    cols = list(row.keys())
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in cols if c not in pk)
    pk_list = ", ".join(pk)
    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk_list}) DO UPDATE SET {update_clause}, "
        f"fetched_at = datetime('now')"
    )
    conn.execute(sql, row)


def _log_run(
    conn: sqlite3.Connection,
    ingest_type: str,
    target: str | None,
    started_at: str,
    rows: int,
    error: str | None,
) -> None:
    conn.execute(
        "INSERT INTO ingestion_runs"
        "(ingest_type, target, started_at, completed_at, success, rows_upserted, error)"
        " VALUES (?, ?, ?, datetime('now'), ?, ?, ?)",
        (ingest_type, target, started_at, 1 if error is None else 0, rows, error),
    )


def _fetch_and_store_laps(
    conn: sqlite3.Connection,
    client,
    activity_id: int,
) -> int:
    """Pull per-lap splits for one activity and upsert them. Idempotent: if any
    laps for this activity already exist in the DB, skip the fetch entirely
    (Garmin lap data doesn't change after upload, so re-pulling is wasted
    bandwidth). Returns the number of lap rows upserted (0 on skip or fetch
    failure)."""
    existing = conn.execute(
        "SELECT 1 FROM activity_laps WHERE activity_id = ? LIMIT 1",
        (activity_id,),
    ).fetchone()
    if existing:
        return 0
    try:
        payload = client.get_activity_splits(str(activity_id))
    except Exception as exc:  # noqa: BLE001 — fail-soft; activity row still useful without laps
        print(f"  laps {activity_id}: {exc}", file=sys.stderr)
        return 0
    laps = payload.get("lapDTOs") if isinstance(payload, dict) else None
    if not laps:
        return 0
    n = 0
    for lap in laps:
        row = _lap_row(activity_id, lap)
        if row is None:
            continue
        try:
            _upsert(conn, "activity_laps", row, pk=("activity_id", "lap_index"))
            n += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  lap upsert failed (activity {activity_id}, lap {row['lap_index']}): {exc}", file=sys.stderr)
    return n


def ingest_activities(conn: sqlite3.Connection, client, limit: int) -> int:
    started = datetime.now(timezone.utc).isoformat()
    try:
        activities = client.get_activities(0, limit)
    except Exception as exc:
        _log_run(conn, "activities", f"last {limit}", started, 0, repr(exc))
        conn.commit()
        raise

    count = 0
    lap_count = 0
    for act in activities:
        try:
            _upsert(conn, "activities", _activity_row(act), pk=("activity_id",))
            count += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  failed to upsert activity {act.get('activityId')}: {exc}", file=sys.stderr)
            continue
        # Pull laps for running activities only — the coach reaction only uses
        # them for run analysis, and skipping non-runs avoids ~30 wasted API
        # calls on a typical sync. Idempotent via the in-DB check inside.
        is_running = _get(act, "activityType", "typeKey", default="").startswith("run")
        if is_running and act.get("activityId"):
            lap_count += _fetch_and_store_laps(conn, client, int(act["activityId"]))

    _log_run(conn, "activities", f"last {limit}", started, count, None)
    conn.commit()
    print(f"activities: {count}/{len(activities)} upserted ({lap_count} new lap rows)")
    return count


def _ingest_day(conn: sqlite3.Connection, client, day: date) -> tuple[int, int, int]:
    iso = day.isoformat()
    daily_n = readiness_n = status_n = 0

    try:
        row = _daily_metrics_row(client.get_stats(iso))
        if row:
            _upsert(conn, "daily_metrics", row, pk=("calendar_date",))
            daily_n = 1
    except Exception as exc:  # noqa: BLE001
        print(f"  daily_metrics {iso}: {exc}", file=sys.stderr)

    try:
        for r in _readiness_rows(client.get_training_readiness(iso)):
            _upsert(conn, "training_readiness", r, pk=("calendar_date", "timestamp"))
            readiness_n += 1
    except Exception as exc:  # noqa: BLE001
        print(f"  training_readiness {iso}: {exc}", file=sys.stderr)

    try:
        row = _training_status_row(client.get_training_status(iso))
        if row:
            _upsert(conn, "training_status", row, pk=("calendar_date",))
            status_n = 1
    except Exception as exc:  # noqa: BLE001
        print(f"  training_status {iso}: {exc}", file=sys.stderr)

    # Race predictions — Garmin only returns *today's* snapshot regardless
    # of the date arg, so only fetch on the most-recent day in the window
    # to avoid wasted calls. The endpoint isn't dated like training_status.
    # Custom upsert (not the generic `_upsert`) so we can supply raw_json
    # only on INSERT — required by the NOT NULL constraint when no
    # training_status row exists yet for the day — while NOT clobbering
    # the real training_status raw_json on UPDATE.
    if iso == date.today().isoformat():
        try:
            payload = client.get_race_predictions()
            row = _race_predictions_row(payload)
            if row:
                conn.execute(
                    """INSERT INTO training_status
                          (calendar_date, race_pred_5k_s, race_pred_10k_s,
                           race_pred_half_s, race_pred_marathon_s, raw_json)
                       VALUES
                          (:calendar_date, :race_pred_5k_s, :race_pred_10k_s,
                           :race_pred_half_s, :race_pred_marathon_s, :raw_json)
                       ON CONFLICT(calendar_date) DO UPDATE SET
                          race_pred_5k_s       = excluded.race_pred_5k_s,
                          race_pred_10k_s      = excluded.race_pred_10k_s,
                          race_pred_half_s     = excluded.race_pred_half_s,
                          race_pred_marathon_s = excluded.race_pred_marathon_s,
                          fetched_at           = datetime('now')""",
                    {**row, "raw_json": json.dumps(payload)},
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  race_predictions {iso}: {exc}", file=sys.stderr)

    return daily_n, readiness_n, status_n


def ingest_recent_days(conn: sqlite3.Connection, client, days: int) -> tuple[int, int, int]:
    started = datetime.now(timezone.utc).isoformat()
    today = date.today()
    totals = [0, 0, 0]
    for offset in range(days):
        d, r, s = _ingest_day(conn, client, today - timedelta(days=offset))
        totals[0] += d
        totals[1] += r
        totals[2] += s
    _log_run(conn, "daily", f"last {days} days", started, sum(totals), None)
    conn.commit()
    print(
        f"daily_metrics: {totals[0]} rows; "
        f"training_readiness: {totals[1]} rows; "
        f"training_status: {totals[2]} rows (deduped on snapshot date)"
    )
    return tuple(totals)  # type: ignore[return-value]


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest Garmin Connect data into local SQLite.")
    parser.add_argument("--activities", type=int, default=30, help="how many recent activities to pull (default 30)")
    parser.add_argument("--days", type=int, default=14, help="how many days of daily metrics to pull (default 14)")
    args = parser.parse_args()

    print("Authenticating with Garmin...")
    try:
        client = get_client()
    except Exception:
        traceback.print_exc()
        return 1
    print("  ok")

    conn = connect()
    try:
        ingest_activities(conn, client, limit=args.activities)
        ingest_recent_days(conn, client, days=args.days)
        try:
            counts = plan_matcher.match_plan_workouts(conn)
            total_matched = counts["matched_exact"] + counts["matched_heuristic"]
            if total_matched or counts["unmatched_past"]:
                print(
                    f"plan adherence: matched {total_matched} "
                    f"({counts['matched_exact']} exact, {counts['matched_heuristic']} heuristic), "
                    f"unmatched_past {counts['unmatched_past']}"
                )
        except Exception as exc:  # noqa: BLE001
            print(f"  matcher failed (continuing): {exc}", file=sys.stderr)
        # Strength matcher: link strength_training / mobility activities
        # back to their scheduled plan_strength_sessions via the echoed
        # Garmin workoutId. Run after the running matcher so the same
        # ingest call closes both loops.
        try:
            from running_coach.strength import matcher as strength_matcher
            sc = strength_matcher.match_strength_sessions(conn)
            if sc["matched"]:
                print(f"strength adherence: matched {sc['matched']} (scanned {sc['scanned']})")
        except Exception as exc:  # noqa: BLE001
            print(f"  strength matcher failed (continuing): {exc}", file=sys.stderr)
    finally:
        conn.close()

    print("done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
