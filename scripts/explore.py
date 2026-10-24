"""Probe what Garmin Connect actually returns, so we can design a schema
around real data rather than guesses.

Run from the project root:

    python -m scripts.explore

Dumps a handful of JSON files into data/raw/ for inspection.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

# Make sibling package importable when run as `python scripts/explore.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from running_coach.garmin import get_client


OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def dump(name: str, data: object) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print(f"  wrote {path.relative_to(Path.cwd()) if path.is_relative_to(Path.cwd()) else path}")


def main() -> None:
    print("Logging in to Garmin Connect...")
    client = get_client()
    print("  ok")

    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()

    probes: list[tuple[str, callable]] = [
        ("activities_last_14", lambda: client.get_activities(0, 14)),
        ("stats_yesterday", lambda: client.get_stats(yesterday)),
        ("sleep_yesterday", lambda: client.get_sleep_data(yesterday)),
        ("hrv_yesterday", lambda: client.get_hrv_data(yesterday)),
        ("training_readiness_yesterday", lambda: client.get_training_readiness(yesterday)),
        ("training_status", lambda: client.get_training_status(yesterday)),
        ("user_summary", lambda: client.get_user_summary(yesterday)),
    ]

    for name, call in probes:
        try:
            print(f"Fetching {name}...")
            dump(name, call())
        except Exception as exc:  # noqa: BLE001 - exploration script, surface everything
            print(f"  failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
