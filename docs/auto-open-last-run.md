# Auto-open last run on sync

> When a Garmin sync pulls in a brand-new run, its detail modal opens automatically — the just-finished run is the first thing the runner sees.

## Purpose

A runner's most common reason to open the app is *"I just finished a run — how did I do?"*. Until now the dashboard synced silently and re-rendered; the new run appeared as a row in the recent-runs table, one click away. This feature closes that gap: the moment a sync detects a newly-arrived run, the app opens that run's detail modal (the same popup you get by clicking the run in the table) without any interaction. Open app → sync fires → run details front-and-centre.

## How it works (user view)

1. The runner finishes a run and opens the dashboard.
2. A Garmin sync kicks off — automatically when data is stale (>4h since the last sync), or on a manual click of **Sync with Garmin**.
3. If that sync brings in a run that wasn't there before, the run-detail modal opens on its own, showing the same tabbed detail (splits, HR zones, coach reaction) as clicking the run row.
4. If the sync finds no new run (nothing changed, or only a backfill of older activities), nothing pops up — the dashboard just refreshes in place as before.

The modal is the existing `#run-detail-modal`; closing it (× / click-outside / Esc) behaves identically to a manually-opened one.

## How it works (implementation)

- **Modules**:
  - [running_coach/web/app.py](../running_coach/web/app.py) — `_latest_run_id()` (new helper), `_run_sync()` (now returns the new run's `activity_id` or `None`), `trigger_ingest()` (`POST /ingest`, now emits a `newRunDetected` HTMX event when a run arrived).
- **Templates**:
  - [running_coach/web/templates/index.html](../running_coach/web/templates/index.html) — a one-time `newRunDetected` listener that `htmx.ajax`-loads `GET /runs/{id}` into `#run-detail-content` and calls `showModal()`.
- **Routes**: `POST /ingest` (touched), `GET /runs/{activity_id}` (reused, unchanged).
- **DB**: reads `activities` (`activity_id`, `activity_type`, `start_time_gmt`) only — no schema change.
- **External services**: Garmin (via the existing sync path).

**Data flow.** `_run_sync()` snapshots the most-recent running `activity_id` (`_latest_run_id`, `ORDER BY start_time_gmt DESC LIMIT 1`) *before* ingest, then re-reads it *after*. If the newest run changed to a non-null id, that id is the "new run". `trigger_ingest()` folds it into the response's `HX-Trigger` header as JSON — `{"dashboardRefresh": null, "newRunDetected": {"activityId": <id>}}` — alongside the existing in-place refresh event. The client listener reacts to `newRunDetected`, loads the detail partial into the dialog (which lives outside `#dashboard-main`, so the concurrent `dashboardRefresh` swap doesn't disturb it) and opens it.

The listener is registered once, outside `#dashboard-main`, so a `dashboardRefresh` in-place swap (which `hx-select`s only `#dashboard-main`) never re-binds it.

## Configuration

None. The feature rides on the existing sync path; there's no setting or env var. Auto-sync-on-load is still gated by the same 4-hour staleness rule as before.

## Known limitations

- **Newest-run comparison, not a true new-row diff.** Detection compares the single most-recent run id before vs after. A sync that backfills an *older* run (never the newest) won't open a modal — intentional, since the UX is about the run you just did. If two runs arrive in one sync, only the newest opens.
- **Depends on `activity_type = 'running'`.** Non-run activities (strength, cycling) never trigger the auto-open.
- **`start_time_gmt` ordering.** If a device uploads with a clock-skewed start time such that a genuinely new run sorts behind an existing one, it won't be detected as newest. Rare in practice.

## Verification

1. With at least one existing run synced, click **Sync with Garmin** when there's no new activity → dashboard refreshes, **no modal** opens.
2. Complete a new run on Garmin (or manually insert a newer `activities` row with `activity_type='running'`), then sync → the run-detail modal **opens automatically** on that run.
3. Confirm the modal content matches clicking that run's row in the recent-runs table.
4. Network check: the `POST /ingest` response carries `HX-Trigger: {"dashboardRefresh":null,"newRunDetected":{"activityId":...}}` only when a new run was found; otherwise plain `dashboardRefresh`.

## Future improvements

- Surface a small toast when a new run is detected but the runner dismisses the modal, so it's discoverable later.
- Extend to non-run activities (open the strength-session modal for a newly-matched strength activity).

---

*Last updated: 2026-07-16*
