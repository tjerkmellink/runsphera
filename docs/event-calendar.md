# Running event calendar

> Dedicated `/calendar` tab listing upcoming Dutch road races, plus a "Your races" section on the dashboard. The app **ships with a curated set of enriched races** (seeded on first run); you can add your own manually. Clicking a supported distance kicks off the plan-creation flow with date + goal pre-filled.

## Purpose

Until now, the runner had to know their next race externally and type its date into the plan-creation form. The calendar gives a structured catalogue with a one-click path from "this race looks interesting" to "training plan toward it". It also enables the dashboard to count down to favorited races and (via the LLM context) lets the coach reference upcoming events.

## How it works (user view)

### Top-nav

A new **Calendar** tab between Plans and Diary. Active when the URL is under `/calendar`.

### `/calendar` page

Top to bottom:

- **Your races** (card, only shown when at least one event is saved) — upcoming races the runner has saved, with date, name, chosen distance, city, and an "A-race" pill for the event tied to the active plan. Clicking a card opens the **event detail modal** (same as the calendar chips/rows). Each card also carries a **Plan** pill (jumps straight to `/plans/new?from_event={id}`) and a **Remove** button to unfavorite; both are exempt from the card click.
- **Toolbar** — view toggle (**List** / **Agenda**) on the left, distance filter pills on the right (All · 10k · 15k · Half · Marathon). Both selections survive reloads via the `?view=` and `?distance=` query strings.
- **List view** — month-grouped event list. Each event renders as a row with date stamp on the left, name + city + province, a row of distance pills, and an actions column with **Save**, one **Plan {distance}** button per supported plan distance (10k / 15k / half / marathon), and a `↗` link to the event's **organiser site** (when set).
- **Agenda view** — one Mon-Sun calendar grid per month. Each day cell shows up to 3 event chips colored by primary distance (5k cyan, 10k blue, 15k amber, half orange, marathon red, ultra dark-red, other slate). Chips open the **event detail modal**. Days with more than 3 events show a "+N more" link to the month's section in list view. Today's cell gets an accent ring.
- **Add an event manually** (collapsible) — for races not in the curated set. Free-form name, date, distance, city, organiser URL.

### Event detail modal

Clicking any event row (list view), chip (agenda view), or saved-race card (the "Your races" section) opens a native `<dialog>` with:

- Hero image (if enriched) and event name, date, location.
- Distance pills and a free-text description (if enriched).
- Buttons: **↗ Organiser site** (when set), and the **Save** + **Plan {distance}** actions.
- An expandable **Enrich this event** section with two forms:
  - **Fetch + extract**: paste the organiser URL — the app fetches the page with a browser User-Agent, parses `<meta property="og:image">`, `og:description`, `og:title` (falling back to `<h1>` + first `<p>` + `<title>`), resolves the image URL to absolute, **downloads the image locally** to `data/event_images/event-{id}-{8charhash}.{ext}`, and writes the enrichment fields. Re-running for the same event replaces the prior local image.
  - **Edit manually**: textareas for description, organiser URL, hero image URL — useful when the auto-scrape misses (every organiser site is different).

Both forms re-render the modal body inline via HTMX — no full page reload, immediate feedback.

### From a calendar event to a plan

Clicking **Plan {distance}** on an event takes you to `/plans/new?from_event={id}&distance_km={km}&distance_label={label}`. The form shows a banner ("Building a plan toward {name} on {date}…") and pre-fills date, goal type, and title. Pick a methodology and submit. The new plan is created **and** a `runner_races` row is inserted linking the event to that plan with `is_a_race=1`.

### Dashboard

A small **"Your races"** strip appears above the daily-tip card when at least one upcoming race is saved. Shows the next 5 races with date, name, chosen distance, and an "A-race" pill where applicable. Links to `/calendar` for the full view.

## How it works (implementation)

### Modules

- [runsphera/race_calendar.py](../runsphera/race_calendar.py) — single module with:
  - **Distance / goal helpers**: `goal_type_for_distance(km)` (maps to `'10k'` / `'15k'` / `'half_marathon'` / `'marathon'` with tolerance), `province_name(code)`, `primary_category(event)` (longest supported distance → chip color bucket).
  - **Writes**: `add_user_event(...)`, `favorite(...)`, `unfavorite(...)`.
  - **Reads**: `list_events(...)`, `get_event(...)`, `list_favorites(...)`, `is_favorited(...)`, `group_by_month(events)`, `build_month_grids(events)` (per-month Mon-Sun cell grids for the agenda view).
  - **Curated set**: `seed_events_if_empty(conn)` — loads `runsphera/data/curated_events.json` into `race_events` on first run only (empty-table guard), mirroring the strength-library seeder; wired into `db.connect()`. `export_curated_events(conn)` — snapshots the DB into the shippable list (enriched-only; drops `external_id`; sets `source = personal-running-coach`; keeps only external hero-image URLs; **does not mutate the source DB**). This is the freeze tool behind the committed JSON.
  - **Enrichment**: `scrape_event_page(url)` + helpers fetch an organiser page, parse `og:*` meta tags, download the hero image locally, and save the fields.

