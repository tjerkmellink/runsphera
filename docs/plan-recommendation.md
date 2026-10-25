# Plan recommendation

> Rules-first enrollment guidance: a "Recommended for you" badge on `/plans/new`, a pre-selected Higdon tier, and one self-assessment question — computed from the fitness baseline. Guidance only, never gating.

## Purpose

Before this feature, methodology and experience tier were pure self-select with zero guidance: a brand-new runner with a default VDOT of 45 could pick Advanced 2, and nothing connected the fitness baseline to the choice. Now the app reads what it already knows (weekly km, VDOT, and where those numbers came from) plus one question — *"Can you currently run 10 minutes non-stop?"* — and points at the right starting plan. The user can override everything.

## How it works (user view)

- **/plans/new**: one methodology tile carries an accent **★ Recommended for you** ribbon plus a one-line reason ("A gentle run/walk build to your first 5K."). The recommended methodology (and, for beginners, the 5K goal) is pre-checked; clicking the Higdon tile pre-selects the recommended tier.
- **Blank-slate users** (no Garmin data, no manual baseline, question never answered) instead see a small strip above the gallery: *"Quick question so we can point you at the right plan: can you currently run 10 minutes non-stop?"* with **Yes** / **Not yet** buttons. Answering re-renders with the badge in place.
- **Onboarding**: the manual fitness step asks the same question (optional radio, blank stays unanswered). Garmin users never see it — measured data implies the answer.
- **Settings → Fitness baseline**: the answer can be set or changed later.

## The rule table

First match wins. `km` = weekly baseline, "known" = source is garmin/manual (not the default guess). A Garmin-sourced seed implies `can_run_10min = yes`.

| # | Condition | Methodology | Higdon tier | Goal |
|---|-----------|-------------|-------------|------|
| 0 | answer unknown AND km & VDOT unknown | none → question strip | — | — |
| 1 | answered "not yet" (beats everything) | `c25k` | novice_1 | 5k |
| 2 | km known < 8 and not answered "yes" | `c25k` | novice_1 | 5k |
| 3 | runs, but km unknown | `higdon` | novice_1 | — |
| 4 | km < 15 | `higdon` | novice_1 | — |
| 5 | 15 ≤ km < 25 | `higdon` | novice_2 | — |
| 6 | 25 ≤ km < 40 | `daniels` if VDOT known, else `higdon` | intermediate_1 | — |
| 7 | km ≥ 40 | `daniels` if VDOT known, else `higdon` | intermediate_2 / advanced_1 (VDOT ≥ 55) / advanced_2 (≥ 70) | — |

The Higdon tier is computed even when the badge lands elsewhere, so the tier pre-check fires whenever the user clicks the Higdon tile. If `c25k` is unavailable the beginner rules fall back to Higdon Novice 1 (and drop the 5K goal push); an unavailable methodology is never badged.

## How it works (implementation)

- **Modules**: `runsphera/plans/recommend.py` (pure `recommend_plan(seed, can_run_10min, available) → Recommendation` — no DB access), `runsphera/settings.py` (`get/set_can_run_10min`, tri-state), `runsphera/db.py` (migration: `app_settings.can_run_10min INTEGER`, NULL = never asked).
- **Templates**: `plans_new.html` (strip + ribbon + reason + pre-checks for goal/methodology/variant, all server-rendered — the existing `applyLock()` JS needs no changes), `_onboarding.html` (fitness-step radio), `settings.html` (fitness card radio).
- **Routes**: `GET /plans/new` and the error re-render compute `rec`; new `POST /plans/new/self-assessment` persists the strip's answer (plain 303 redirect — the strip only shows on a blank-slate form, so nothing is lost); `POST /onboarding/fitness` and `POST /settings/fitness` accept the optional radio.
- **Seed**: `plan_service.get_plan_seed()` output is passed verbatim — the `*_source` fields ("garmin"/"manual"/"default") are what make "known" honest.

Degradation matrix: Garmin or manual-baseline users → badge, never the question. Blank-slate users → strip, no badge until answered. Empty recommendation → exactly the old behaviour (first available tile pre-checked, first variant pre-checked).

## Configuration

The answer is editable in Settings → Fitness baseline. Everything else is code (thresholds in `recommend.py`).

## Known limitations

- The gallery is goal-filtered: flipping the goal to a distance the recommended methodology doesn't offer hides its tile (ribbon and all) and moves the selection to the first fitting tile. Flipping back restores it. The recommendation itself is only recomputed on page load.
- Thresholds (8 / 15 / 25 / 40 km, VDOT 55 / 70) are heuristics, not physiology — tune with feedback.
- One-user app: the answer is a single global setting, not per-plan.

## Verification

1. `.venv/Scripts/python.exe tests/test_plan_recommendation.py` — one test per rule + boundaries.
2. Fresh DB → `/plans/new` shows the question strip; answer **Not yet** → Couch to 5K ribbon, 5K goal pre-checked.
3. Set a baseline in Settings (e.g. 30 km/wk + a race result) → Daniels ribbon, no strip; Higdon tile pre-selects Intermediate 1.

## Future improvements

- Re-ask stale answers (a "not yet" from a year ago shouldn't outlive graduation — flip it after a completed C25K plan).
- Recommend a goal distance for experienced runners too (e.g. race history → "your next PR distance").

---

*Last updated: 2026-07-18*
