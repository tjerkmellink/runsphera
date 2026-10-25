# Language

> UI + LLM coach language selector — English (default) or Dutch. Stored as a single column on `app_settings`; everything reads through one helper.

## Purpose

The runner reads the dashboard, picks training plans, and consumes the coach's commentary several times a day. Putting that voice in their native language matters more than the UI labels — but once you flip the coach to Dutch, English UI chrome around it feels half-finished. So the language picker switches both surfaces in one move: the visible chrome via a dictionary lookup in templates, and the coach via a system-prompt prefix sent to Claude.

## How it works (user view)

### Settings → Language

A small section on the [/settings](../runsphera/web/templates/settings.html) page lists the available languages as a radio-style pill row. Picking one POSTs to `/settings/language` and the page reloads with the new locale active. The banner at the top of Settings confirms the choice ("● Language saved. Nederlands.").

### What changes

- **UI chrome**: navigation labels, headlines, section eyebrows, button text, card titles, modal labels, table headers, error/flash messages.
- **Coach voice**: the daily coach banner, the weekly recap, and the run-reaction byline regenerate in the chosen language on next render. All three are produced by Claude using a per-locale `## Taal` / `## Language` instruction prepended to the system prompt.

### What doesn't change

- **Pace, HR, distance, dates**: numbers are universal. Pace zone abbreviations (E / M / T / I / R) stay in English — they're terms of art in Daniels' running-coaching vocabulary that Dutch runners use too.
- **Activity names** stored from Garmin (e.g. "Bridge Tempo 8K") — those came from the watch and don't get re-translated.
- **Existing diary text** — entries the runner wrote stay in whatever language they wrote them.

## How it works (implementation)

### Modules

- [runsphera/i18n.py](../runsphera/i18n.py) — the i18n core. Exports `t(source, locale, **kwargs)`, `plural(n, singular, many, locale)`, `language_name(code)`, plus `LANGUAGES` (the supported set) and `_NL` (the Dutch translation table).
- [runsphera/settings.py](../runsphera/settings.py) — `get_language(conn)`, `set_language(conn, lang)`, `ALLOWED_LANGUAGES`.
- [runsphera/llm/prompts.py](../runsphera/llm/prompts.py) — `system_prompt_for(base_prompt, locale)` prepends the per-locale language instruction.
- [runsphera/llm/commentary.py](../runsphera/llm/commentary.py) — `invalidate_all_coach(conn)` drops every cached LLM message; called from the language-switch route so the next page render produces output in the new locale instead of serving stale text.

### Templates

- [runsphera/web/templates/settings.html](../runsphera/web/templates/settings.html) — picker UI (section ④).
- [runsphera/web/templates/settings.html](../runsphera/web/templates/settings.html) — base-theme picker.
- Every template uses `{{ t("English source string") }}` to wrap visible literals. The `t()` function is registered as a Jinja global in [runsphera/web/app.py](../runsphera/web/app.py) bound to the current request's locale.

