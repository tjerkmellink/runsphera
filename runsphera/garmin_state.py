"""Garmin workout lifecycle: releasing a pushed copy.

Shared by the running-plan paths (`plans/service.py`) and the strength paths
(`strength/garmin_push.py`). It lives outside both so neither has to import
the other, and because the rule it encodes is the same on both sides.
"""
from __future__ import annotations


def release_garmin_copy(client, garmin_workout_id) -> bool:
    """Delete one pushed workout on Garmin. True once it is confirmed gone.

    Every path that reshapes a pushed workout — edit, move, swap, recalibrate,
    reshape — has to answer the same question first: *is the old copy actually
    off the watch?* Only then may the local push state be cleared, and only
    then may a replacement be uploaded.

    Returns False when the delete could not be confirmed, either because there
    is no authenticated client or because Garmin refused. The caller must then
    leave ``garmin_workout_id`` and ``pushed_at`` alone: they are the push
    state (architecture decision #4) and the only handle left to retry.
    Clearing them would claim the watch is clean when it is not, and turn the
    next push into a duplicate instead of a replacement.

    Returns True when ``garmin_workout_id`` is None — there was nothing to
    release, so the caller is free to proceed.
    """
    if garmin_workout_id is None:
        return True
    if client is None:
        # No auth: the workout is still on Garmin and we cannot touch it.
        return False
    try:
        client.delete_workout(garmin_workout_id)
        return True
    except Exception:  # noqa: BLE001 — caller decides what a failure means
        return False


# ── per-workout push serialisation ───────────────────────────────────────
#
# The app runs as one process (uvicorn's thread pool, or that pool inside the
# desktop launcher), but two of its threads can race: "Push week" walks a
# week while the runner clicks Push on a single day inside it. Both read the
# row as unpushed, both upload, both schedule — and the second DB write
# overwrites the first id, putting that copy beyond any later cleanup.
#
# A lock per workout id is enough for a single process, which is all this app
# ever is. It is deliberately not a DB-level claim: holding a SQLite write
# lock across a Garmin network round-trip would block every other request.

import threading as _threading

_push_locks: dict[tuple[str, int], _threading.Lock] = {}
_push_locks_guard = _threading.Lock()


def push_lock(kind: str, row_id: int) -> _threading.Lock:
    """The lock guarding pushes for one row. Same (kind, id) → same lock.

    ``kind`` separates the namespaces: plan workout 7 and strength session 7
    are different rows in different tables.
    """
    key = (kind, int(row_id))
    with _push_locks_guard:
        lock = _push_locks.get(key)
        if lock is None:
            lock = _threading.Lock()
            _push_locks[key] = lock
        return lock
