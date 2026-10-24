# Personal Running Coach — Documentation

The project [README](../README.md) is the entry point. These pages go deeper, one feature at a time. Each follows the same skeleton ([_template.md](_template.md)) so you can always find purpose, implementation, configuration, limitations, and verification in the same spots.

## How to use these docs

- **Changing something structural?** Read [architecture.md](architecture.md) first — it records the decisions other components depend on, and why each was made.
- **Building on an existing feature?** Read its page first — purpose + known limitations save you from rediscovering scope decisions.
- **Verifying after a refactor?** Each page has a "Verification" section with a short manual smoke test.
- **Adding a new feature?** Copy [_template.md](_template.md) → `docs/<feature>.md`, write it as you build, link it from this index.

Working on the code — human or agent — starts with [architecture.md](architecture.md): the load-bearing decisions and the reasoning behind them.

## Cross-cutting

| Page | What it covers |
|---|---|
| [architecture.md](architecture.md) | The load-bearing decisions everything else follows from: rules-decide / LLM-speaks, the single SQLite file and its additive-migration rule, the methodology registry contract, `workout_structure` as the contract with the watch, server-rendered HTMX, and the token/`t()` layers. Plus the module map, the stack, and the honest limitations. |
| [same-origin-protection.md](same-origin-protection.md) | Why a no-login localhost app still needs CSRF defence, and the two checks that provide it: a `Host` allow-list (stops DNS rebinding) plus an `Origin`/`Referer` match on state-changing methods (stops cross-origin POSTs). Covers every route via one middleware; `RUNNING_COACH_ALLOWED_HOSTS` opts in to non-loopback hosts. |

## Documented features

