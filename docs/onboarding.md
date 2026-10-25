# Getting-started wizard

> A guided, skippable first-run setup that walks a brand-new runner from an empty app to a connected, synced, plan-ready dashboard.

## Purpose

Before this existed, a first-time user landed on a hard Garmin-auth redirect, then a passive "welcome card" on the dashboard with two loose buttons. Nothing tied the real setup path together (connect → sync → plan), and the steps were scattered across `/auth`, the dashboard, and `/plans/new`.

The wizard replaces that with a single guided flow, so the app is presentable when shared with people who didn't build it. Every step is **skippable** and the flow is **resumable and non-nagging** — a runner is never trapped, and once they finish (or explicitly defer) they're never pestered again.

## How it works (user view)

On first run the dashboard renders (even before Garmin is connected) with the **Getting-started** pop-over (`#onboarding-modal`) auto-opened on top. Six steps, shown as progress dots ("Step N / 6"):

1. **Welcome** — one-line intro + what's ahead.
2. **Connect Garmin** — email/password → MFA code, inline (folded in from `/auth`). Only a session token is stored, never the password. The third action, **I don't use Garmin →**, records the choice (`garmin_optout`) and jumps straight to the Fitness step — the whole app then works Garmin-less (the dashboard stops redirecting signed-out visits to `/auth`).
3. **Sync** — one click pulls recent activities + daily metrics; shows "Pulled N runs · VO₂max ~X".
4. **Fitness baseline** — the Garmin-less seed. When Garmin already measured a VO₂max this is a one-line confirmation; otherwise a short all-optional form: first name (for the greeting), a recent race result (distance + time → VDOT via `estimate_vdot_from_race`), self-reported weekly km, and the self-assessment "Can you currently run 10 minutes non-stop?" (Yes / Not yet — feeds the plan recommendation, see [plan-recommendation.md](plan-recommendation.md)). Saving advances; the derived VDOT pays off on the finale's stat cards.
5. **Optional extras** — add an Anthropic API key for the coach voice and/or a home location for weather. Both detect existing values and show a "set ✓" badge. Fully skippable.
6. **Your goal (finale)** — deliberately *not* a form. Building a plan is a flagship feature, so this step is a short motivational hand-off ("You're almost there, {name}! Let's find the training plan that fits your goal…") with the runner's baseline (VO₂max/VDOT · km-per-week) shown as stat cards — **honestly labeled**: "We've read your training" (Garmin), "Based on what you told us (10 km in 52:30)" (manual), or, when neither exists, a plain note that plans will start from a cautious default plus a "← Set my fitness" shortcut. The primary **Find my plan →** completes onboarding and redirects to the full `/plans/new` builder; **Not now** completes and closes without leaving the dashboard.

The goal step is last on purpose — the flow ends on the exciting "let's build your plan" note and sends the runner into the real builder rather than a cramped popup form.

Navigation on every step:
- **Skip →** advances without doing that step's action.
- **← Back** returns to the previous step.
- **I'll finish later** dismisses the whole wizard (stops it auto-opening).
- The × / backdrop / ESC just close it ("not now" — it reopens next dashboard visit while still pending).

**First-run only.** The wizard auto-opens on the dashboard while onboarding is unfinished (`pending`); closing it with ×/backdrop/ESC leaves it `pending` so it reappears next dashboard visit, while "I'll finish later" dismisses it for good. There is deliberately **no reopen entry point** — everything the wizard does (connect Garmin, sync, coach voice, home location, build a plan) is reachable directly through the normal UI (Settings cards, the dashboard Sync button, `/plans/new`), so a guided replay would only duplicate them.

## How it works (implementation)

