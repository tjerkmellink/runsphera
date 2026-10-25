"""Nutrition & hydration — the Fuel feature.

`engine` holds the pure, deterministic sports-nutrition rules (no I/O):
BMR, daily energy + macro targets, hydration, and around-the-run fuelling.
`service` wires those rules to the DB (profile + today's workout + weather
+ Garmin day metrics) for the routes to consume.

Rules-first by design: every threshold is a named constant in `engine`,
sourced from mainstream sports-nutrition guidance — see
docs/nutrition-fueling.md. Concrete meal suggestions (NEVO food DB) are a
later phase; this phase delivers the numbers + fuelling timing.
"""
from __future__ import annotations

from . import engine, food_library, meal_plan, service  # noqa: F401
