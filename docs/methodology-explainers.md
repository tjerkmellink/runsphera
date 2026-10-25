# Methodology "Read more" explainers

> The **Read more** button on each methodology tile of `/plans/new` opens a modal that explains the plan in depth — who built it, the core idea, what a week looks like, and why you'd choose it.

## Purpose

The [methodology picker](methodology-picker.md) tile is deliberately scannable: hook, fact-chips, a three-line description, "Best for". That's enough to compare tiles, but not enough to *commit* to 8–23 weeks of training. Before a runner picks a plan they reasonably want to know: who is this person, why this method, what will my weeks actually look like, and is it right for me?

The explainer modal answers exactly that — long-form editorial copy per methodology, in the app's house style, without leaving the create-plan flow.

## How it works (user view)

- On `/plans/new`, every methodology tile has a **Read more →** button under its description.
- Clicking it opens a centered modal (`<dialog>`): a hero-image masthead (title, tagline, author credit, fact-chips) over a scrollable article of sections.
- Sections can carry an **illustration placeholder** — a dashed box naming the diagram we'd add, with a collapsible **Generation prompt** written in the same risograph house style as the hero images. Until a rendered PNG is dropped in, the placeholder stands in; the button always works.
- Close via the × , the backdrop, `Esc`, or the footer **Close** button.

## How it works (implementation)

- **Modules**:
  - `runsphera/plans/explainers.py` — the content. `MethodologyExplainer` (tagline, credit, lead, sections) → `ExplainerSection` (heading, paragraphs, bullets, optional illustration) → `Illustration` (slug, concept, prompt). `_EXPLAINERS` dict keyed by methodology id; `get_explainer(id)` returns `None` when unauthored. `ILLUSTRATION_STYLE` is the shared house-style suffix appended to every prompt.
- **Templates**:
  - `web/templates/_method_detail.html` — the modal body. Renders the explainer, or falls back to the tile's own `description` + `best_for` when no explainer exists.
  - `web/templates/plans_new.html` — the tile's **Read more** button (`hx-get` → `#method-detail-content`, then `showModal()`) and the `#method-detail-modal` `<dialog>` shell.
- **Routes**: `GET /plans/methodology/{methodology_id}/detail` (`methodology_detail`) — renders `_method_detail.html`; 404 on unknown id.
- **CSS**: `web/static/app.css`, the `.md-*` block (`.method-detail-modal`, `.md-masthead`, `.md-section`, `.md-illus*`). Reuses the shared `dialog.modal` shell from `base.html`.
- **DB / external services**: none. Pure static content.

**Data flow**: button `hx-get` → route looks up `MethodologyInfo` + explainer → template renders into the dialog → `hx-on::after-request` calls `showModal()`. Illustration asset path convention: `static/method-detail/<methodology_id>-<slug>-{light,dark}.png`.

## Configuration

None user-facing. Authoring is code: add a `MethodologyExplainer` entry to `_EXPLAINERS`. Content is authored English and rendered `|safe` (light inline `<b>`/`<em>` allowed — it is trusted, not user input).

## Localisation

Full English + Dutch. The long-form copy lives in `explainers.py`, **not** the global `_NL` catalog — long HTML paragraphs make terrible dict keys. `_EXPLAINERS` (en) and `_EXPLAINERS_NL` (nl) hold parallel structures; `get_explainer(id, locale)` selects (falls back to English for any un-translated locale/methodology). The route passes `_current_language()`. Illustration **generation prompts are language-independent** (image-gen reads best in English) — the Dutch entries omit them and `_backfill_nl_prompts()` copies them from the English entry by slug. English zone names (Easy/Marathon/Threshold/Interval/Repetition) and RD/DT/INT stay untranslated, matching the tile copy. The template's placeholder chrome ("Illustration:", "Generation prompt") is translated via the normal `t()`/`_NL` path.

## Known limitations

- **All six authored, both languages.** Daniels, Foppen, Pfitzinger, Higdon, Couch to 5K, and Hybrid (a "coming soon" preview) all have full en + nl content. The graceful fallback (tile description) remains for any future methodology added without an explainer.
- **Illustrations are partly placeholders.** Jack Daniels' two illustrations are rendered (`static/method-detail/daniels-*.png`); the rest still show the concept + prompt box. The route checks disk per illustration (`illus_ready`) and shows the image only when both `-light`/`-dark` PNGs exist, so dropping in a pair lights it up with no code change.

## Verification

1. `GET /plans/new`, click **Read more** on the Jack Daniels tile → modal opens with hero, credit line, four sections, and two rendered illustrations (VDOT dial, pace spectrum) that swap light/dark with the theme.
2. On a methodology whose PNGs aren't in yet, the illustration shows a placeholder box; expand its **Generation prompt** → full prompt with the house-style suffix + a `static/method-detail/<id>-<slug>-light.png` save hint.
3. Toggle light/dark → the hero swaps variants; content stays legible.
4. Click **Read more** on a tile without an explainer (e.g. Hybrid) → fallback body ("A fuller guide … on the way").
5. `GET /plans/methodology/bogus/detail` → 404.

## Future improvements

1. Generate the remaining illustration PNGs from the embedded prompts and drop the `-light`/`-dark` pairs into `static/method-detail/` (Daniels' two are done). Combined light-over-dark exports split cleanly at the light→dark row boundary — see how Daniels' were cropped.

---

*Last updated: 2026-07-23*
