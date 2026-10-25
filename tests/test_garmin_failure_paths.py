"""Regression tests for Garmin failure paths that used to report success.

Two defects, both of the same shape — an outward Garmin call fails and the
local DB records it as though it had worked:

1. ``cleanup_pushed_workouts`` cleared ``garmin_workout_id``/``pushed_at``
   even when ``delete_workout`` raised, stranding a workout on the watch
   with no identifier left to retry, and making a later re-push duplicate
   rather than replace it.
2. ``push_session`` stamped ``pushed_at`` even when ``schedule_workout``
   raised, so a session that never reached the calendar reported
   "Pushed to your watch."
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runsphera.db import connect  # noqa: E402
from runsphera.plans import service as plan_service  # noqa: E402


# ── doubles ──────────────────────────────────────────────────────────────

class DeleteAlwaysFails:
    def delete_workout(self, wid):
        raise RuntimeError("garmin 503")


class DeleteAlwaysWorks:
    def __init__(self):
        self.deleted = []

    def delete_workout(self, wid):
        self.deleted.append(wid)


class DeleteFailsFor:
    """Fails only for the given ids; succeeds for the rest."""

    def __init__(self, bad):
        self.bad = set(bad)
        self.deleted = []

    def delete_workout(self, wid):
        if wid in self.bad:
            raise RuntimeError("garmin 503")
        self.deleted.append(wid)


def _db():
    """Temp database — never the real one (architecture decision #2)."""
    tmp = tempfile.mkdtemp()
    return connect(Path(tmp) / "test.db")


def _plan_with_pushed_workouts(conn, n=3):
    cur = conn.execute(
        "INSERT INTO plans "
        "(goal_type, methodology, days_per_week, long_run_day, title, status) "
        "VALUES ('10k', 'daniels', 4, 6, 'test plan', 'active')"
    )
    plan_id = cur.lastrowid
    for i in range(n):
        conn.execute(
            "INSERT INTO plan_workouts "
            "(plan_id, week_number, week_phase, day_of_week, planned_date, "
            " workout_type, title, garmin_workout_id, pushed_at) "
            "VALUES (?, 1, 'base', ?, ?, 'easy', 'easy run', ?, "
            "        '2026-01-01 10:00:00')",
            (plan_id, i, f"2026-01-0{i + 1}", 1000 + i),
        )
    conn.commit()
    return plan_id


def _push_state(conn, plan_id):
    return conn.execute(
        "SELECT garmin_workout_id, pushed_at FROM plan_workouts "
        "WHERE plan_id = ? ORDER BY id",
        (plan_id,),
    ).fetchall()


# ── finding 2: cleanup must not clear state it did not change ────────────

def test_failed_delete_keeps_garmin_id():
    conn = _db()
    plan_id = _plan_with_pushed_workouts(conn, 3)

    result = plan_service.cleanup_pushed_workouts(conn, DeleteAlwaysFails(), plan_id)

    assert result == {"cleaned": 0, "failed": 3}, result
    for row in _push_state(conn, plan_id):
        assert row["garmin_workout_id"] is not None, "id dropped on a failed delete"
        assert row["pushed_at"] is not None, "pushed_at dropped on a failed delete"


def test_successful_delete_clears_garmin_id():
    conn = _db()
    plan_id = _plan_with_pushed_workouts(conn, 3)

    result = plan_service.cleanup_pushed_workouts(conn, DeleteAlwaysWorks(), plan_id)

    assert result == {"cleaned": 3, "failed": 0}, result
    for row in _push_state(conn, plan_id):
        assert row["garmin_workout_id"] is None
        assert row["pushed_at"] is None


def test_partial_failure_clears_only_the_confirmed_ones():
    """One bad row must not abort the sweep, nor contaminate the good rows."""
    conn = _db()
    plan_id = _plan_with_pushed_workouts(conn, 3)  # ids 1000, 1001, 1002

    result = plan_service.cleanup_pushed_workouts(conn, DeleteFailsFor({1001}), plan_id)

    assert result == {"cleaned": 2, "failed": 1}, result
    rows = _push_state(conn, plan_id)
    assert rows[0]["garmin_workout_id"] is None
    assert rows[1]["garmin_workout_id"] == 1001, "failed row must keep its id"
    assert rows[1]["pushed_at"] is not None
    assert rows[2]["garmin_workout_id"] is None


def test_retry_after_failure_can_still_find_the_workout():
    """The point of keeping the id: a later sweep can finish the job."""
    conn = _db()
    plan_id = _plan_with_pushed_workouts(conn, 2)

    plan_service.cleanup_pushed_workouts(conn, DeleteAlwaysFails(), plan_id)
    client = DeleteAlwaysWorks()
    result = plan_service.cleanup_pushed_workouts(conn, client, plan_id)

    assert result == {"cleaned": 2, "failed": 0}
    assert sorted(client.deleted) == [1000, 1001]


# ── finding 3: upload and schedule are separate gates ────────────────────

class UploadsThenFailsSchedule:
    def __init__(self):
        self.scheduled = []

    def upload_workout(self, payload):
        return {"workoutId": 777}

    def schedule_workout(self, workout_id, date):
        raise RuntimeError("garmin 500 on schedule")


class UploadsAndSchedules:
    def __init__(self):
        self.scheduled = []

    def upload_workout(self, payload):
        return {"workoutId": 888}

    def schedule_workout(self, workout_id, date):
        self.scheduled.append((workout_id, date))


def _strength_session(conn):
    """One plan + one library workout + one scheduled session."""
    plan_id = _plan_with_pushed_workouts(conn, 0)
    cur = conn.execute(
        "INSERT INTO strength_workouts "
        "(slug, title, category, duration_min_lo, duration_min_hi, structure) "
        "VALUES ('t', 'Test session', 'full_body', 20, 25, ?)",
        ('{"blocks": [{"name": "Main", "rounds": 1, "exercises": ['
         '{"name": "Squat", "garmin": "squat/squat", "reps": 10}]}]}',),
    )
    workout_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO plan_strength_sessions "
        "(plan_id, strength_workout_id, planned_date) VALUES (?, ?, '2030-01-06')",
        (plan_id, workout_id),
    )
    conn.commit()
    return cur.lastrowid