- **Modules**:
  - `runsphera/web/app.py` — `ONBOARDING_STEPS` (the ordered step keys), `_render_onboarding()` (renders a step partial + persists the resume point + bundles progress metadata), `_onboarding_step_data()` (per-step context), `_onboarding_sync_summary()`, the `/onboarding/*` routes, and the `onboarding=1` branches in `/auth/login` + `/auth/mfa`. `_run_sync()` is the extracted Garmin-pull core shared by `/ingest` and `/onboarding/sync`.
  - `runsphera/settings.py` — `get_onboarding()`, `set_onboarding_step()`, `set_onboarding_status()` (+ `ALLOWED_ONBOARDING_STATUS`).
  - `runsphera/db.py` — schema + migration for the two new columns.
- **Templates**:
  - `web/templates/_onboarding.html` — the whole wizard, one partial with a branch per step (macros for the Back / Skip / "finish later" buttons).
  - `web/templates/base.html` — the `#onboarding-modal` dialog shell, the auto-open script (`show_onboarding`, dashboard only), and all `.onb-*` styling.
  - `web/templates/index.html` — the old `.welcome-card` block was removed (superseded by the wizard).
- **Routes**:
  - `GET /onboarding?step=<key>` — render/resume a step (persists it as the resume point).
  - `POST /onboarding/sync` — run the Garmin pull, re-render the Sync step done-state.
  - `POST /onboarding/skip-garmin` — set `garmin_optout=1`, jump to the Fitness step.
  - `POST /onboarding/fitness` — save name / race-result-derived VDOT / weekly km, advance to Extras (re-renders with an error inline when a value is implausible).
  - `POST /onboarding/coach-key`, `POST /onboarding/location` — optional saves, re-render Extras.
  - `POST /onboarding/goto-plans` — finale hand-off: mark `completed`, return `HX-Redirect: /plans/new`.
  - `POST /onboarding/dismiss` (→ `dismissed`), `POST /onboarding/complete` (→ `completed`, fires `dashboardRefresh`).
  - `POST /auth/login` + `POST /auth/mfa` — return wizard step partials when `onboarding=1` (else unchanged); a successful login clears `garmin_optout`.
- **DB**: columns on `app_settings` (single-row, id=1):
  - `onboarding_status` — `pending` | `dismissed` | `completed`.
  - `onboarding_step` — the resume-point step key.
  - `manual_vdot` / `manual_vdot_note` / `manual_weekly_km` — the manual fitness baseline (see below).
  - `garmin_optout` — 1 when the runner chose the Garmin-less mode.
- **Seed precedence** (`plans/service.get_plan_seed`): Garmin-measured (`training_status.vo2max_precise`, 4-week activity average) → manual baseline → defaults (VDOT 45, 25 km/wk). Each value carries a `*_source` tag (`garmin` / `manual` / `default`) that the wizard finale, the `/plans/new` subhead, and the Settings "Fitness baseline" card use to label the numbers honestly. The LLM coach context uses the same fallback for VDOT.
- **Garmin-less dashboard access**: `index()` redirects signed-out visits to `/auth` only when onboarding is past `pending` **and** `garmin_optout` is 0 — a runner who chose "I don't use Garmin" keeps the dashboard.
- **Garmin affordances are auth-gated in templates** via the `is_authenticated()` template global: the header "Sync from Garmin" button + its "no data yet" helper line (index.html), the per-day "Send to watch" / per-week "Push this week →" buttons (`_day_card.html`, `_week_card.html`), the workout modal's "Send to Garmin" section, the strength modal's "Push to watch", and the acute-load/recent-runs empty states (which get watch-free copy instead of a dead "sync" CTA). A runner without a connected watch never sees a sync or push control.
- **External services**: Garmin (connect + sync), Anthropic (optional coach key), Open-Meteo geocoding (optional home location) — all via existing services.

**Data flow**: `index()` reads `get_onboarding()`; if `status == 'pending'` it sets `show_onboarding`, and base.html's script `htmx.ajax('GET', '/onboarding')` fills the dialog body and `showModal()`s it. Each step is an HTMX partial swapped into `#onboarding-body`; server-side each render persists the current step so a reload/reopen resumes correctly. Garmin login/MFA post to `/auth/*` with a hidden `onboarding=1` and get step partials back instead of a redirect.

