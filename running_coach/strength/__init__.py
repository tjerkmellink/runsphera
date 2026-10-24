"""Optional bodyweight core/strength sessions for rest days.

Layered to mirror the running side of the app:

- ``library``  — the canonical bodyweight sessions (Python data, seeded
  into the ``strength_workouts`` table on first connect).
- ``scheduler`` — rotates the library across a plan's rest days when
  the plan-level toggle is on, with a "recovery after quality" override.
- ``service``   — read/write helpers for the ``plan_strength_sessions``
  join table (assign, clear, mark-complete, fetch-for-week).

Strength sessions are deliberately a *parallel* schedule axis from
``plan_workouts``: a rest day stays a rest day even when a strength
session is attached. The week card renders the strength chip alongside
the rest cell rather than replacing it.
"""

from . import garmin_catalog, garmin_push, library, matcher, scheduler, service  # noqa: F401