def _strength_state(conn, session_id):
    return conn.execute(
        "SELECT garmin_workout_id, pushed_at FROM plan_strength_sessions WHERE id = ?",
        (session_id,),
    ).fetchone()


def test_failed_schedule_does_not_mark_session_pushed():
    """Upload succeeded, schedule did not — pushed_at must stay NULL.

    pushed_at means "on the watch's calendar for the planned date". Stamping
    it here made the UI report "Pushed to your watch." for a session that
    never arrived.
    """
    from runsphera.strength import garmin_push

    conn = _db()
    session_id = _strength_session(conn)

    result = garmin_push.push_session(conn, UploadsThenFailsSchedule(), session_id)

    assert result["scheduled"] is False, result
    assert result["schedule_error"] is not None
    row = _strength_state(conn, session_id)
    assert row["pushed_at"] is None, "claimed pushed despite a failed schedule"


def test_failed_schedule_still_records_the_uploaded_id():
    """Keeping the id means a retry replaces the copy instead of duplicating."""
    from runsphera.strength import garmin_push

    conn = _db()
    session_id = _strength_session(conn)

    garmin_push.push_session(conn, UploadsThenFailsSchedule(), session_id)

    row = _strength_state(conn, session_id)
    assert row["garmin_workout_id"] == 777, "uploaded id was dropped"


def test_successful_push_marks_session_pushed():
    from runsphera.strength import garmin_push

    conn = _db()
    session_id = _strength_session(conn)

    result = garmin_push.push_session(conn, UploadsAndSchedules(), session_id)

    assert result["scheduled"] is True
    assert result["schedule_error"] is None
    row = _strength_state(conn, session_id)
    assert row["garmin_workout_id"] == 888
    assert row["pushed_at"] is not None


# ── release_garmin_copy: the shared decision ─────────────────────────────

def test_release_returns_true_when_nothing_to_delete():
    assert plan_service.release_garmin_copy(DeleteAlwaysWorks(), None) is True


def test_release_returns_false_without_a_client():
    """No auth means the workout is still on Garmin — never report success."""
    assert plan_service.release_garmin_copy(None, 999) is False


def test_release_returns_false_when_garmin_refuses():
    assert plan_service.release_garmin_copy(DeleteAlwaysFails(), 999) is False


def test_release_returns_true_on_confirmed_delete():
    client = DeleteAlwaysWorks()
    assert plan_service.release_garmin_copy(client, 999) is True
    assert client.deleted == [999]


# ── finding 3 (running path): upload and schedule are separate gates ─────

class RunUploadsThenFailsSchedule:
    def __init__(self):
        self.uploads = 0

    def upload_running_workout(self, obj):
        self.uploads += 1
        return {"workoutId": 555}

    def schedule_workout(self, wid, date):
        raise RuntimeError("garmin 500 on schedule")

    def delete_workout(self, wid):
        pass