### Routes

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/settings/language` | Persist the choice, invalidate every cached LLM message, redirect back to `/settings?saved=language`. |

### DB

One new column:

```sql
ALTER TABLE app_settings ADD COLUMN language TEXT NOT NULL DEFAULT 'en';
```

### Translation dictionary shape

English string literals double as the lookup keys. `_NL` in `i18n.py` maps each English source to its Dutch target:

```python
_NL = {
    "Sync from Garmin": "Synchroniseren met Garmin",
    "{n} days/week, long run on {day}s.": "{n} dagen/week, lange run op {day}.",
    ...
}
```

`{name}` placeholders survive translation because `.format()` runs *after* the dict lookup. So `t("{n} days to race", n=7)` renders the same way in either language as long as the target has matching placeholder names.

### Fallback behavior

`t("Unported string", "nl")` returns `"Unported string"` — the English source. So shipping a new UI surface without translating it yet just leaves that surface in English instead of crashing the page. This is intentional: it lets us land features without making translation a release-blocker.

### Coach language injection

`system_prompt_for("...persona...", "nl")` prepends a small Dutch instruction:

```
## Taal
Antwoord uitsluitend in het Nederlands. ... Houd de warme, directe, observerende toon — alleen de taal verandert. ...
```

This is layered on top of the existing English persona prompt rather than translating the persona itself — keeps prompt caching effective across locale changes, since the cached suffix is shared.

### Cache invalidation

Switching languages calls [`commentary.invalidate_all_coach(conn)`](../runsphera/llm/commentary.py) which clears the entire `llm_cache` table. The next render of each surface (daily banner, weekly recap, every run reaction) re-queries Claude with the new locale.

## Configuration

| What | Where | Notes |
|---|---|---|
| Active language | `app_settings.language` (DB) | `'en'` or `'nl'`. |
| Default for new installs | `db.py` ALTER statement (`DEFAULT 'en'`) | English unless the runner picks otherwise. |
| Available languages | `runsphera/i18n.py` → `LANGUAGES` | Add a code + display name + a new translation dict to extend. |

## Adding a new language

1. Pick an ISO 639-1 code (e.g. `de`).
2. In [`i18n.py`](../runsphera/i18n.py): add `"de": "Deutsch"` to `LANGUAGES`, copy `_NL` to `_DE`, translate values, register `"de": _DE` in `_TRANSLATIONS`.
3. In [`prompts.py`](../runsphera/llm/prompts.py): add a `_LANGUAGE_INSTRUCTION["de"]` entry telling Claude to reply in German.
4. In [`settings.py`](../runsphera/settings.py): add `"de"` to `ALLOWED_LANGUAGES`.

That's it — the picker UI iterates `LANGUAGES.items()` so no template changes needed.

## Known limitations

- **Partial coverage at launch.** Fully ported: the Tempo dashboard, run-detail modal, base nav, Settings picker, the getting-started wizard, and the entire **Plans** surface — the new-plan builder (`/plans/new`, including methodology-card copy from `plans/__init__.py`), the plans list + plan-detail pages (hero, stat strip, phase-bar legend, archive), the week cards, and every day-triggered modal (plan-workout editor, plan-settings incl. the schedule/reshape form, recalibrate-paces preview, and the strength-session detail). Still English: calendar, diary, weather modal, daily-tip card, and a few partials — they fall through to the dict and render in English when `language = nl`. Backfill is incremental: pick a template, replace literals with `{{ t("...") }}`, add the Dutch entries to `_NL`.
  - **Not translated on Plans (by design):** generated workout titles/descriptions (methodology output, like activity names), Daniels' E/M/T/I/R zone letters, methodology proper names, and units (km, bpm, VDOT, VO₂max).
- **English is the source-of-truth language.** All translation keys are English strings. Renaming an English label requires updating its lookup key everywhere. Acceptable for a 2-language app; if we add more, dotted-key namespacing might be worth revisiting.
- **No client-side switching.** Changing the language requires a full page reload (the picker is a POST → 303 redirect). No live re-render.
- **No fallback chain.** `t("X", "de")` falls straight to the English source if the German dict doesn't have `X`. There's no intermediate fallback like Dutch → German → English.
- **Pluralization is simple.** `plural(n, singular_template, many_template)` handles the common 1/many case for both EN and NL. Languages with more plural forms (Russian, Polish) would need a richer rule — not in scope.

## Verification

1. **Picker renders.** Open `/settings`, scroll to the Language section. Two pills visible: English (active), Nederlands.
2. **Switch to Dutch.** Click Nederlands. Page reloads, banner reads "● Language saved. Nederlands." The nav bar now reads `Dashboard · Plannen · Kalender · Dagboek · Instellingen`.
3. **Dashboard reflects locale.** Open `/`. Section eyebrows say `① VANDAAG`, `③ DE CIJFERS`, `④ RECENT`. Stat-wall labels show `Trainingsstatus`, `Gereedheid`. The "Sync from Garmin" button reads "Synchroniseren met Garmin".
4. **Run-detail modal in Dutch.** Click a recent run. Tabs say `Training · Inspanning · Notities`. The active-block callout reads `Actief blok · vs voorschrift` and the chart legend shows `WARMING-UP · ACTIEF · COOLING-DOWN`.
5. **Coach voice flips.** With a Claude key configured, click ↻ Regenerate on the daily coach banner. The new message comes back in Dutch. Same for the weekly recap and any run reaction.
6. **New-plan builder in Dutch.** Open `/plans/new`. The goal tiles read `Fit blijven · 10 km-wedstrijd · … · Marathon`, the section headings say `Doel · Methodologie · Schema · Extra's`, the methodology cards (tagline, description, "Geschikt voor:") are Dutch, and the training-day picker hint reads "Kies nog N dagen." Proper nouns (methodology names, Daniels' E/M/T/I/R zone names, Higdon plan tiers) stay in English by design.
7. **Unported strings fall back gracefully.** Open the plans list page (not yet fully translated). The page renders in English without crashing — strings without Dutch entries fall through to the source.
8. **Reset.** Switch back to English in Settings, refresh — everything (including coach output, after a regenerate) returns to English.

## Future improvements

- **Finish the port.** Calendar, diary, weather modal, daily-tip card, error flash messages, base-theme templates, and any new strings added since this doc. (Dashboard and the whole Plans surface are done.)
- **Dotted-key namespacing** if we ever exceed 3 languages — `t("plans.empty.headline")` is harder to refactor accidentally than `t("No active plan.")`.
- **Per-template extraction script** — a small CLI that walks the templates and reports any `>literal text<` not wrapped in `{{ t(...) }}`. Useful as a translation-coverage gate.
- **Locale-aware formatters** — date formats (`1 mei 2026` vs `1 May 2026`), thousand separators, decimal separators. Currently we use the same `fmt_date_long` for both; Dutch readers will tolerate "27 May 2026" but locale-correct would be nicer.
- **Force language override per response** — useful for testing without persisting (`?lang=nl` query param).
- **In-app translation editing** — a settings-only tool to edit specific source-target pairs without an i18n.py reload. Only worth building once the dict gets really big.

---

*Last updated: 2026-07-11*
