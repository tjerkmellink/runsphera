"""Probe which Recovery & Mobility exercise blocks 'push to watch'.

Background
----------
The Recovery & Mobility session uploads to Garmin Connect fine and every
step renders with animation in the app — but it refuses to sync to the
watch ("incompatible device"). That's the Fenix *device-compatibility*
validator rejecting it, which is a DIFFERENT gate from the animation
check we probed on 2026-05-31. All 12 steps are `pose/*` / `move/*`,
verified animated but never verified sync-able to the device.

This script isolates the culprit empirically, the same way as last time:
it pushes ONE single-exercise mobility workout per pose (same sportType /
description=None / workoutProvider shape as the real session, so the only
variable is the exercise enum), schedules each on today, and records the
workout IDs to a JSON sidecar.

Usage
-----
    python -m scripts.probe_recovery_sync push     # upload + schedule the 12 probes
    python -m scripts.probe_recovery_sync clean     # delete every probe it created

Then, in the Garmin Connect phone app: open each "ZZPROBE NN ..." workout
and try to send it to the watch. Note which NN values throw the
incompatible-device notification — those are the offending enums. Report
them back, then run `clean`.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

from runsphera import garmin
from runsphera.strength import garmin_push
from runsphera.strength.library import RECOVERY_MOBILITY

# Round 2: the 12 single-pose MOBILITY probes all failed to push to the
# watch, and the user's own copies of Garmin's yoga/pilates workouts
# (which DO sync) use sportType yoga(7)/pilates(8) + subSportType GENERIC.
# So the culprit is the sport type, not any exercise. This round re-pushes
# the SAME pose/move steps under yoga(7) to confirm before changing code.
_SPORT_YOGA = {"sportTypeId": 7, "sportTypeKey": "yoga", "displayOrder": 8}

# The 12 exercises in Recovery & Mobility, in session order. Mirrors
# RECOVERY_MOBILITY in runsphera/strength/library.py — kept inline so
# the probe is self-contained and doesn't depend on a live plan row.
PROBE_EXERCISES: list[tuple[str, str, int]] = [
    ("pose", "easy_seated",          45),
    ("pose", "cat",                  30),
    ("pose", "cow",                  30),
    ("pose", "low_lunge",            45),
    ("pose", "runners_lunge",        45),
    ("pose", "one_legged_pigeon",    45),
    ("pose", "downward_facing_dog",  45),
    ("move", "forward_fold",         45),
    ("move", "hamstring_stretch",    30),
    ("pose", "supine_spinal_twist",  45),
    ("pose", "thread_the_needle",    30),
    ("pose", "childs",               60),
]

_IDS_FILE = Path(__file__).with_name("probe_recovery_sync_ids.json")


def _probe_session(idx: int, category: str, exercise: str, dur: int) -> dict:
    """A minimal one-step mobility session in the hydrated shape
    build_payload expects. category='recovery' => sportType mobility (11),
    identical to the real Recovery & Mobility push."""
    return {
        "title":           f"ZZPROBE {idx:02d} {category}-{exercise}",
        "category":        "recovery",
        "duration_min_lo": 1,
        "duration_min_hi": 1,
        "notes":           f"sync probe: {category}/{exercise}",
        "structure": {
            "blocks": [
                {
                    "name": "probe",
                    "rounds": 1,
                    "rest_between_rounds_s": 0,
                    "exercises": [
                        {"category": category, "exercise": exercise, "duration_s": dur},
                    ],
                },
            ],
        },
    }


def push() -> None:
    client = garmin.get_client()
    today = date.today().isoformat()
    created: list[dict] = []

    for i, (cat, ex, dur) in enumerate(PROBE_EXERCISES, start=1):
        session = _probe_session(i, cat, ex, dur)
        payload = garmin_push.build_payload(session)
        resp = client.upload_workout(payload)
        wid = resp.get("workoutId") if isinstance(resp, dict) else None
        if not wid:
            print(f"  !! {i:02d} {cat}/{ex}: upload returned no workoutId: {resp!r}")
            continue
        try:
            client.schedule_workout(wid, today)
        except Exception as exc:  # noqa: BLE001 — scheduling is convenience only
            print(f"  ~  {i:02d} {cat}/{ex}: scheduled-failed ({exc}) but uploaded")
        created.append({"n": i, "category": cat, "exercise": ex, "workout_id": wid})
        print(f"  ok {i:02d} {cat}/{ex}  -> workoutId {wid}")

    _IDS_FILE.write_text(json.dumps(created, indent=2))
    print(f"\nPushed {len(created)} probes, scheduled on {today}.")
    print(f"IDs saved to {_IDS_FILE.name}.")
    print("Now: in the phone app, try 'send to watch' on each ZZPROBE NN "
          "workout and note which NN fail. Then run: python -m scripts.probe_recovery_sync clean")


def clean() -> None:
    if not _IDS_FILE.exists():
        print("No probe ID file found — nothing to clean.")
        return
    created = json.loads(_IDS_FILE.read_text())
    client = garmin.get_client()
    for item in created:
        wid = item["workout_id"]
        try:
            client.delete_workout(wid)
            print(f"  deleted {item['n']} {item['category']}/{item['exercise']} ({wid})")
        except Exception as exc:  # noqa: BLE001
            print(f"  !! delete {wid} failed: {exc}")
    _IDS_FILE.unlink()
    print(f"\nRemoved {len(created)} probes and deleted {_IDS_FILE.name}.")


def _override_sport(payload: dict, sport: dict) -> dict:
    """Swap the sportType to `sport` and add subSportType=GENERIC, mirroring
    the proven-syncing Garmin yoga/pilates shape. Everything else (steps,
    description=None, provider) stays identical to the real push."""
    payload["sportType"] = sport
    payload["subSportType"] = "GENERIC"
    for seg in payload.get("workoutSegments", []):
        seg["sportType"] = {**sport, "displayOrder": sport["sportTypeId"]}
    return payload


def yoga() -> None:
    """Round-2 confirmation: re-push the recovery steps under yoga(7).

    Pushes two test workouts:
      ZZYOGA full   — the real Recovery & Mobility session (10 pose + 2 move)
      ZZYOGA move   — just the 2 move/* steps, to isolate the move-under-yoga risk
    """
    client = garmin.get_client()
    today = date.today().isoformat()
    created: list[dict] = []

    full = {
        "title": "ZZYOGA full Recovery", "category": "recovery",
        "duration_min_lo": RECOVERY_MOBILITY["duration_min_lo"],
        "duration_min_hi": RECOVERY_MOBILITY["duration_min_hi"],
        "notes": "yoga sportType test — full session",
        "structure": {"blocks": RECOVERY_MOBILITY["blocks"]},
    }
    move_only = {
        "title": "ZZYOGA move only", "category": "recovery",
        "duration_min_lo": 1, "duration_min_hi": 2,
        "notes": "yoga sportType test — move/* steps only",
        "structure": {"blocks": [{
            "name": "moves", "rounds": 1, "rest_between_rounds_s": 0,
            "exercises": [
                {"category": "move", "exercise": "forward_fold", "duration_s": 45},
                {"category": "move", "exercise": "hamstring_stretch", "duration_s": 30},
            ],
        }]},
    }

    for tag, session in (("full", full), ("move", move_only)):
        payload = _override_sport(garmin_push.build_payload(session), _SPORT_YOGA)
        resp = client.upload_workout(payload)
        wid = resp.get("workoutId") if isinstance(resp, dict) else None
        if not wid:
            print(f"  !! {tag}: upload returned no workoutId: {resp!r}")
            continue
        try:
            client.schedule_workout(wid, today)
        except Exception as exc:  # noqa: BLE001
            print(f"  ~  {tag}: scheduled-failed ({exc}) but uploaded")
        created.append({"n": tag, "category": "yoga", "exercise": session["title"], "workout_id": wid})
        print(f"  ok {tag:5s} -> workoutId {wid}  ({session['title']})")

    # Append to the same sidecar so `clean` removes these too.
    existing = json.loads(_IDS_FILE.read_text()) if _IDS_FILE.exists() else []
    _IDS_FILE.write_text(json.dumps(existing + created, indent=2))
    print(f"\nPushed {len(created)} yoga-sportType probes, scheduled on {today}.")
    print("Try 'send to watch' on BOTH 'ZZYOGA ...' workouts and report which sync.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "push":
        push()
    elif mode == "yoga":
        yoga()
    elif mode == "clean":
        clean()
    else:
        print(__doc__)
        sys.exit(1)