class RunUploadsAndSchedules:
    def __init__(self):
        self.uploads = 0
        self.deleted = []

    def upload_running_workout(self, obj):
        self.uploads += 1
        return {"workoutId": 666}

    def schedule_workout(self, wid, date):
        pass

    def delete_workout(self, wid):
        self.deleted.append(wid)


def _unpushed_workout(conn):
    """One plan with a single pushable easy run, not yet pushed."""
    cur = conn.execute(
        "INSERT INTO plans "
        "(goal_type, methodology, days_per_week, long_run_day, title, status) "
        "VALUES ('10k', 'daniels', 4, 6, 'test plan', 'active')"
    )
    plan_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO plan_workouts "
        "(plan_id, week_number, week_phase, day_of_week, planned_date, "
        " workout_type, title, target_distance_km, target_pace_s_per_km) "
        "VALUES (?, 1, 'base', 1, '2030-01-08', 'easy', 'Easy 8 km', 8.0, 355)",
        (plan_id,),
    )
    conn.commit()
    return cur.lastrowid


def test_failed_schedule_keeps_the_uploaded_running_workout_id():
    """The upload happened; losing its id would strand it on Garmin."""
    conn = _db()
    wid = _unpushed_workout(conn)

    try:
        plan_service.push_workout_to_garmin(conn, RunUploadsThenFailsSchedule(), wid)
    except Exception:
        pass  # scheduling failure propagates to the caller by design

    row = conn.execute(
        "SELECT garmin_workout_id, pushed_at FROM plan_workouts WHERE id = ?", (wid,)
    ).fetchone()
    assert row["garmin_workout_id"] == 555, "uploaded id was lost"
    assert row["pushed_at"] is None, "claimed scheduled despite the failure"


def test_retry_after_failed_schedule_replaces_rather_than_duplicates():
    """A stranded upload is released before the retry uploads a new copy."""
    conn = _db()
    wid = _unpushed_workout(conn)

    try:
        plan_service.push_workout_to_garmin(conn, RunUploadsThenFailsSchedule(), wid)
    except Exception:
        pass

    client = RunUploadsAndSchedules()
    plan_service.push_workout_to_garmin(conn, client, wid)

    assert client.deleted == [555], "stranded copy was not removed before retry"
    assert client.uploads == 1
    row = conn.execute(
        "SELECT garmin_workout_id, pushed_at FROM plan_workouts WHERE id = ?", (wid,)
    ).fetchone()
    assert row["garmin_workout_id"] == 666
    assert row["pushed_at"] is not None


def test_retry_refuses_when_the_stranded_copy_cannot_be_removed():
    """Better a loud failure than a second copy on the same day."""
    conn = _db()
    wid = _unpushed_workout(conn)

    try:
        plan_service.push_workout_to_garmin(conn, RunUploadsThenFailsSchedule(), wid)
    except Exception:
        pass

    class CannotDelete(RunUploadsAndSchedules):
        def delete_workout(self, wid):
            raise RuntimeError("garmin 503")

    client = CannotDelete()
    raised = False
    try:
        plan_service.push_workout_to_garmin(conn, client, wid)
    except RuntimeError as exc:
        raised = "still on" in str(exc)
    assert raised, "should refuse rather than upload a duplicate"
    assert client.uploads == 0, "uploaded a duplicate anyway"


def test_successful_push_sets_both_id_and_pushed_at():
    conn = _db()
    wid = _unpushed_workout(conn)

    plan_service.push_workout_to_garmin(conn, RunUploadsAndSchedules(), wid)

    row = conn.execute(
        "SELECT garmin_workout_id, pushed_at FROM plan_workouts WHERE id = ?", (wid,)
    ).fetchone()
    assert row["garmin_workout_id"] == 666
    assert row["pushed_at"] is not None


# ── strength: unpush and prior-copy delete ───────────────────────────────

class StrengthDeleteFails:
    def delete_workout(self, wid):
        raise RuntimeError("garmin 503")

    def upload_workout(self, payload):  # pragma: no cover — must not be reached
        raise AssertionError("uploaded despite a failed prior delete")

    def schedule_workout(self, wid, date):  # pragma: no cover
        pass


class StrengthDeleteOk:
    def __init__(self):
        self.deleted = []

    def delete_workout(self, wid):
        self.deleted.append(wid)

    def upload_workout(self, payload):
        return {"workoutId": 321}

    def schedule_workout(self, wid, date):
        pass


def _pushed_strength_session(conn):
    session_id = _strength_session(conn)
    conn.execute(
        "UPDATE plan_strength_sessions SET garmin_workout_id = 999, "
        "pushed_at = '2030-01-01 10:00:00' WHERE id = ?",
        (session_id,),
    )
    conn.commit()
    return session_id


