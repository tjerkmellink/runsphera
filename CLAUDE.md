# RunSphera

A local-first running coach. It pulls a runner's data from Garmin Connect into SQLite, generates a training plan around a race goal, pushes the planned sessions back to the watch, and explains each day in a coach's voice.

One runner, one machine, no accounts, no cloud. Garmin credentials never leave the laptop.

**Technology:** Python 3.12+, FastAPI, SQLite, Jinja, HTMX. No build step. Server-rendered throughout.

**Tests:** plain `assert` functions under `tests/`, run with pytest. No fixtures, no classes, no new dependencies without explicit authorization.

Run the test suite:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

383 tests, roughly 6 seconds, no network and no Garmin. Tests that need a database build a temporary one; none of them may touch `data/running_coach.db`.

`pytest` is declared in `requirements-dev.txt`, not `requirements.txt` — install both before running the suite. Each test file also carries a `main()` runner, so a single file executes without pytest at all.

Coverage is deliberately partial: plan engines, scoring, matching and nutrition are covered; the Garmin network path, the LLM providers, the desktop launcher and template rendering are not.

Run the application:

```powershell
.venv\Scripts\python.exe -m runsphera.web
```

This serves the dashboard at `http://localhost:8000`.

```powershell
.venv\Scripts\python.exe -m runsphera.desktop
```

This opens the native window (pywebview over Edge WebView2), which is how the runner actually launches it — from the RunSphera shortcut that `install.cmd` creates.

For development with auto-reload:

```powershell
.venv\Scripts\uvicorn.exe runsphera.web.app:app --reload --port 8000
```

## Essential documentation

Before making structural changes, read [docs/architecture.md](docs/architecture.md).

It records the decisions other components depend on. Understand the reasoning before changing one, and challenge it when there is a concrete reason to.

Other documentation:

* [docs/README.md](docs/README.md): index of every feature page, plus the conventions.
* [docs/roadmap.md](docs/roadmap.md): done · bugs · committed next-up · backlog. The living priority list.
* [docs/design-system.md](docs/design-system.md): the single visual language — tokens, status palette, semantic palettes.
* [docs/garmin-workout-push.md](docs/garmin-workout-push.md): the push path and its contracts.
* [docs/_template.md](docs/_template.md): the skeleton every feature page follows.

Read the documentation relevant to the task before changing behavior. A line in this file never replaces the feature page.

# Architecture in Six Facts

## 1. Rules decide; the LLM only speaks

Every verdict — GO/CAUTION/EASY/REST, the plan itself, the execution score, race readiness, fuel targets, the daily tip — is deterministic Python. `runsphera/llm/` receives a decision that has already been made and phrases it.

The LLM never chooses training load, never overrides a rule, and its output is never parsed back into application state.

**When a feature needs a new judgement, the judgement goes in Python and the prompt is told about it.** Moving a decision into a prompt is a regression even when the output reads better.

The app must stay fully functional with no API key and no network. See architecture decision #1.

## 2. One SQLite file, additive migrations only

`data/running_coach.db` (override: `RUNNING_COACH_DB`). Schema lives in `db.py` as `SCHEMA` plus an ordered `_MIGRATIONS` list of idempotent `ALTER TABLE` statements.

`CREATE TABLE IF NOT EXISTS` is silently ignored for a table that already exists. **Never add a column by editing `SCHEMA` alone** — add it there for fresh installs *and* append an `ALTER` to `_MIGRATIONS` for existing databases.

Garmin-sourced tables are regeneratable and carry `raw_json`. Plans, workouts, diary entries, body issues and saved races are **not** regeneratable and have no backup.

**Never delete rows from `plans`, `plan_workouts`, `diary_entries` or `body_*` to clean up after a test or a debugging session.** Real training history has been lost this way. Use `tempfile.mkdtemp()` + `connect(tmp)`, or point `RUNNING_COACH_DB` at a temp file.

Destructive migrations are not an option; a dead column stays in the schema.

## 3. The methodology contract

`plans/_REGISTRY` maps an id to `(MethodologyInfo, class | None)`. Each engine implements `generate(params) -> list[PlannedWorkout]`. A `None` class is a "coming soon" tile.

`MethodologyInfo` is the contract with the UI, not decoration. `fixed_schedule`, `uses_vdot_paces`, `requires_race_date`, `supported_goals`, `variants` and `fixed_days_per_week` each change real behavior in the create form, the server, and the plan service.

**Paceless plans stay paceless.** `uses_vdot_paces=False` (Foppen, Couch to 5K) means recalibration and soft-swap refuse to run — stamping E/M/T/I/R paces onto effort-cue sessions corrupts them.

