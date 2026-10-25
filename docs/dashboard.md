# Dashboard (`/`)

> The home surface. It owns almost no logic of its own — it's the assembly point where the route gathers everything (coach voice, readiness, today's session, weather, charts, recent runs) and arranges it editorially. This page is the **map**: what renders, in what order, and which feature doc owns each piece.

## Purpose

`/` is the first thing the runner sees each day. Its job is to answer, top to bottom: *how am I doing, what's today, how's the weather, what do the numbers say, what have I run lately.* Every card is a window onto a feature documented elsewhere; this page documents the **surface** — the render order, the data contract the route assembles — plus the handful of widgets (status tiles, the two charts, the recent-runs table) that have no other home.

## How it works (user view)

### Render order

| # | Card | Owning doc |
|---|---|---|
| — | Welcome card *(fresh user)* / hero eyebrow greeting | — |
| 1 | Hero — display headline + status pill + coach pull-quote + reasons + suggestion + *Apply swap* | [llm-coach.md](llm-coach.md) · readiness rules below |
| 2 | Weather aside (inside the hero) | [weather.md](weather.md) |
| 3 | Weekly recap | [llm-coach.md](llm-coach.md) |
| 4 | Today's note editor | [runners-diary.md](runners-diary.md) |
| 5 | Flagship — running workout (post-run flip) **·** rest-day strength session (when scheduled) **·** plain rest card — + bonus/race aside | [post-run-flagship.md](post-run-flagship.md) · [strength-sessions.md](strength-sessions.md) |
|  | *(daily bonus tip + next race fold into the flagship's right-hand aside via `_flagship_aside.html`)* | [daily-tips.md](daily-tips.md) · [event-calendar.md](event-calendar.md) |
| 6 | Stats wall — 4 oversized cells (Training status · VO₂ max · Readiness · Acute/Chronic) | *this page* |
| 7 | Charts — weekly mileage (Plotly) + HR-zone bars (inline) | *this page* |
| 8 | Acute training load chart (28-day rolling load with optimal band) | *this page* |
| 9 | Recent runs table + Newer/Older pager | *this page* |

The page ends with two HTMX-loaded modals — the **run-detail** modal (from any recent-runs row) and the **event-detail** modal (from the race card).

### The header (from `base.html` blocks)

- **subhead** — last-ingest line (`last ingest: … (auto, N rows)`), or the "no data yet" prompt.
- **header_actions** — the **Sync from Garmin** button (`POST /ingest`, targets `#sync-status`; `hx-indicator="#dashboard-main, .garmin-sync"` drives the hero skeletons *and* keeps the button's own spinner — see below).
- **header_status** — `#sync-status`, where ingest result HTML lands.

## How it works (implementation)

### Route

[app.py](../runsphera/web/app.py) — `index(request)`. Redirects to `/auth` if there's no cached Garmin session, otherwise opens one connection and assembles the whole context in a single pass, then renders [index.html](../runsphera/web/templates/index.html).

### Data contract

Every key the template may read, and where it comes from:

| Context key | Source | Used for |
|---|---|---|
| `state` | `analytics.current_state` | training status, latest readiness, last ingest |
| `runs` | `analytics.recent_runs(n=10)` | recent-runs table (page 1) |
| `page` / `has_prev` / `has_next` | `1` / `False` / `count_runs() > 10` | recent-runs pager state |
| `weekly_chart` | `_weekly_mileage_chart(analytics.weekly_mileage(weeks=12))` | mileage chart |
| `acute_load_chart` | `_acute_load_chart(analytics.acute_training_load(days=28))` | acute-load chart |
| `zones` | `analytics.hr_zone_totals(days=7)` | inline HR-zone bars |
| `todays_workout` | `plan_service.todays_workout` | flagship card (carries `actual_*` once matched — see [post-run-flagship.md](post-run-flagship.md)) |
| `todays_strength` | `strength_service.todays_strength_session` | rest-day strength flagship — see [strength-sessions.md](strength-sessions.md) |
| `active_plan` | `plan_service.get_active_plan` | flagship plan name, rest-day card |
| `recommendation` | `plan_coach.daily_recommendation` | coach headline/pill/reasons/suggestion, `swap_available` |
| `coach_message` / `coach_generated_at` | `llm_commentary.daily_coach_message` | LLM daily voice |
| `weekly_recap` / `weekly_recap_generated_at` | `llm_commentary.weekly_recap` | Sunday recap |
| `llm_available` | `llm_commentary.connector.is_available()` | show/hide regenerate buttons |
| `daily_tip` / `tip_category_labels` | `tips_service.daily_tip` | bonus tip card |
| `weather` / `weather_hours` | `weather_service.current_weather` / `hourly_breakdown` | weather chip + 48h modal |
| `upcoming_races` | `race_calendar_service.list_favorites` | flagship-aside race card / carousel |
| `swap_available` | computed in-route | gate the *Apply swap* button |
| `first_name` / `home_location` | `app_settings` | greeting, location eyebrow |
| `is_fresh_user` | `not active_plan and not runs` | welcome card |
| `today_diary` / `today_iso` | `diary_service` / `date.today()` | today's-note editor |
| `vdot_suggestion` | `vdot_detection.detect_vdot_suggestion` | auto-VDOT banner — see [auto-vdot-suggestion.md](auto-vdot-suggestion.md) |
| `auto_sync_due` | `state.last_ingest.completed_at` >4h old | trigger the auto-sync `<script>` |
| `nav_active` | literal `"dashboard"` | nav highlight |

### Partials / includes

[_coach_message.html](../runsphera/web/templates/_coach_message.html) (daily voice pull-quote), [_weekly_recap.html](../runsphera/web/templates/_weekly_recap.html) (Sunday recap pull-quote), [_today_note_editor.html](../runsphera/web/templates/_today_note_editor.html) (diary inline), [_flagship_aside.html](../runsphera/web/templates/_flagship_aside.html) (bonus-tip + next-race aside shared by the running and strength flagships), [_daily_tip.html](../runsphera/web/templates/_daily_tip.html), [_weather_chip.html](../runsphera/web/templates/_weather_chip.html) / [_weather_modal.html](../runsphera/web/templates/_weather_modal.html).

### Loading skeletons (hero)

While the hero is waiting on fresh data, the two pieces that re-render — the display headline and the coach pull-quote — swap to shimmer placeholders so the layout holds its shape instead of showing stale text. Pure CSS, driven by HTMX's `htmx-request` class:

- **Garmin sync / dashboard refresh** — both **Sync from Garmin** buttons carry `hx-indicator="#dashboard-main, .garmin-sync"`, so the wrapper wears `htmx-request` for the whole (slow) `POST /ingest` (skeletons) *and* the button keeps its own `::after` spinner. (htmx 2's `this` token isn't resolved inside a comma-separated `hx-indicator` list — only `hx-target` special-cases it — so the button is referenced by its `.garmin-sync` class instead.) The follow-up `dashboardRefresh` re-fetch adds the class again on its own request, so the skeleton stays continuous through both until the swap lands.
- **Coach regenerate** — the ↻ button in [_coach_message.html](../runsphera/web/templates/_coach_message.html) uses `hx-indicator="closest #coach-head"`, so the pull-quote alone skeletons (and the ↻ icon keeps spinning) while `POST /coach-message/refresh` runs.

The CSS lives in [app.css](../runsphera/web/static/app.css) (`.tp-sk` shimmer + `.tp-dash-display-sk` / `.tp-coach-quote-sk`). Rules hide `.tp-dash-display` / `.tp-status-pill` / `.tp-coach-quote` and reveal the placeholders when an ancestor has `htmx-request`. Honors `prefers-reduced-motion` (shimmer animation off, static bars stay).

### Widgets that live only here

- **Stats wall** — Training status · VO₂ max · Readiness · Acute/Chronic (ACWR). Read straight from `state.training_status` + `state.latest_readiness`; no transform beyond formatting.
- **Weekly mileage chart** — `_weekly_mileage_chart` in [app.py](../runsphera/web/app.py) renders `analytics.weekly_mileage(weeks=12)` to inline Plotly; `|safe` into the template.
- **HR-zone inline bars** — built inline from raw `zones` totals as five vertical bars (Z1 left → Z5 right, fills grow bottom→top), colored with Garmin Connect's zone palette.
- **Acute training load chart** — `_acute_load_chart` renders the 28-day rolling acute load (black line + markers) over a moving green "optimal range" band. Mirrors Garmin Connect's own training-load chart.
- **Recent-runs table** — `analytics.recent_runs`; each row is HTMX-clickable into the run-detail modal (`GET /runs/{id}`). The table + a **Newer / Older pager** live in the `_recent_runs.html` partial inside a stable `#recent-runs-panel` wrapper. The pager buttons `hx-get /runs/recent?page=N` and swap the partial back in — 10 runs per page, up to 5 pages (50 runs, `RECENT_RUNS_PER_PAGE` / `RECENT_RUNS_MAX_PAGES`). Page 1 is the newest; `has_next` is gated on both the page cap and `analytics.count_runs()`. `/runs/recent` is declared **before** `/runs/{activity_id}` so "recent" isn't parsed as an id.
- **Auto-sync `<script>`** — when `auto_sync_due` is true, a tiny inline script clicks the visible Sync button 1.2s after page paint.

### Readiness coaching (the hero)

The GO/CAUTION/EASY/REST/DONE headline and the *Apply swap* affordance come from `plan_coach.daily_recommendation` (rules over readiness score + ACWR + today's planned intensity). Not yet its own doc — listed under "without their own page yet" in [README.md](README.md). The LLM layer that voices it *is* documented: [llm-coach.md](llm-coach.md).

**DONE** is the completion-aware status: once today's workout carries an `actual_activity_id`, the engine stops prescribing. This matters because readiness and ACWR are *lagging* — a hard interval session tanks readiness and spikes acute load by design, so the same rules that would sensibly say "swap this for an easy run" at 07:00 are, at 19:00, advising you out of a session already in the log. DONE keeps the numbers on screen (they're honest post-session state) but drops the suggestion and the swap button. The pill reads "Logged"; `apply_soft_swap` refuses the status outright.

## Configuration

- **Language** (Settings → Language) drives `t()`; English literals are i18n keys, Dutch overrides come from the translation dict. See [language.md](language.md).
- **Light/dark mode** (Settings → Mode) drives the visual variant — see [design-system.md](design-system.md).
- **Home location** (Settings) gates the weather chip and the hero location eyebrow.
- **Claude API key** (Settings) gates `llm_available` → the coach voice and regenerate buttons; absent, the rules headline still renders.

Otherwise the dashboard has no settings of its own — it's a projection of the data + the per-feature configs.

## Known limitations

- **Everything is recomputed per request.** One DB connection, ~14 calls, on every load. The LLM pieces are day-cached, but charts and analytics are not — fine at single-user scale, would need caching if this ever grew.
- **Bonus tip + next race fall below the flagship on narrow screens.** They live in the flagship aside; on phones they stack vertically.
- **Stats wall shows raw-ish values.** ACWR status, training-status phrase, readiness feedback are lightly formatted but not explained inline — the LLM banner is where interpretation happens.

## Verification

1. Visit `/`. Confirm the order matches the table above.
2. Toggle language to Nederlands — labels translate via `t()`.
3. Toggle mode (Light · Dark · Auto) — visual variant flips without page reload.
4. Click a recent-runs row → run-detail modal opens. Click the race card → event-detail modal opens.
5. With no Claude key: coach hero still shows the rules headline; regenerate buttons hidden. With a key: LLM voice appears.
6. Fresh user (no plan, no runs): the welcome card replaces the normal stack.
7. Click **Sync from Garmin** (or ↻ on the coach quote): the headline / quote swap to shimmer placeholders for the duration, then the real content lands — no layout jump.

## Future improvements

- **Auto-sync on load** is in place (>4h stale triggers); the next-evolution is a smarter trigger keyed on activity-since-last-sync rather than wall-clock.
- **Document the readiness rules engine** as its own page and link it here, the way the LLM layer already is.
- **Per-request caching** of the analytics/charts if the assembly cost ever matters.

---

*Last updated: 2026-07-03*