**First-run detection (the key trick)**: the `pending` vs `completed` default is set so that **fresh installs auto-open, upgrades never do**. The base `SCHEMA` `app_settings` defines `onboarding_status DEFAULT 'pending'` (used when a brand-new DB is created), while the idempotent `ALTER TABLE ... ADD COLUMN` migration uses `DEFAULT 'completed'` (applied to existing DBs on upgrade). No data-fix UPDATE is needed, and a new user connecting Garmin mid-flow is never prematurely marked done.

## Configuration

- Nothing to configure to use it — state lives entirely in `app_settings` (id=1).
- Env var `GARMIN_TOKEN_DIR` still governs where the Garmin session token lands (used in testing to simulate an unconnected user).
- To re-run onboarding manually (e.g. for a demo): `UPDATE app_settings SET onboarding_status='pending', onboarding_step='welcome' WHERE id=1;`

## Known limitations

- **Single-user / self-hosted only.** Like the rest of the app (`app_settings` id=1, one Garmin token slot), the wizard assumes one runner per install. Multi-tenant hosting would need accounts + per-user isolation first — out of scope by design.
- **Translated for `en` + `nl` only.** All wizard strings have `nl` entries in [i18n.py](../runsphera/i18n.py); any further locale falls back to the English source (see [language.md](language.md)). Note the back button uses the distinct key `"← Back"` so it doesn't collide with the body diagram's `"Back"` ("Achter").
- **No metric/imperial choice.** The app is metric (km) end-to-end; a units toggle was deliberately deferred (it's a whole feature, not a wizard field). See the roadmap.
- **The wizard never creates a plan itself** — by design. Plan generation is a flagship feature and lives on `/plans/new`; the finale hands off there. Reaching the finale marks onboarding complete whether or not the runner actually builds a plan, so a runner who bails on `/plans/new` won't be re-nagged (the Plans page has its own create affordances).
- Closing via ×/backdrop/ESC is "not now" (reopens while pending), distinct from "I'll finish later" (dismisses). This is deliberate but subtle.

## Verification

Manual smoke test (against a **copy** of the DB — never the live one):

1. Point `RUNSPHERA_DB` at a copy and reset: `UPDATE app_settings SET onboarding_status='pending', onboarding_step='welcome';`
2. Load `/` — the wizard auto-opens on Step 1.
3. Click through **Skip →** / **Continue →** to Step 6 (the goal finale) — no console errors, dots advance.
4. The finale shows "You're almost there!" with baseline stat cards. Click **Find my plan →** — the dialog hands off to `/plans/new`, and `onboarding_status` is now `completed`.
5. Reload `/` — the wizard no longer auto-opens. (**Not now** on the finale also completes, without the redirect.)
6. Fresh-install check: delete the copy, reconnect — `get_onboarding()` returns `pending`. Upgrade check: an existing DB migrates to `completed`.
7. Garmin-less path: on the Garmin step click **I don't use Garmin →**, fill the Fitness step (e.g. 10 km in 52:30 + 22 km/wk), finish via **Find my plan →**, build a plan without a race date — then reload `/`: the dashboard renders (no `/auth` bounce), greets by the entered name, and `/settings#fitness` shows the saved baseline. Automated coverage: `tests/test_garmin_less_onboarding.py`.

To exercise the unconnected path, point `GARMIN_TOKEN_DIR` at an empty dir so `is_authenticated()` is false — `/` still renders (with the wizard) while `pending`, and the Garmin step shows the login form.

## Future improvements

- Fold a units (metric/imperial) choice in once imperial display support exists app-wide.
- Optional inline "About you" note (currently Settings-only) as a personalization step.
- A subtle inline progress nudge on the dashboard when onboarding is `dismissed` but incomplete (without nagging).

---

*Last updated: 2026-07-18*
