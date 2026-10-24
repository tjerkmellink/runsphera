# Settings page

> A single `/settings` page reached via the ⚙ icon in the top-right of the nav. Hosts the durable configuration the runner controls — Garmin connection, Claude API key, About-you note — plus four "Coming soon" stubs marking future surface area.

## Purpose

Earlier in the project, configuration was scattered: Garmin disconnect was a button in the top nav, the Claude API key only worked via `.env`. As the app grew this got cluttered fast. The Settings page consolidates everything into one place with a consistent card pattern, leaving the top nav lean (Dashboard · Plans · Diary · ⚙).

## How it works (user view)

### Top nav

A small **⚙ icon** replaces the previous Disconnect text-button. It sits right-aligned, after the "Garmin connected" status pill (visible only when authenticated).

### `/settings` page

Each concern is a card with a status pill (● Connected / Configured / Set vs ● Not connected / configured / set):

- **Garmin Connect** — account info (full name + email) and a Disconnect button when connected. When disconnected, a "Connect Garmin" CTA goes to `/auth`.
- **Claude (Anthropic)** — paste an API key to enable the LLM coach voice. Saved keys are masked (`sk-ant-api0…XXXX`). Clear key button. If a key is set via `.env`, shown as "Source: provided via .env" and not overwritten.
- **About you** — durable free-text note the LLM coach treats as ground truth. 1000-char cap. Empty save + leave empty = clear.
- **Fitness baseline** (`#fitness`, added 2026-07-18) — the manual seed for plan generation when there's no Garmin data: a recent race result (distance + h/m/s → VDOT via Daniels' formula, stored as `manual_vdot` + a human note like "10 km in 52:30") and self-reported weekly km (`manual_weekly_km`). The card header says which source currently wins (Garmin-measured outranks manual — see the seed-precedence ladder in [onboarding.md](onboarding.md)). `POST /settings/fitness`; the wizard's Fitness step writes the same fields.
- **Coming soon** (greyed out, no form): Units · Language · Country · Data & storage.

Saving a card flashes a green confirmation banner at the top.

## How it works (implementation)

### Modules

- [running_coach/settings.py](../running_coach/settings.py) — all read/write helpers for the `app_settings` single-row table:
  - Garmin: `get_garmin_email`, `set_garmin_email`, `get_garmin_full_name`, `set_garmin_full_name`, `garmin_first_name`.
  - Claude: `get_anthropic_key`, `set_anthropic_key`, `clear_anthropic_key`, `mask_anthropic_key`.
  - About-you: `get_about_you`, `set_about_you`. Cap: `ABOUT_YOU_MAX_CHARS = 1000`.

### Templates

- [settings.html](../running_coach/web/templates/settings.html) — the page. Inline CSS for the card grid and pill styling.
- [base.html](../running_coach/web/templates/base.html) — the ⚙ icon in the top nav.

### Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/settings` | Render the page. Reads all settings, masks the Claude key. |
| `POST` | `/settings/claude` | Save a Claude API key. Also writes to `os.environ` at runtime so the connector sees it immediately. |
| `POST` | `/settings/claude/delete` | Clear the stored key. Re-reads `.env` to check whether to also drop the runtime env var (preserves env-provided keys). |
| `POST` | `/settings/about` | Save / clear the About-you note. Invalidates today's `llm_cache`. |
| `POST` | `/auth/logout` | Disconnect Garmin. Redirects to `/settings` (not `/auth`) so the user lands on their full state. |

### DB

```
app_settings
─ id                 INTEGER  PRIMARY KEY CHECK (id = 1)   -- single row enforced
─ garmin_email       TEXT
─ garmin_full_name   TEXT
─ anthropic_api_key  TEXT     -- masked on display, never logged
─ about_you          TEXT     -- ≤ 1000 chars
─ updated_at         TEXT
```

A row is seeded with `INSERT OR IGNORE INTO app_settings (id) VALUES (1)` on schema init. Updates target `WHERE id = 1`.

### Startup hook

On FastAPI startup, [app.py](../running_coach/web/app.py) reads the saved Claude key from the DB and writes it to `os.environ["ANTHROPIC_API_KEY"]` if no env var is already set. This means a DB-stored key survives restarts without needing `.env`.

## Configuration

Settings *is* the configuration surface. The only escape hatches that don't live here:

| Env var | Purpose |
|---|---|
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | Bypass the web sign-in flow for headless CLI ingests. Only consulted when the token cache is empty. |
| `GARMIN_TOKEN_DIR` | Where the Garmin session token is cached. Default `./.garmin_tokens`. |
| `ANTHROPIC_API_KEY` | Alternative to the Settings card. A key saved via Settings overrides this. |
| `RUNNING_COACH_DB` | Override the SQLite path. Default `./data/running_coach.db`. |

## Known limitations

- **Single-user.** The `id = 1` CHECK on `app_settings` enforces this at the schema level. A future multi-user version needs a per-user settings table.
- **Plaintext API key in SQLite.** Acceptable for a local-first single-user app — the threat model is "someone has filesystem access to the DB", at which point they have everything anyway. If this ever ships beyond local-first, encrypt at rest.
- **No "test connection" button.** Saving a malformed Claude key doesn't fail at save time; you find out when the next dashboard load silently falls back to the rules-engine headline. Could ping `/v1/models` on save to give an immediate green/red.
- **Disconnect redirects to `/settings`, not back to where you came from.** Intentional (the user lands on their full state) but worth knowing.
- **Four stub cards do nothing.** Visible deliberately to mark the roadmap — Units, Language, Country, Data & storage. Removing the stub when wiring each.

## Verification

1. **⚙ icon present and active state works.** Visit `/settings` directly — the ⚙ in the nav should have the active highlight.
2. **Garmin card.** With a Garmin session: name + email rendered, "● Connected" pill, Disconnect button visible. Click Disconnect, confirm, you should land back on `/settings` with "● Not connected".
3. **Claude card round-trip.** Paste a key, save. Banner says "Claude API key saved." The card now shows masked key + Clear button. Refresh `/` — the coach banner should regenerate with Claude voicing.
4. **About-you flush.** Save "I'm a morning runner, no time for doubles." Banner says it was saved. Click ↻ on the dashboard coach banner — Claude should pick up the context within a regeneration.
5. **Env-provided key.** Stop the server, set `ANTHROPIC_API_KEY=sk-...` in `.env`, restart, visit `/settings`. Claude card shows "Source: provided via .env" instead of the masked key. Save a different key — the env one is overridden. Clear from Settings — env value resumes.

## Future improvements

Lighting up the stubs, in roughly increasing scope:

- **Units (km / mi).** A radio toggle that flips a global render helper. The DB stays SI internally; only the formatting layer changes.
- **Language.** Requires real i18n — not just translating strings, also threading locale into the LLM prompt so the coach speaks the runner's language.
- **Country.** Drives weather lookup + race calendar (both parked features). Free-form text or a curated list; mark "EU" / "NL" / "US" enough for v1.
- **Data & storage.** Show the DB path, size, last-modified. Add a "Download backup" button (just `sendfile` the SQLite). A "Reset all data" button is more invasive and needs strong confirmations — see [feedback_no_data_wipes.md](https://github.com/) in the memory store for the rationale.

Other ideas:

- **Test-connection button on the Claude card.** Pings `/v1/models` and shows green ✓ / red error inline.
- **Per-runner profile fields.** Birth year, max HR, lactate threshold — currently inferred from Garmin where possible, but explicit fields would let the LLM coach reference them when Garmin's are off.

---

*Last updated: 2026-07-18*