def test_unpush_keeps_state_when_delete_fails():
    """It returned True and cleared state, so the UI said 'Removed from your
    watch.' for a session still on the watch."""
    from runsphera.strength import garmin_push

    conn = _db()
    session_id = _pushed_strength_session(conn)

    result = garmin_push.unpush_session(conn, StrengthDeleteFails(), session_id)

    assert result is False, "claimed the workout was removed"
    row = _strength_state(conn, session_id)
    assert row["garmin_workout_id"] == 999, "retry handle was thrown away"
    assert row["pushed_at"] is not None


def test_unpush_clears_state_on_confirmed_delete():
    from runsphera.strength import garmin_push

    conn = _db()
    session_id = _pushed_strength_session(conn)
    client = StrengthDeleteOk()

    assert garmin_push.unpush_session(conn, client, session_id) is True
    assert client.deleted == [999]
    row = _strength_state(conn, session_id)
    assert row["garmin_workout_id"] is None
    assert row["pushed_at"] is None


def test_unpush_without_a_client_keeps_state():
    """No auth means nothing was deleted — never report success."""
    from runsphera.strength import garmin_push

    conn = _db()
    session_id = _pushed_strength_session(conn)

    assert garmin_push.unpush_session(conn, None, session_id) is False
    assert _strength_state(conn, session_id)["garmin_workout_id"] == 999


def test_push_refuses_when_the_prior_copy_cannot_be_removed():
    """Better a loud failure than two copies of the same session on one day."""
    from runsphera.strength import garmin_push

    conn = _db()
    session_id = _pushed_strength_session(conn)

    raised = False
    try:
        garmin_push.push_session(conn, StrengthDeleteFails(), session_id)
    except RuntimeError as exc:
        raised = "could not be removed" in str(exc)
    assert raised, "should refuse rather than upload a duplicate"
    assert _strength_state(conn, session_id)["garmin_workout_id"] == 999


def test_push_replaces_the_prior_copy_when_delete_succeeds():
    from runsphera.strength import garmin_push

    conn = _db()
    session_id = _pushed_strength_session(conn)
    client = StrengthDeleteOk()

    result = garmin_push.push_session(conn, client, session_id)

    assert client.deleted == [999], "prior copy was not removed"
    assert result["workout_id"] == 321
    assert _strength_state(conn, session_id)["garmin_workout_id"] == 321


# ── finding 3: replaying a successful push must not duplicate ────────────

def test_replaying_a_successful_push_is_a_no_op():
    """A stale tab or a retried POST would upload a second copy and overwrite
    the id, orphaning the first beyond the reach of any cleanup."""
    conn = _db()
    wid = _unpushed_workout(conn)
    client = RunUploadsAndSchedules()

    plan_service.push_workout_to_garmin(conn, client, wid)
    first = conn.execute(
        "SELECT garmin_workout_id, pushed_at FROM plan_workouts WHERE id = ?", (wid,)
    ).fetchone()

    plan_service.push_workout_to_garmin(conn, client, wid)

    assert client.uploads == 1, f"uploaded {client.uploads} copies on replay"
    after = conn.execute(
        "SELECT garmin_workout_id, pushed_at FROM plan_workouts WHERE id = ?", (wid,)
    ).fetchone()
    assert after["garmin_workout_id"] == first["garmin_workout_id"]
    assert after["pushed_at"] == first["pushed_at"]


def test_replay_returns_the_existing_row():
    conn = _db()
    wid = _unpushed_workout(conn)
    client = RunUploadsAndSchedules()

    plan_service.push_workout_to_garmin(conn, client, wid)
    row = plan_service.push_workout_to_garmin(conn, client, wid)

    assert row["garmin_workout_id"] == 666
    assert row["pushed_at"] is not None


def test_a_stranded_push_is_still_retried_not_skipped():
    """The no-op must not swallow the stranded case it sits next to."""
    conn = _db()
    wid = _unpushed_workout(conn)

    try:
        plan_service.push_workout_to_garmin(conn, RunUploadsThenFailsSchedule(), wid)
    except Exception:
        pass

    client = RunUploadsAndSchedules()
    plan_service.push_workout_to_garmin(conn, client, wid)

    assert client.deleted == [555], "stranded copy was not released"
    assert client.uploads == 1


# ── finding 1: the unpush route must not claim success ───────────────────

def test_unpush_outcome_confirms_only_a_real_removal():
    from runsphera.web.app import unpush_outcome

    key, _ = unpush_outcome(removed=True, error=None, still_pushed=False)
    assert key == "Removed from your watch."


