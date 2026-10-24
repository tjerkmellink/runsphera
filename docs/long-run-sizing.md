# Marathon long-run sizing

> Peak-phase marathon long runs size toward Daniels' 2.5-hour ceiling instead of a flat percentage — and the M-pace finish now reaches the watch.

## Purpose

The Daniels engine used to size every long run as a flat share of weekly volume (32% on a 4-day week). For a modest-volume marathoner that quietly capped the whole campaign: a 61 km/wk plan (VDOT 43, ~3:47 projected marathon) peaked at a **20 km** long run — ~2:08 of time on feet for a ~3:47 race, while Daniels' own ceiling (the lesser of ~30% weekly volume or **2.5 hours**) left half an hour unused.

Discovered 2026-07-02 during a verification pass on a marathon plan (weeks 17–20 all showed 20 km). Two changes came out of it:

1. **Sizing** — marathon peak-phase long runs target `min(40% of weekly volume, the 2.5 h ceiling)`; the final build week bridges toward it; the final peak week steps down ~10% so the longest run lands 4+ weeks out.
2. **Structure** — peak marathon long runs carry a two-step `workout_structure` (E-pace segment + M-pace segment) so the M-pace finish is guided on the watch instead of living only in the description text.

## How it works (user view)

- **Plans calendar**: peak long-run titles read e.g. "Long 24 km incl. 8 km @ M pace".
- **Workout modal**: a new **Steps** strip renders any structured workout as chips — `E pace · 16 km @ 6:23/km → M pace · 8 km @ 5:23/km` (tempo and interval sessions get the same treatment: `WU 2 km → 7 km @ 4:50/km → CD 2 km`).
- **Manual edit**: the modal's edit form renders one editable row per pace segment (e.g. an *Easy* row and a *Marathon pace* row), each pre-filled with its own distance + pace. Changing them rebuilds the structure and keeps the zone tags, so a bespoke E/M shape survives editing and still recalibrates per-zone. (Before, the form collapsed the run to a single distance+pace pair, dropping the M-pace finish.)
- **Send to watch**: the pushed Garmin workout has two steps with their own pace targets; the watch alerts at the E→M transition. Previously it pushed as one 20 km step at easy pace.
- Weekly volume is unchanged — easy days shrink to fund the longer long run (e.g. 15+11+15+20 → 13+11+13+24 on a 61 km week).

## How it works (implementation)

- **Modules**:
  - `running_coach/plans/daniels.py` — `_LONG_RUN_CAP_S` (150 min), `_PEAK_LONG_M_FRACTION` (0.35), `_time_capped_long_km()` (longest run fitting the ceiling given the M-pace share), marathon sizing branch in `_allocate_week()`, zone-tagged structure in `_long_run_workout()`, `_structure_duration_s()` (exact duration for fully-paced structures).
  - `running_coach/plans/service.py` — `_rewrite_structure_pace()` is zone-aware: steps tagged `"zone": "E"|"M"|…` recalibrate against their own zone (untagged steps keep the old workout-level behaviour). Recalibrated durations come from the structure when it fully times itself. `_derive_title()` keeps the "incl. X km @ M pace" suffix. `_build_progression_structure()` rebuilds the segmented structure from the edit form's per-segment arrays (preserving each `zone`); `edit_workout()` takes a `segments` list and routes easy/long/recovery workouts with ≥2 distance segments through it. A single-segment or type-changing edit still drops the structure (stale-shape guard).
  - `running_coach/plans/garmin_sync.py` — no changes needed; `long` was already pushable and the builder uses a structure whenever present (the extra `zone` key is ignored).
- **Templates**: `_plan_workout_modal.html` — Steps chip strip (also shows for tempo/intervals); the edit form collects the distance-based `active` segments (`ns.active_segs`) and renders one `seg_km` / `seg_pace` / `seg_zone` row each when `_is_progression`. `_zone_labels` maps zone codes to the row headings (translated in `i18n.py`).
- **Endpoint**: `POST /plan-workouts/{id}/edit` accepts the `seg_km` / `seg_pace` / `seg_zone` parallel form arrays and zips them into `segments`.
- **DB**: no schema change. Peak long-run rows now hold a `workout_structure` like:
  `{"steps": [{"type": "active", "zone": "E", "end": {"distance_m": 16000}, "pace_s_per_km": 383}, {"type": "active", "zone": "M", "end": {"distance_m": 8000}, "pace_s_per_km": 323}]}`
- **Migration**: `scripts/resize_marathon_long_runs.py` applies the sizing to an existing plan's future, unmatched long + easy rows (last build week + peak weeks). UPDATE-only, dry-run by default, `--apply` to write. Run against plan 41 on 2026-07-02: weeks 17–20 went from 20/20/20/20 to 22/24/24/22 km. A pre-migration DB copy sits at `data/running_coach.pre-longrun-resize-20260702.db`.

Grounding: Daniels' Running Formula caps the long run at the lesser of ~30% of weekly mileage and 2.5 hours; his 2Q marathon plans pair long runs with M-pace blocks. The 40% weekly share deliberately exceeds his 30% guidance — on 4 runs/week the percentage rule starves the long run (Hansons-style plans defend similar shares on comparable volume); the 2.5 h ceiling remains the hard stop.

## Configuration

None user-facing. Constants in `daniels.py`: `_LONG_RUN_CAP_S = 9000`, `_PEAK_LONG_M_FRACTION = 0.35`, the 40% peak share and 36% build-bridge share inline in `_allocate_week()`.

## Known limitations

- Only the **marathon** goal gets ceiling-based sizing; half/10k keep the flat percentage (their race demands don't strain it).
- Half-marathon peak long runs ("incl. 5 km @ HM pace") still have no structure — same title-only problem this fixed for marathon, so per-segment editing doesn't apply to them yet.
- Per-segment editing edits the segments that exist; it can't **add** or **remove** a segment (e.g. turn a flat easy run into a two-pace progression). Change the type or move the workout for bigger reshapes.
- M pace is baked in at plan creation from `vdot_at_start` and only moves via the recalibrate flow (auto VDOT detection banner or manual plan-settings update) — see [auto-vdot-suggestion.md](auto-vdot-suggestion.md).

## Verification

```
.venv/Scripts/python.exe tests/test_daniels_long_runs.py           # 10 lock-down tests (sizing + structure)
.venv/Scripts/python.exe tests/test_workout_edit_progression.py    # 6 lock-down tests (per-segment editing)
.venv/Scripts/python.exe scripts/resize_marathon_long_runs.py      # dry run — should report 0 rows
```

In the app: open a peak-week long run on `/plans` — the modal shows the Steps strip and Target time ≈ 2:25 for 24 km; "Send to watch" produces a two-step workout in Garmin Connect. In **Manual edit**, the Easy and Marathon-pace segments each get their own distance + pace row; change the M-pace distance, save, and the title + Steps strip update to match.

## Future improvements

- Structure + watch guidance for the half-marathon peak long run (5 km @ HM pace).
- Add/remove segments in the edit form (currently edit-only) so any run can become a multi-pace progression.
- A "test race" nudge in mid-build so the VDOT (and thus M pace) is fresh before the M-pace sessions start.

---

*Last updated: 2026-07-22*
