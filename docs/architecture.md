# Architecture

> The load-bearing decisions everything else follows from, and why each was made.

## Purpose

RunSphera sits between a Garmin account, a training methodology, and a runner. Most of its design is downstream of a handful of choices. Writing them down here means a future change can argue with the reasoning instead of rediscovering it.

Read this before making structural changes. Per-feature detail lives in the pages indexed by [docs/README.md](README.md); this page only covers what crosses feature boundaries.

---

## 1. Rules decide, the LLM only speaks

Every verdict in the app is produced by deterministic Python:

| Verdict | Where it is decided |
|---|---|
| GO / CAUTION / EASY / REST | [plans/coach.py](../running_coach/plans/coach.py) |
| The whole training plan | the methodology engines under [plans/](../running_coach/plans/) |
| Execution score (0–100) | [execution_score.py](../running_coach/execution_score.py) |
| Race readiness + projected finish | [analytics.py](../running_coach/analytics.py) |
| Energy, carbs, hydration, meals | [nutrition/engine.py](../running_coach/nutrition/engine.py) |
| Which supplementary activity to suggest | [tips.py](../running_coach/tips.py) |

The LLM layer ([llm/](../running_coach/llm/)) receives a decision that has already been made and phrases it. It never chooses the training load, never overrides a rule, and never has its output parsed back into application state — the cached text is displayed and nothing more.

**Why:** a prescription that changes because a sampling temperature changed is not a training plan. Determinism also means the whole suite can assert on exact numbers, and the app stays fully functional with no API key and no network.

**Consequence:** when a feature needs a new judgement, the judgement goes in Python and the prompt gets told about it. Moving a decision into a prompt is a regression, even when the output looks better. LLM output is cached in `llm_cache`, keyed per calendar day (or per activity for run reactions), and invalidated explicitly by the writers in [llm/commentary.py](../running_coach/llm/commentary.py).

---

## 2. Local-first, one SQLite file, additive migrations only

Everything lives in a single file: `data/running_coach.db` (override with `RUNNING_COACH_DB`). No server, no account, no cloud. Garmin credentials are sent to Garmin once and dropped; only the session token is cached, in `.garmin_tokens/`.

Schema handling in [db.py](../running_coach/db.py) has two halves:

* `SCHEMA` — the `CREATE TABLE IF NOT EXISTS` script. It runs on every connect and is **ignored by SQLite for tables that already exist**.
* `_MIGRATIONS` — an ordered list of `ALTER TABLE` statements, each wrapped in a try/except that swallows "duplicate column name" and "no such column" so re-running is idempotent.

**Never add a column by editing a `CREATE TABLE` in `SCHEMA` alone.** Existing databases will silently never get it. Add it to `SCHEMA` for fresh installs *and* append an `ALTER` to `_MIGRATIONS` for existing ones.

`connect()` sets WAL journal mode, a 5-second busy timeout, and `foreign_keys = ON`, and applies the schema once per database file per process — re-running `executescript(SCHEMA)` on every connect contended with in-flight writes during long syncs.

### What is regeneratable, and what is not

| Regeneratable from Garmin | Lost forever if deleted |
|---|---|
| `activities`, `activity_laps`, `activity_routes` | `plans`, `plan_workouts`, `plan_strength_sessions`, `plan_event_swaps` |
| `daily_metrics`, `training_readiness`, `training_status` | `diary_entries` |
| `ingestion_runs` | `body_issues`, `body_severity_log`, `body_clear_logs` |
| `weather_cache`, `llm_cache` (caches) | `runner_races`, manual `race_events`, `app_settings` |

Every Garmin-sourced row keeps the untouched response in a `raw_json` column, so an unmodeled field is recoverable without a re-fetch.

**Consequence:** the right-hand column is the user's own history and has no backup. Never delete from those tables to clean up after a test or a debugging session — use a temp database (see [Testing](#testing)). Destructive migrations are not an option; a column that is no longer read stays in the schema as dead data, as `app_settings.theme` does today.

---

## 3. Methodologies are engines behind one registry contract

A plan is generated, not transcribed. Each methodology is a class implementing a single method:

```python
Methodology.generate(params: PlanParams) -> list[PlannedWorkout]
```

[plans/\_\_init\_\_.py](../running_coach/plans/__init__.py) holds `_REGISTRY`, mapping a stable id to `(MethodologyInfo, class | None)`. A `None` class is a "coming soon" tile — surfaced in the UI, not selectable.

`MethodologyInfo` is not decoration; it **is** the contract between an engine and the UI. The flags that change behavior:

