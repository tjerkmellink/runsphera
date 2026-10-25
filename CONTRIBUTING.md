# Contributing to RunSphera

Thanks for looking. RunSphera is a local-first running coach maintained by one
person, so the most useful thing to know up front is what this project is and
isn't — it will save you building something that can't be merged.

## Before you write code

**Open an issue first** for anything beyond a typo or an obvious bug fix. A
short description of what you want to change and why is enough. This is a
single-maintainer project; an issue costs you five minutes and can save you a
weekend.

**Read [docs/architecture.md](docs/architecture.md).** It records the decisions
every other component depends on. Several of them look like style choices and
are not — breaking one tends to be invisible until a session reaches the watch
wrong.

Two in particular catch people out:

- **Rules decide; the LLM only speaks.** Every training verdict is
  deterministic Python. The model phrases a decision that has already been
  made, and never chooses training load. Moving a judgement into a prompt is a
  regression even when the output reads better. The app must stay fully
  functional with no API key and no network.
- **`workout_structure` is the contract with the watch.** Typing a row
  `intervals` is a promise to hand it a structure. Break that promise and
  nothing raises — the push button simply never renders. That is how taper
  strides stayed unpushable for 20 weeks.

## Getting set up

Python 3.12+. Garmin is optional — the plan engine, fuel engine and diary all
work without it, and the test suite never touches the network.

```powershell
git clone https://github.com/tjerkmellink/runsphera.git
cd runsphera
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

macOS and Linux work the same way with `.venv/bin/python`. The one-click
`install.cmd` is Windows-only; a cross-platform bootstrap script is on the
roadmap.

Run it:

```powershell
.venv\Scripts\python.exe -m runsphera.web          # http://localhost:8000
.venv\Scripts\uvicorn.exe runsphera.web.app:app --reload --port 8000
```

Point `RUNNING_COACH_DB` at a scratch file while developing so you never write
to a real training history.

## Running the tests

```powershell
.venv\Scripts\python.exe -m pytest tests -q
```

383 tests, about 6 seconds, no network and no Garmin. Every test module also
has a `main()` runner, so a single file works without pytest at all:

```powershell
.venv\Scripts\python.exe tests\test_daniels_paces.py
```

**Coverage is deliberately partial.** The suite covers the plan engines,
scoring, matching and nutrition. It does *not* cover the Garmin network path,
the LLM providers, the desktop launcher, or template rendering. A green suite
does not prove a push reached the watch or a page rendered — if your change
touches those, exercise it by hand and say so in the PR.

### Test conventions

Plain module-level `def test_*()` functions with bare `assert`s, plus a
`main()` at the bottom. No fixtures, no test classes, no new dependencies.

**A test that asserts a training number must pin it to the methodology's
published source, not to the current output.** `tests/test_daniels_paces.py`
locks the VDOT table to Daniels' Running Formula (4th ed., Table 5.2) for
exactly this reason. A test updated in the same commit to match new output is
not evidence of correctness — it only pins the code to itself.

## Submitting a pull request

1. **Fork the repository** and branch from `main`. Use a descriptive branch
   name (`fix/interval-volume`, `docs/install-linux`).
2. **Keep the change focused.** One concern per PR. Unrelated refactors make a
   change much harder to review and much slower to merge.
3. **Add or update tests** for any behaviour change, and a regression test for
   any bug fix where one is practical.
4. **Run the full suite** and include the command and its result in the PR.
5. **Update the docs in the same change.** A new or meaningfully reshaped
   feature ships with its own page — copy [docs/_template.md](docs/_template.md)
   to `docs/<feature>.md` and link it from [docs/README.md](docs/README.md).
   This is not a follow-up task.
6. **Open the PR against `main`** and describe what changed, why, and how you
   verified it. Say plainly what you did *not* verify.

Reviews follow [AGENTS.md](AGENTS.md), which is the standard this project
applies to every change regardless of who or what wrote it. It is worth
reading before you submit — particularly the ordering of risk, which puts
prescribed training numbers above everything else.

### What gets a change merged quickly

- A regression test that fails before the fix and passes after
- Honest reporting of what is unverified
- Documentation updated alongside the behaviour
- No new runtime dependencies

### What will slow it down

- New dependencies. Open an issue first; the answer is usually no.
- Build tooling. There is no bundler, no npm, no client framework, and that is
  deliberate — see architecture decision #5.
- Moving a training judgement into an LLM prompt.
- Large refactors bundled with a fix.
- Schema changes that are not additive. `CREATE TABLE IF NOT EXISTS` is
  silently ignored for a table that already exists, so a new column goes in
  `SCHEMA` *and* as an `ALTER` in `_MIGRATIONS`. Destructive migrations are not
  an option — a dead column stays in the schema.

## Reporting a bug

Include what you expected, what happened, and enough detail to reproduce it:
the methodology, goal, and week if it is a plan issue; the workout type and
whether it had a structure if it is a push issue. Screenshots help.

**Never paste database contents, Garmin tokens, or health data into an issue.**
If a log is relevant, redact it first.

The highest-value bug reports are the ones automated review cannot find:
something that behaves wrong in the actual running app. A recent example — a
long run moved from Sunday to Monday vanished from the plan page, because the
row kept its old week number. Five rounds of adversarial code review missed it;
one person moving a workout and looking at the page found it immediately.

## Scope

RunSphera is deliberately a **single-runner, self-hosted** application.

**Multi-tenant SaaS is not on the roadmap.** It would require Garmin Health API
partnership approval, and holding other people's Garmin credentials is a
security and terms-of-service non-starter. Changes that assume accounts,
tenancy, or a hosted backend will not be merged.

Support for other data sources — Samsung, Apple, Polar, Suunto — is a genuine
future direction, and the ingest layer is where that seam belongs.

## Licence and brand

Code is MIT (see [LICENSE](LICENSE)). By contributing you agree your work is
licensed the same way.

The RunSphera **name, wordmark and icon are not covered by the MIT grant** and
are not included in this repository. Fork the code freely; ship it under your
own name.