def test_unpush_outcome_reports_a_garmin_refusal():
    """unpush_session returned False with the id still set."""
    from runsphera.web.app import unpush_outcome

    key, _ = unpush_outcome(removed=False, error=None, still_pushed=True)
    assert "still on your watch" in key


def test_unpush_outcome_reports_an_auth_failure():
    from runsphera.web.app import unpush_outcome

    key, params = unpush_outcome(
        removed=False, error="Garmin isn't connected", still_pushed=True
    )
    assert "{error}" in key
    assert params["error"] == "Garmin isn't connected"


def test_unpush_outcome_never_claims_removal_when_still_pushed():
    """The route hard-coded success for all four cases; three were wrong."""
    from runsphera.web.app import unpush_outcome

    for error in (None, "boom"):
        key, _ = unpush_outcome(removed=False, error=error, still_pushed=True)
        assert key != "Removed from your watch.", (error, key)


def test_unpush_outcome_handles_a_session_that_was_never_pushed():
    from runsphera.web.app import unpush_outcome

    key, _ = unpush_outcome(removed=False, error=None, still_pushed=False)
    assert key == "That session wasn't on your watch."


# ── finding 1: an edit that couldn't reach Garmin must not read as synced ──

def test_edit_without_a_client_leaves_the_row_unsynced():
    """The interaction that made a stale prescription permanent.

    Round 2 kept `garmin_workout_id` when a delete failed, so a retry had a
    handle. Round 4 then made a fully-pushed row a push no-op. Together they
    meant: edit a pushed workout offline, keep both columns, and every later
    push returned early — the watch kept the old prescription forever while
    the UI showed the new one as on-watch.
    """
    conn = _db()
    plan_id = _plan_with_pushed_workouts(conn, 1)
    wid = conn.execute(
        "SELECT id FROM plan_workouts WHERE plan_id = ?", (plan_id,)
    ).fetchone()["id"]

    plan_service.edit_workout(
        conn, None, wid, workout_type="easy", target_distance_km=8.0,
        target_pace_s_per_km=360,
    )

    row = conn.execute(
        "SELECT garmin_workout_id, pushed_at FROM plan_workouts WHERE id = ?", (wid,)
    ).fetchone()
    assert row["garmin_workout_id"] == 1000, "lost the handle to the watch copy"
    assert row["pushed_at"] is None, "row claims the edited shape is on the watch"


def test_pushing_after_an_offline_edit_replaces_the_stale_copy():
    """End to end: the retry must actually reach Garmin, not no-op."""
    conn = _db()
    plan_id = _plan_with_pushed_workouts(conn, 1)
    wid = conn.execute(
        "SELECT id FROM plan_workouts WHERE plan_id = ?", (plan_id,)
    ).fetchone()["id"]

    plan_service.edit_workout(
        conn, None, wid, workout_type="easy", target_distance_km=8.0,
        target_pace_s_per_km=360,
    )

    client = RunUploadsAndSchedules()
    plan_service.push_workout_to_garmin(conn, client, wid)

    assert client.deleted == [1000], "stale copy was never removed from Garmin"
    assert client.uploads == 1, f"expected one upload, got {client.uploads}"
    row = conn.execute(
        "SELECT garmin_workout_id, pushed_at FROM plan_workouts WHERE id = ?", (wid,)
    ).fetchone()
    assert row["garmin_workout_id"] == 666
    assert row["pushed_at"] is not None


# ── finding 4: concurrent pushes must not both upload ────────────────────

def test_concurrent_pushes_upload_only_once():
    """Bulk push and an individual push can hit the same row at once."""
    import threading

    tmp = Path(tempfile.mkdtemp()) / "test.db"
    conn = connect(tmp)
    wid = _unpushed_workout(conn)
    conn.close()

    class SlowUpload:
        def __init__(self):
            self.uploads = 0
            self.scheduled = []
            self._lock = threading.Lock()

        def upload_running_workout(self, obj):
            with self._lock:
                self.uploads += 1
                n = self.uploads
            # Widen the race window the lock is supposed to close.
            threading.Event().wait(0.05)
            return {"workoutId": 900 + n}

        def schedule_workout(self, wid_, date):
            self.scheduled.append(wid_)

        def delete_workout(self, wid_):
            pass

    client = SlowUpload()
    errors = []

    def push():
        # One connection per thread, exactly as each web request does.
        try:
            c = connect(tmp)
            try:
                plan_service.push_workout_to_garmin(c, client, wid)
            finally:
                c.close()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=push) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert client.uploads == 1, f"uploaded {client.uploads} copies concurrently"
    assert len(client.scheduled) == 1, client.scheduled


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"{len(fns)} passed")


if __name__ == "__main__":
    main()