### Templates

- [calendar.html](../runsphera/web/templates/calendar.html) — the page (renders list or agenda based on `view_mode`); hosts the event-detail `<dialog>` wrapper at the bottom.
- [_event_row.html](../runsphera/web/templates/_event_row.html) — one race in the list view; clickable to open the modal.
- [_calendar_agenda.html](../runsphera/web/templates/_calendar_agenda.html) — monthly calendar grids; chips are `<button>`s that open the modal via HTMX.
- [_event_detail_modal.html](../runsphera/web/templates/_event_detail_modal.html) — modal body. Re-rendered after each enrich / manual-save so the view updates inline.
- [index.html](../runsphera/web/templates/index.html) — adds the "Your races" strip on the dashboard.
- [plans_new.html](../runsphera/web/templates/plans_new.html) — shows the prefill banner + carries hidden fields when launched from an event.
- [base.html](../runsphera/web/templates/base.html) — nav link + all CSS.

### Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/calendar` | Render the tab. Reads `?distance=` + `?view=`. |
| `POST` | `/calendar/events` | Add a manual event. Validates ISO date + numeric km. |
| `POST` | `/calendar/events/{id}/favorite` | Save an event (no distance chosen — used by the calendar's "Save" button). |
| `POST` | `/calendar/events/{id}/delete` | Delete an event (blocked if it has a linked plan). |
| `POST` | `/runner-races/{rr_id}/delete` | Unfavorite. |
| `GET`  | `/calendar/events/{id}/detail` | Render the event-detail modal body (HTMX target). |
| `POST` | `/calendar/events/{id}/enrich` | Form: `url` → scrape organiser page, download hero image, save fields. Returns updated modal body. |
| `POST` | `/calendar/events/{id}/manual` | Form: `organizer_url`, `description`, `hero_image_url` → save directly. Returns updated modal body. |
| (static) | `/event-images/<filename>` | FastAPI `StaticFiles` mount over `data/event_images/`. |
| `GET`  | `/plans/new` | Accepts `?from_event=N&distance_km=K&distance_label=…` for prefill. |
| `POST` | `/plans/new` | Accepts `from_event_id`, `chosen_distance_km`, `chosen_distance_label` as hidden form fields; on successful create, inserts a `runner_races` row with `is_a_race=1` linking event → new plan. |

Cache invalidation: favoriting / unfavoriting / adding events all drop today's LLM coach cache so the coach picks up the new context on the next dashboard render.

### DB

```
race_events
─ id               INTEGER  PK
─ external_id      TEXT     UNIQUE — legacy import dedup key. NULL on the shipped curated set + manual entries.
─ source           TEXT     'personal-running-coach' (curated/shipped) | 'user' (manually added)
─ name             TEXT     not null
─ race_date        TEXT     ISO date, not null
─ city             TEXT
─ province         TEXT     2-letter NL code
─ country_code     TEXT     default 'NL'
─ distances_json   TEXT     JSON array [{km, label}, ...]
─ description      TEXT     short paragraph for the detail modal
─ organizer_url    TEXT     official race website (set by enrichment / manual add); the only event link
─ hero_image_url   TEXT     local '/event-images/…' download, or an external http(s) URL (shipped set keeps only external)
─ enriched_at      TEXT     ISO timestamp of last successful enrichment
─ created_at       TEXT
─ updated_at       TEXT

runner_races
─ id                    INTEGER  PK
─ event_id              INTEGER  FK race_events.id  ON DELETE CASCADE
─ plan_id               INTEGER  FK plans.id        ON DELETE SET NULL
─ chosen_distance_km    REAL
─ chosen_distance_label TEXT
─ is_a_race             INTEGER  0|1 — flag for the A-race driving the linked plan
─ notes                 TEXT
─ added_at              TEXT
```

The split keeps the catalogue and the runner's selection apart. Multiple `runner_races` can point to the same event (e.g. a runner who races the same loop yearly).

### Curated-seed format

The committed [runsphera/data/curated_events.json](../runsphera/data/curated_events.json) is a JSON array of event dicts — `name`, `race_date`, `city`, `province`, `country_code`, `distances` (`[{km, label}]`), `description`, `organizer_url`, optional external `hero_image_url`, and `source: "personal-running-coach"`. To change what ships: curate events in the running app (add manually / enrich / delete the irrelevant ones), then regenerate the file from the live DB with `export_curated_events` (a one-off `python -c` call) and commit it over the old one.

## Configuration

- **Shipped seed** — `runsphera/data/curated_events.json` (committed). On first run, `seed_events_if_empty` loads it into an empty `race_events`. Subsequent runs are no-ops (the table is non-empty), so a runner's own added/enriched events are never clobbered.

## Known limitations

- **The shipped set goes stale.** It's a frozen snapshot — events drift into the past over time (display already hides past-dated events via `list_events`'s future-only filter, but the catalogue doesn't grow on its own). Regenerate + commit the JSON periodically to refresh it.
- **Enriched images aren't bundled.** The freeze drops local `/event-images/…` hero paths (those files are gitignored), keeping only external image URLs — so most curated events ship text-only until re-enriched. Bundling the images into the repo is a deferred follow-up.
- **NL-centric.** Province codes and the default `country_code = 'NL'` assume Dutch races. Foreign races can still be added manually (just set `country_code` to the right ISO code), but the UI doesn't help much with non-NL discovery.
- **No geocoding for events.** We store `city`/`province` but not lat/lon, so the location-aware filter is country-level only. Geocoding all events would be slow + Open-Meteo doesn't love bulk requests; better solved on-demand if it ever matters.
- **One A-race per plan.** The `is_a_race=1` flag is enforced by convention, not by a uniqueness constraint. If two `runner_races` rows are marked as A-race for the same plan, both show as "A-race" — should pick the most recent one.
- **No tune-up race logic.** Saving a non-A race doesn't influence the plan structure. A future pass could insert a mini-taper around a saved race date.
- **No distance picker on the "Save" button.** Saving from `/calendar` doesn't capture which distance you intend to do — it just bookmarks the event. The chosen distance only enters the picture via the "Plan {distance}" flow.

## Verification

1. **First-run seed.** Against a fresh DB (empty `race_events`), open `/calendar` — it shows the curated set seeded from `curated_events.json`. Re-opening the app doesn't duplicate (seeder no-ops on a non-empty table).
2. **Browse + filter.** Distance filter pills update the list. The "Half" filter should hide events with no half-marathon distance.
3. **Save / remove.** Click **Save** on an event. The row gets an accent border and shows a "✓ saved" pill. The event also appears at the top of `/calendar` and in the dashboard's "Your races" strip. Click **remove** in either place — the event leaves both lists.
4. **Plan from race.** Click **Plan half marathon** on a half-marathon event. You land on `/plans/new` with a green banner *"Building a plan toward {name} on {date}…"* and the date, goal type, and title pre-filled. Pick a methodology, submit. Your plan is created and the event appears in **Your races** with the **A-race** pill.
5. **Manual add.** Open the **Add an event manually** disclosure, fill name + date + distance, submit. The event appears in the list.
6. **Agenda view toggle.** Click **Agenda** in the toolbar. The page swaps to monthly Mon-Sun grids. Today's day cell has an accent ring; chips are colored by primary distance and open the detail modal. The toggle and distance filter compose (URL has both `view=` and `distance=`).
7. **Detail modal.** Click any event row (list view) or chip (agenda view) — the modal opens with the event's static info. ESC or backdrop click closes it.
8. **Auto-enrichment.** In the modal, expand **Enrich this event**, paste an organiser URL (e.g. `https://www.vrijstadvianenloop.nl/`), submit. The modal refreshes inline showing the hero image, description, and organiser link. The image file lands at `data/event_images/event-{id}-{hash}.{ext}`.
9. **Manual edit fallback.** Expand the **Or edit manually** sub-section, change the description / organiser URL / hero image URL, save. Modal refreshes with the new values.
10. **Re-enrichment cleans up.** Run the enrich form twice with different organiser URLs. The local `data/event_images/event-{id}-*` files should contain only the most recent image — the previous one is removed.

## Future improvements

- **Hourly weather on the race-day forecast.** For events within the 16-day forecast window, pull and display the race-day weather inline on the event card.
- **Tune-up race logic.** When a non-A race is saved and the date falls during the active plan, the planner could automatically insert a mini-taper week ahead of it (lighter Wed/Thu, faster Sat shakeout).
- **Distance picker on Save.** When an event has multiple distances, a small dropdown next to Save lets the runner record *which* one they plan to do — then it surfaces on the dashboard as `"15 km · Mike Foppen 15"` rather than just the event name.
- **Geocoded events.** Pre-geocode city → lat/lon; show distance from the runner's home location, sort by proximity.
- **Past races view.** A "Completed" tab listing past races the runner saved, with the matched activity if one exists (link via date + distance). Builds a history of races you've done.
- **Bundle curated hero images.** Ship the enriched images alongside the JSON so the curated set arrives with artwork, not just text.

---

*Last updated: 2026-06-05*