| Flag | What it promises |
|---|---|
| `fixed_schedule` | The engine owns the weekly shape. The form neutralises the day pickers and the server ignores their submitted values. |
| `uses_vdot_paces` | `False` means the plan is effort-based and paceless. Recalibration and soft-swap refuse to run — stamping E/M/T/I/R paces onto effort cues corrupts them. |
| `requires_race_date` | The race date stays mandatory. Everything else synthesizes a goal date on the final week's long-run day. |
| `supported_goals` / `force_goal` | Goal allow-list. Empty means all goals. |
| `variants` | Sub-plans (Higdon's experience tiers). The chosen id rides through `PlanParams.variant` and persists to `plans.variant` so a reshape regenerates the same variant. |
| `fixed_days_per_week` / `preferred_day_offsets` | The engine owns the session count but not the weekday placement (Couch to 5K). |

**Why a registry of engines rather than stored plan tables:** the plan has to be calibrated to this runner's VDOT and this runner's four-week volume baseline, on their chosen days, for a window ending on their race date. A table cannot do that. The one transcribed plan in the codebase — Foppen's 7 Heuvelen — is the exception that needs `fixed_schedule` and `uses_vdot_paces=False` to coexist with the rest.

**Consequence:** adding a methodology means adding an engine plus a registry entry plus a page under `docs/`. Feeding form defaults from the engine's own constants (rather than retyping them in a template) is what keeps the form from drifting out of sync with what `generate()` would actually do.

---

## 4. `workout_structure` is the contract with the watch

The watch is a render target, not a source of truth. [plans/garmin_sync.py](../running_coach/plans/garmin_sync.py) splits workout types into three buckets:

| Bucket | Types | Needs `workout_structure`? |
|---|---|---|
| Simple | `easy`, `long`, `recovery`, `race` | No — one distance step at the headline pace |
| Structured | `tempo`, `intervals` | **Yes** — no structure means not pushable |
| Never | `rest`, `cross` | n/a |

**Typing a row `intervals` is a promise to also hand it a structure.** Break that promise and nothing is rejected loudly: the push button simply never renders and the bulk push counts the row as "skipped". That failure mode cost 20 weeks of invisible breakage once already — see the taper-strides case study in [garmin-workout-push.md](garmin-workout-push.md).

Structure steps carry a `zone` tag (`E` / `M` / `T` / `I` / `R`). That tag is what lets a pace recalibration rewrite a mixed-pace session correctly — the peak marathon long run has an E segment and an M segment, taper strides have E warm-up and cool-down around R reps. Untagged steps fall back to the workout-level pace, so pre-tag structures keep working.

The DB columns `garmin_workout_id` and `pushed_at` **are** the push state; nothing is cached alongside them. Editing a pushed workout deletes the Garmin copy and re-uploads, so the watch never holds a stale version.

**Consequence:** pushability, sport-type acceptance, and in-Connect animation are three separate gates. A workout can be FIT-valid and pushable and animated and still be rejected by the watch on *Send to device* — see [strength-sessions.md](strength-sessions.md).

---

### `week_number` must agree with `planned_date`

`get_plan_weeks` groups rows by `week_number`, and the plans page renders one
card per group. `planned_date` decides *when* a session happens; `week_number`
decides *where it appears*. Any write that changes one must change the other.

`move_workout` broke this: it updated `planned_date` and `day_of_week` and
left `week_number` alone. Moving Sunday's long run to Monday kept it filed in
the previous week, where an elapsed week renders behind the "Show N previous
weeks" collapse — so the session looked, to the runner, like it had
disappeared. The swap case mis-filed *both* rows, leaving one week spanning
eight days with two Mondays and the next with two Sundays.

`_week_for_date()` resolves the owning week from the plan's own rows rather
than from arithmetic on the start date, because engines align weeks as they
like and a `fixed_schedule` plan need not start on a Monday. Every engine
emits all seven days per week, rest days included, so each date in the plan
window lands in exactly one week.

Found by moving a workout in the running app and looking at the page — five
rounds of static review never touched it.

## 5. Server-rendered HTMX, no build step

FastAPI serves full pages and HTML fragments from Jinja templates in [web/templates/](../running_coach/web/templates/). Templates whose names start with `_` are fragments returned to an `hx-target`. There is no bundler, no npm, no JSON API, and no client-side framework. Charts are Plotly HTML rendered on the server.

[web/app.py](../running_coach/web/app.py) is one large route module (~100 routes). That is deliberate for now: the routes are thin, and the logic they call lives in the service modules. Splitting it is a refactor worth doing on purpose, not as a side effect of adding a feature.

**Why:** one language, one process, one deployment artifact, and a page that works before any JavaScript loads. The app ships to its user as a folder with an `install.cmd` in it.

**Consequence:** interactivity is an HTMX attribute and a fragment route, not a component. State that the server does not know about does not exist. Native browser dialogs (`confirm()`, `alert()`) are banned — they are unstyleable and break the HTMX flow; use an inline confirm strip instead (pattern in `_plan_settings_modal.html`).

---

## 6. One visual language, one text layer

**Colour goes through tokens.** The status palette (`--ok` / `--warn` / `--bad` / `--info`, each with a `-solid` variant for filled chips) is the single answer to "is this good, worrying, or bad?". Never hardcode a green, amber, or red hex. `--accent` is the brand voice and the current-item marker, never a status — because it reads as red-orange, state signalled through it looks like an error. Full rules in [design-system.md](design-system.md).

**Text goes through `t()`.** English literals are the lookup keys, so an untranslated string renders in English instead of throwing. `t` and `plural` are registered as per-request Jinja globals already bound to the runner's locale. Two languages today (`en`, `nl`); adding a third means extending `LANGUAGES` and dropping a dict alongside `_NL` in [i18n.py](../running_coach/i18n.py).

**Consequence:** a user-facing string added without `t()` is a bug that only shows up for Dutch readers, and a hardcoded hex is a bug that only shows up in the other colour mode. Both are invisible to the test suite.

---

## 7. The LLM provider is a seam; Garmin is becoming one

[llm/connector.py](../running_coach/llm/connector.py) is the single dispatcher between the app and three providers (`_anthropic`, `_openai`, `_gemini` under `llm/providers/`). It resolves the active provider from settings, returns a uniform `LLMResult`, and reports `is_available()` for the **active** provider only — so the dashboard degrades gracefully when the runner switches to a provider they have not configured. Adding a provider is a new `providers/_<name>.py`, a registry entry, a storage column, and a settings tab.

Ingest has no equivalent seam yet. [garmin.py](../running_coach/garmin.py) and [ingest.py](../running_coach/ingest.py) assume one account on one vendor, and Garmin's field names reach the schema directly. Widening this — Samsung, Apple, Polar, Oura, and a mobile client — is designed but not built: see the multi-device plan and the mobile MVP brief.

**Consequence:** new ingest code should not deepen the Garmin assumption any further than it has to. When a choice is cheap, prefer the shape that survives a second provider.

---

## Layout

```
running_coach/
├── db.py              # SCHEMA + _MIGRATIONS + connect()
├── garmin.py          # Garmin login wrapper (token cache + MFA)
├── ingest.py          # CLI: Garmin → SQLite, idempotent
├── analytics.py       # Dashboard read queries + format helpers
├── execution_score.py # 0–100 score on completed workouts
├── body.py            # Body check-in domain
├── body_svg.py        #   …and its 27-region front/back diagram
├── diary.py           # Diary CRUD + Garmin feel/RPE labels
├── weather.py         # Open-Meteo forecast + caching
├── race_calendar.py   # Curated + manual race events
├── gps_route.py       # Activity polyline fetch/decode
├── laps.py            # Lap + split extraction
├── settings.py        # app_settings key/value
├── tips.py            # Daily supplementary-activity rules
├── i18n.py            # t() / plural() + the EN→NL dictionary
├── desktop.py         # pywebview window; uvicorn on a background thread
├── plans/             # Methodology registry + engines + plan service
│   ├── methodology.py #   the contract: MethodologyInfo, PlanParams, PlannedWorkout
│   ├── daniels.py · pfitzinger.py · higdon.py · c25k.py · foppen_7heuvelen.py
│   ├── service.py     #   plan CRUD, push, edit, reshape, recalibrate, adherence
│   ├── garmin_sync.py #   PlannedWorkout → Garmin RunningWorkout + pushability
│   ├── narrative.py   #   renders a session in a coach's voice
│   ├── matcher.py · coach.py · readiness.py · swapper.py · event_swap.py
│   ├── recommend.py · vdot_detection.py · explainers.py
├── strength/          # Optional core/strength sessions (library, scheduler, push)
├── nutrition/         # Fuel engine, food library, meal assembly
├── llm/               # Dispatcher + prompts + context + providers/
└── web/               # FastAPI app, templates/, static/
```

## Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12+ |
| Storage | SQLite, one file, WAL |
| Garmin API | `garminconnect` (unofficial) |
| Web | FastAPI + Jinja2 + HTMX, no build step |
| Charts | Plotly (server-rendered HTML) |
| Desktop shell | pywebview over Edge WebView2 |
| LLM | Anthropic / OpenAI / Gemini, optional |
| Tests | plain `assert` functions, run under pytest |

## Testing

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

383 tests, roughly 6 seconds, no network. The convention is plain module-level `def test_*()` functions with bare `assert`s — no fixtures, no classes, no pytest-specific API — plus a `main()` runner at the bottom so each file is also executable on its own against a fresh checkout. Keep it that way; it is what lets a test double as a readable statement of what the methodology promises.

Tests that need a database build one with `tempfile.mkdtemp()` and `connect(tmp)`, or point `RUNNING_COACH_DB` at a temp file. A test must never touch `data/running_coach.db`.

## Known limitations

* **One runner, one machine.** No accounts, no auth, no concurrency beyond WAL. Multi-user is a roadmap item, not a seam that exists.
* **`web/app.py` is a ~3,700-line route module.** Thin routes, but it is past the size where finding a route is pleasant.
* **The Garmin library is unofficial.** Enum IDs and field names in `garmin_sync.py` are empirically derived and occasionally contradict the library's own constants. Verified values are documented in [garmin-workout-push.md](garmin-workout-push.md) — do not "fix" them back.
* **Coverage is partial.** The network path, the LLM providers, the desktop launcher, and template rendering are unverified by the suite.
* **Ingest is Garmin-shaped** all the way into the schema. See decision 7.

---

*Last updated: 2026-10-23*