Feed form defaults from the engine's own constants so the form can never drift from what `generate()` would do. See architecture decision #3.

## 4. `workout_structure` is the contract with the watch

Three buckets in `plans/garmin_sync.py`: simple (`easy`, `long`, `recovery`, `race`) needs no structure; structured (`tempo`, `intervals`) **requires** one; `rest` and `cross` are never pushed.

**Typing a row `intervals` is a promise to hand it a structure.** Breaking that promise raises nothing — the push button just never renders, and "Push week" silently skips the row. That is how taper strides went unpushable for 20 weeks.

Structure steps carry a `zone` tag (E/M/T/I/R). That tag is what lets a recalibration rewrite a mixed-pace session correctly. Dropping it degrades the session quietly.

`garmin_workout_id` and `pushed_at` *are* the push state. Editing a pushed workout deletes the Garmin copy and re-uploads.

Preserve this contract when changing plan generation, the push path, or the day/week UI.

## 5. Server-rendered HTMX, no build step

Full pages and fragments from Jinja templates. Fragments are the `_`-prefixed templates, returned to an `hx-target`. No bundler, no npm, no JSON API, no client framework. Charts are server-rendered Plotly HTML.

`web/app.py` is one ~3,700-line route module with ~100 thin routes. Splitting it is a deliberate refactor, never a side effect of adding a feature.

State the server does not know about does not exist.

## 6. Tokens for colour, `t()` for text

Status goes through `--ok` / `--warn` / `--bad` / `--info` (plus their `-solid` variants for filled chips). **Never hardcode a green, amber or red hex.** `--accent` is the brand voice and the current-item marker — never a status, because it reads as red-orange and makes a success look like an error.

Every user-facing string goes through `t()`, which is registered as a per-request Jinja global already bound to the runner's locale. English literals are the keys; a missing Dutch entry falls back to English rather than throwing.

Both failures are invisible to the test suite: a missing `t()` only shows up for Dutch readers, a hardcoded hex only in the other colour mode.

# Operational Gotchas

These are known pitfalls. Preserve the associated behavior unless a deliberate, tested change is required.

## The UI

* **No native dialogs.** `confirm()` and `alert()` are banned — unstyleable and they break the HTMX flow. Use an inline confirm strip; the pattern lives in `_plan_settings_modal.html`.
* **`hx-indicator` moves the `htmx-request` class off the triggering element** onto the indicator target, so a button silently loses its own spinner the moment you add one. And `this` is *not* resolved inside `hx-indicator` (only in `hx-target`), so `"#x, this"` applies to `#x` alone. Reference the button by class instead: `hx-indicator="#dashboard-main, .garmin-sync"`. Verified on htmx 2.0.3, which is the pinned version in `base.html`.

## Garmin

The `garminconnect` library is unofficial and some of its own constants are wrong. These values are empirically verified — do not "correct" them back:

* `conditionTypeId`: lap.button = 1, time = 2, **distance = 3** (the library's `ConditionType.DISTANCE = 1` is stale).
* Pace targets use `targetValueOne` / `targetValueTwo`, not `Low` / `High`.
* `endConditionValue` is metres for distance and seconds for time; pace targets are in m/s.
* `delete_workout(id)` also unschedules the workout from the calendar.
* `get_scheduled_workouts(year, month)` takes a **1-indexed** month but returns **0-indexed** months in the response.

Upload, in-Connect animation, and device sync are **three separate gates**:

* Only ~18 basic gym-move FIT enums animate in Garmin Connect. `warm_up/*` and most variants are FIT-valid but un-animated, and no programmatic check exists — probe and record.
* A Fenix rejects `sportType: mobility` (11) on *Send to device* even when every pose animated. Recovery sessions push as `yoga` (7) with `subSportType: "GENERIC"`. Known-good: `cardio_training` (6), `hiit` (9), `yoga` (7). Known-bad: `strength_training` (5), `mobility` (11).
* `scripts/probe_recovery_sync.py` is the reusable harness: `push` isolates a bad enum, `yoga` isolates a bad sport type, `clean` removes every probe. Always probe both gates.

## Windows and the desktop launcher

* Always invoke the venv interpreter explicitly: `.venv\Scripts\python.exe`. A bare `python` is the wrong one.
* The desktop launcher runs under `pythonw`, which has no console — it writes to `data/desktop.log` (gitignored). That file is the only trace when the window fails to appear.
* Uvicorn runs on a background thread inside the desktop process. Keep `--reload` to development runs only.

## Personal data

* The database holds real health data, diary entries and body check-ins. Never use it as a test fixture, never paste its contents into logs, commits or review output.
* `.garmin_tokens/` holds a live Garmin session. It is gitignored; keep it that way.
* `.claude/` is gitignored in its entirety — settings, permissions and local skills are per-machine and are never shared through the repo.
* The Garmin password is sent to Garmin once at sign-in and dropped. Never persist it.

# Development Workflow

## Instructions and scope

1. Read `CLAUDE.md` and `AGENTS.md` before making changes.
2. For a feature request, write the user story first — acceptance criteria before code. (The maintainer drives this with a local `implement-user-story` skill; the workflow matters, the tooling doesn't.)
3. Write user stories to `docs/user-stories/`.
4. Read the relevant feature page and the architecture decisions before changing existing behavior.
5. Keep changes focused on the requested task.
6. Preserve unrelated working-tree changes.
7. Never implement features directly on `main`.
8. Do not overwrite or discard user changes without authorization.

## Implementation

1. Understand the acceptance criteria and the existing implementation before editing files.
2. Identify the relevant code paths, the contracts involved, and the regression risks.
3. Create or use a dedicated feature branch.
4. Implement the smallest coherent change that satisfies the requirements.
5. Add or update tests for behavior changes.
6. Follow the existing technology choices and conventions. Do not add dependencies or introduce new tools without authorization.
7. Update the relevant documentation when behavior, architecture, configuration, or operational procedures change.

Do not refactor unrelated code merely because it could be improved. If a broader refactor is necessary, explain why and keep its scope explicit.

## Documentation

Every new or meaningfully reshaped feature ships with its own page in the same change — copy `docs/_template.md` to `docs/<feature>.md`, fill in purpose, user view, implementation map, configuration, known limitations and verification, then link it from the table in `docs/README.md`.

This is not a follow-up task. A feature without its page is not finished.

Update `docs/roadmap.md` when an item ships or gets re-scoped.

## Testing

Run the relevant tests before requesting code review:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

Follow the existing test architecture: plain module-level `def test_*()` functions with bare `assert`s, plus a `main()` runner at the bottom so the file also runs standalone. Do not introduce pytest fixtures, test classes, or new dependencies without authorization.

Testing requirements:

* Add regression tests for confirmed defects where practical.
* A test that asserts a training number must pin it to the methodology's published source, not to the current output. Daniels' pace table is locked down this way in `tests/test_daniels_paces.py`.
* Cover important edge cases and failure scenarios.
* Do not weaken assertions or remove tests merely to obtain a passing result.
* Never use the real database, real credentials, or real health data in a test.
* Do not claim tests passed unless they completed successfully and the results were verified.
* Report the exact command and outcome.
* Distinguish test failures from environment, dependency, permission, or sandbox restrictions.

Remember that coverage is deliberately partial. A green suite does not prove a push reached the watch or a page rendered.

## Independent code review

Get an independent review once the implementation and the relevant tests are complete — a second agent, a second model, or a human. The point is that the reviewer did not write the code. (The maintainer uses a local `/codex:review` plugin; any independent reviewer works.)

Follow the review guidelines in `AGENTS.md`. The reviewer inspects the actual Git diff and the surrounding code without modifying the implementation.

When reviewing findings:

1. Verify each finding against the implementation and a plausible execution path.
2. Distinguish confirmed defects from speculation.
3. Fix confirmed findings that fall within the task's scope.
4. Add or update regression tests where appropriate.
5. Re-run the relevant tests after making fixes.
6. Request a second review of the updated changes.
7. Verify that earlier findings are resolved and that the fixes introduced no new defects.

Do not blindly accept review findings, and do not dismiss one merely because the test suite passes.

If a finding cannot be resolved safely or falls outside the authorized scope, explain the issue and leave it explicitly outstanding.

## Completion and authorization

Before declaring a task complete:

* Confirm that the requested acceptance criteria have been addressed.
* Report the tests executed and their actual results.
* Report the code review outcome and any remaining findings.
* Identify unverified behavior, environmental restrictions, and outstanding risks.
* Mention the documentation updates.
* Be explicit if the task is only partially verified.

Do not claim a review is clean while actionable findings remain unresolved.

Do not commit, push, or merge without authorization. A passing suite and a clean review do not authorize it by themselves.

# General Principles

* Preserve the established architecture unless the task explicitly calls for changing it.
* Prefer evidence and targeted fixes over assumptions and broad refactoring.
* Treat prescribed training numbers, durable local data, and outward Garmin writes as high-risk areas.
* Prefer a loud failure to a silent one. The worst defects in this codebase have all been rows that quietly rendered no button.
* Explain significant trade-offs when a change affects an architectural decision.
* If a requirement is ambiguous and the ambiguity materially affects correctness or data integrity, ask before proceeding.
* Otherwise, make a reasonable minimal assumption and document it in the final summary.