| Page | What it covers |
|---|---|
| [dashboard.md](dashboard.md) | The `/` home surface — render order, the route's data contract, theme routing, and the widgets that live only here (status tiles, charts, recent runs). Maps to every per-card feature doc. |
| [onboarding.md](onboarding.md) | Getting-started wizard — the guided, skippable, resumable first-run flow (connect Garmin → sync → first plan → optional coach voice & location). Fresh-install auto-open vs upgrade suppression via the schema/migration default split. |
| [llm-coach.md](llm-coach.md) | LLM-voiced daily banner on the dashboard. Prompt layering, caching, fallback behavior. |
| [runners-diary.md](runners-diary.md) | Free-text notes + mood, three editing surfaces, timeline view, backfill. |
| [settings.md](settings.md) | `/settings` page, Garmin / Claude / About-you cards, plus the four stubs. |
| [daily-tips.md](daily-tips.md) | "Today's bonus" supplementary-activity card on the dashboard. Rules tree. |
| [adherence.md](adherence.md) | Per-week `done/planned` badge on plan week cards. |
| [week-wrapped.md](week-wrapped.md) | Dashboard "This week" stats strip (④, stats-wall style) for the active plan's current training week — live distance/time/plan-total/streak all week, flips to a celebratory DONE state with an LLM (or rules-based) coach line when every session is done. Forgiving ≥80% streak; resets each week. |
| [collapsible-previous-weeks.md](collapsible-previous-weeks.md) | On an active plan, past weeks collapse behind a "Show N previous weeks" toggle so the page opens on the current + upcoming weeks. Pure CSS `<details>`, no JS. |
| [post-run-flagship.md](post-run-flagship.md) | Dashboard "Today" hero flips from prescription → post-run actuals once the day's run is matched. |
| [route-map.md](route-map.md) | Route tab in the run-detail modal — the GPS track replays itself (~3 s, time-proportional) on a Leaflet/OSM map. Lazy one-time fetch from Garmin's activity-details endpoint into `activity_routes`; `hasPolyline` gate hides the tab for treadmill/indoor runs and Garmin-less setups. |
| [auto-open-last-run.md](auto-open-last-run.md) | When a Garmin sync pulls in a brand-new run, its detail modal opens automatically — the just-finished run is the first thing the runner sees. Newest-run before/after diff in `_run_sync`, `newRunDetected` HTMX event, one-time listener that opens the existing run-detail dialog. |
| [race-day-countdown.md](race-day-countdown.md) | Flagship-aside card for the A-race: days remaining, projected finish time (Garmin race predictor + Daniels VDOT fallback), and a 0-100 race-readiness score with on-track / building / behind verdict. |
| [auto-vdot-suggestion.md](auto-vdot-suggestion.md) | Dashboard banner that detects race-pace efforts (parkrun, 5k tempo, time trial) and offers a one-click recalibration of the plan's VDOT + paces. Keeps the plan honest as fitness improves. |
| [weather.md](weather.md) | Home location + today's forecast chip + LLM context. Open-Meteo, no API key. |
| [event-calendar.md](event-calendar.md) | `/calendar` tab — curated Dutch race calendar (shipped + seeded on first run), manual events, organiser enrichment, plan tie-in. |
| [event-swap.md](event-swap.md) | Swap a training day in the active plan for a calendar race event — race lands on its date, the given-up session (default: that week's long run) becomes a rest day, fully reversible from the workout modal. `plan_event_swaps` snapshots. |
| [design-system.md](design-system.md) | Single visual language (Tempo) — typography, color tokens, the `--ok`/`--warn`/`--bad` status palette every state pill · badge · banner · button reads from (and why `--accent` is never a status color), semantic palettes (workout-type / severity / distance-band), light/dark/auto mode, CSS architecture, editorial byline trio. |
| [language.md](language.md) | UI + LLM coach language selector (English / Nederlands). Settings picker, translation dictionary, system-prompt injection. |
| [execution-score.md](execution-score.md) | 0–100 execution score on completed plan workouts. Pace + distance + HR-zone composite. Colored corner ring on day cells and modal. |
| [workout-narrative.md](workout-narrative.md) | The plan-workout modal explains each session in a coach's voice — warm-up → main set → cool-down → *why* — instead of shorthand (`WU 2 km, 6×1000 m @ I pace…`). Derived from `workout_structure` on every render, so recalibrated paces and manual edits track for free; rules-based, no LLM. Paceless plans (C25K / Foppen) stay paceless; sessions that can't be safely narrated fall back to the engine's own words. |
| [strength-sessions.md](strength-sessions.md) | Optional bodyweight core / strength sessions auto-scheduled on rest days. Per-plan toggle, 5-session rotation with recovery-after-quality override. |
| [training-day-picker.md](training-day-picker.md) | Pick the weekdays you train on at plan creation. Engine assigns slot types (long / quality / easy) under Daniels' recovery rules. |
| [methodology-picker.md](methodology-picker.md) | Illustrated gallery tiles for the *Methodology* step of `/plans/new` — hero image, hook, fact-chips, clamped description + "Best for", coming-soon state. Goal-first browsing: distances are never disabled; the gallery filters to methodologies offering the selected goal. `MethodologyInfo` tile fields + per-id hero PNGs. |
| [methodology-explainers.md](methodology-explainers.md) | The **Read more** modal on each methodology tile — long-form editorial copy (who built it, the core idea, a typical week, why choose it) with in-house-style illustration placeholders + generation prompts. `explainers.py` content model, `_method_detail.html`, `/plans/methodology/{id}/detail`. All six authored in English + Dutch; Daniels' illustrations rendered, the rest show placeholder + prompt. |
| [long-run-sizing.md](long-run-sizing.md) | Marathon peak long runs size toward Daniels' 2.5 h ceiling (was a flat 32% of weekly volume → 20 km max on 61 km/wk). Two-step E+M `workout_structure` so the M-pace finish is guided on the watch; zone-aware pace recalibration; Steps strip in the workout modal. |
| [pfitzinger_18_55.md](pfitzinger_18_55.md) | Pfitzinger 18/55 marathon engine — 18 weeks, 4 mesocycles, medium-long runs + lactate threshold + VO₂max + marathon-pace long runs + 2 tune-up races. Methodology engine (not a transcribed table); paces reuse the Daniels VDOT zones. |
| [higdon.md](higdon.md) | Hal Higdon tiered engine — beginner-friendly. Six experience tiers (Novice 1/2, Intermediate 1/2, Advanced 1/2) × half (12 wk) / marathon (18 wk). Novice = pure easy mileage + one long run; higher tiers add goal-pace / tempo / hills / speed. Effort-first descriptions with VDOT paces attached under the hood. Introduces the generic `variant` (sub-plan) plumbing + `supported_goals` allow-list. |
| [plan-recommendation.md](plan-recommendation.md) | Rules-first enrollment guidance — "Recommended for you" badge + Higdon tier pre-select on `/plans/new`, driven by the fitness baseline plus one self-assessment question ("Can you run 10 minutes non-stop?") asked in onboarding / a form strip / Settings. |
| [couch-to-5k.md](couch-to-5k.md) | Couch to 5K engine — the classic NHS 9-week run/walk on-ramp for absolute beginners. 3 time-based sessions/week, paceless by contract (`uses_vdot_paces=False` + no pace idioms anywhere), graduation run on the long-run day, refuses windows <9 weeks. |
| [garmin-workout-push.md](garmin-workout-push.md) | Send a planned session to the watch — per workout and per week. The three-bucket pushability contract (simple / structured / never) and why typing a row `intervals` is a promise to hand it a `workout_structure`, the structure JSON shape (step types, distance-vs-duration ends, `pace.zone` targets, E/M/T/I/R zone tags for recalibration), re-push on edit and recalibrate, the empirically-derived Garmin enum IDs, and the taper-strides case study — a row that was unpushable for 20 weeks with no error anywhere. |
| [plan-reshape.md](plan-reshape.md) | Change an active plan's training days, long-run day, or race date from plan settings. Regenerate + splice: upcoming workouts rebuild on the new shape, history and completed runs stay locked, pushed workouts are cleaned off Garmin. |
| [desktop-launcher.md](desktop-launcher.md) | `install.cmd` sets up the app + creates RunSphera shortcuts (icon + taskbar identity); launch from a pinned shortcut into a native window (pywebview / Edge WebView2) with a branded splash + retry screen. Server in a background thread; closing the window quits. |
| [body-wellbeing-checkin.md](body-wellbeing-checkin.md) | Interactive full-body SVG (front + back, 27 regions) where the runner taps to log how their body actually feels — type, severity 1-10, optional structure name + note. Active issues with sparkline + lifecycle pills, month-grouped history timeline, heatmap with gradient + window picker. Dashboard widget + daily check-in prompt + run-detail RPE auto-suggest. LLM coach reads the body block as ground truth (Settings opt-out). |
| [nutrition-fueling.md](nutrition-fueling.md) | `/fuel` tab — body profile (Settings card + optional Garmin pre-fill) drives a deterministic engine: daily energy + carb-periodised macros, hydration, before/during/after fuelling for long runs, and concrete Dutch meals (breakfast/lunch/dinner/snack, diet-aware, date-rotated) scaled to the carb target. Dashboard tile + weekly carb-load strip + 7-day selector. Works with or without Garmin. Curated food list (not NEVO — licensing). |

## Design briefs (pre-build)

Features that have been designed but not yet built. The brief captures the decisions made up front so the eventual implementation has a frozen reference.

| Brief | What it covers |
|---|---|
| [post-marathon-recovery.md](post-marathon-recovery.md) | 28-day auto-generated recovery plan that picks up the day after the A-race marathon. Trigger rules, UI surfaces, per-day content, explanation layers, v1 minimum. **Now unblocked** — body-map (its hard dependency) shipped; sleep+HRV deferred to v1.1. |

## Features without their own page yet

These exist in the app but haven't been ported into this format. Backfill as they're touched.

- Garmin auth + token cache + MFA flow
- Daily ingest (activities, daily metrics, readiness, training status)
- Plan generation — Daniels VDOT engine
- Daily readiness coaching rules (GO / CAUTION / EASY / REST)
- Tap-to-apply swap
- Adherence matching (completed activities → planned workouts)

When a feature in this list gets new work, write its doc before / alongside the change.

## Cross-cutting topics (someday)

Bigger than a single feature, worth a dedicated page when they grow:

- `db-schema.md` — full table breakdown and migration log. [architecture.md](architecture.md) covers the migration *rule* and which tables are regeneratable; a per-column breakdown would go here.
- `garmin-api-notes.md` — empirical quirks in one place. Scattered today across [architecture.md](architecture.md), [garmin-workout-push.md](garmin-workout-push.md) and [strength-sessions.md](strength-sessions.md).
