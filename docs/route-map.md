# Route map

> Animated map of where a completed run went — the GPS track replays itself inside the run-detail modal.

> **Note (v2, 2026-07-20):** this map now lives on the **Replay** slide (the modal's default view when a route exists). The modal has no tab bar — you move between slides with the prev/next nav at each panel's foot — and the masthead is hidden on Replay so the glow header + map own the top. It leads with a glow header + verdict badge and gained a stats footer. Dark mode briefly used CARTO `dark_all` tiles, but CARTO started requiring an API key (2026-09), so the map is back on keyless OSM tiles with the CSS re-tint for dark mode. See run-detail-design-brief.md §10. The data layer below is unchanged.

## Purpose

The dashboard tells the runner *how* a run went (pace, HR, laps); nothing showed *where* it went. The Route tab closes that gap: click a completed run and watch the track redraw itself over a real map — a small post-run reward that also makes routes comparable at a glance ("the Dalfsen loop again, clockwise this time").

## How it works (user view)

1. Click a run in the dashboard's recent-runs table (or let a fresh sync auto-open it). The run-detail modal opens as usual.
2. Runs with a GPS track get a **Route** tab between Workout and Effort. Opening it shows an OpenStreetMap view fitted to the run, with the full route as a faint dashed ghost line, a green start pin and a red finish pin.
3. On open, a bold orange trail animates over the ghost in ~3 seconds. The replay is **time-proportional to the actual run**: fast blocks sweep, standstills linger — an interval session visibly pulses. The **↻ Replay** button runs it again.
4. Treadmill/indoor runs, strength activities, and Garmin-less setups simply never show the tab — no empty state, no dead map.

## How it works (implementation)

- **Modules**: `running_coach/gps_route.py` — fetch, normalise, cache, and gate the track.
- **Templates**: `_run_detail.html` (Route tab: radio input, label, panel, inline animation JS), `base.html` (Leaflet CDN `<link>`/`<script>`, shell-level for the same HTMX-swap reason as Plotly).
- **Routes**: none new — `GET /runs/{activity_id}` now also hydrates the route and passes `route` to the template.
- **DB**: new `activity_routes` table — `activity_id` PK/FK, `points_json` (compact `[[lat, lon, t_rel_s], …]`), `point_count`, `fetched_at`.
- **External services**: Garmin Connect `get_activity_details` (`/activity-service/activity/{id}/details`, `maxPolylineSize=2000`, `maxChartSize=1` since Phase 1 needs no metric streams). Map tiles from `tile.openstreetmap.org` (no key; attribution rendered by Leaflet).

**Data flow.** Garmin's activity *summary* (already stored in `activities.raw_json`) never contains the track — only a `hasPolyline` flag. On the first modal open of a run, `hydrate_route()` walks a gating ladder:

1. cached row with points → serve it (no network, ever again);
2. cached row with NULL points → known GPS-less activity, serve nothing;
3. `hasPolyline` false in raw_json → write the NULL row immediately, **zero API calls**;
4. otherwise, if signed in to Garmin → one `get_activity_details` call, normalise `geoPolylineDTO.polyline` to `[lat, lon, seconds-from-start]` triples (drops null-coordinate GPS dropouts, rounds to 6 decimals ≈ 0.1 m), store forever. API errors store nothing so the next open retries; signed-out opens also store nothing.

A finished run's track never changes, so there is no invalidation. The client-side animation interpolates along the triples with `requestAnimationFrame`; Leaflet initialises on the Route tab's radio-`change` (a `display:none` container can't be measured), one frame after the panel becomes visible.

## Configuration

Nothing to configure. Dark mode is handled automatically: OSM serves light tiles only, so `app.css` re-tints them (`invert + hue-rotate + dim`) under `html.is-dark`.

## Known limitations

- **Needs internet** for OSM tiles and the one-time Garmin fetch (the app already CDN-loads htmx/Plotly, so this adds no new offline story).
- **Runs synced while signed out** get their route on the first modal open *after* signing in — never backfilled in bulk.
- Garmin downsamples the polyline server-side (≤2000 points) — fine for shape/replay, not for surveying.
- The polyline is fetched for the *modal*, so a run nobody clicks never costs an API call — by design.
- No pace/HR coloring on the trail yet (that's Phase 2 — the details endpoint has the streams, `maxchart` is just set to 1 for now).

## Verification

1. Open the dashboard, click a recent **outdoor** run → Route tab appears; opening it draws the map and the trail replays start→finish. ↻ Replay repeats it.
2. `sqlite3 data/running_coach.db "SELECT activity_id, point_count FROM activity_routes"` → one row per opened run; reopening the same run must not add calls (watch the server log: no second details request).
3. A treadmill/indoor activity (or any row with `hasPolyline: false` in raw_json) shows no Route tab and gets a `point_count = 0` row.
4. Toggle dark mode in Settings → tiles re-tint, route colors unchanged.
5. `.venv/Scripts/python.exe tests/test_gps_route.py` → 7/7 pass.

## Future improvements

- **Pace-colored trail** — color segments by pace or HR zone from the same details endpoint (raise `maxchart`, join streams to polyline timestamps). Makes intervals pop on the map.
- **Replay dot with live stats** — km/pace ticker following the head of the trail.
- **Lap-chart linkage** — hovering a lap bar highlights that segment on the map.
- **Route recognition** — hash the track shape to label recurring loops ("Dalfsen 11 km loop, 14th time").

---

*Last updated: 2026-07-19*
