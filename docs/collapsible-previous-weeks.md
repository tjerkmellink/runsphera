# Collapsible previous weeks

> On an active plan, weeks already in the past are tucked behind a toggle so the page opens on the week you're in plus what's coming.

## Purpose

A long plan (12–16 weeks) makes the active-plan view a tall scroll, and the weeks that matter day-to-day are *this week* and *what's next*. Past weeks are history you check occasionally, not on every visit. Collapsing them puts the current week near the top on load, while a single click still brings the history back.

## How it works (user view)

On the **Plans** page (active plan) and any **plan detail** page:

- Weeks whose span ends *before today* are hidden behind a pill-shaped toggle that reads **"↑ Show N previous weeks"** (the count tells you what's behind it).
- The current week and all upcoming weeks render expanded as before.
- Clicking the toggle reveals the past weeks and the label flips to **"↓ Hide previous weeks"**. Clicking again re-collapses them. State is not persisted — every page load starts collapsed.
- The block-map phase bar above the weeks still shows the *whole* plan (including past weeks) at a glance, so collapsing the cards loses no overview.

Archived plans, and active plans that haven't started yet, show every week (nothing to collapse).

## How it works (implementation)

- **Templates**:
  - `_weeks_section.html` — new shared partial. Partitions `weeks` into `past` / `visible` and renders the eyebrow heading, the optional `<details>` toggle, and the week cards.
  - `plan_detail.html`, `plans.html` — both now delegate week rendering to `_weeks_section.html` via `{% with %}` instead of looping over `_week_card.html` directly.
  - `_week_card.html` — unchanged; rendered once per week as before.
- **CSS**: `app.css` — `.tp-plan-prev-weeks` / `.tp-plan-prev-toggle` styles. The toggle uses a native `<details>`/`<summary>`; `.when-closed` / `.when-open` spans are swapped via the `[open]` attribute selector, so no JavaScript is involved.
- **Routes / DB / external services**: none. This is purely presentational — the same week data already on the page is partitioned client-/render-side.

**Data flow**: the partial walks `weeks`; a week is "past" when `plan_status == 'active'` and its end date (`week.week_end`, else its last workout's `planned_date`, else `week.week_start`) is `< today_iso`. Past weeks go in the `<details>`; everything else renders expanded. A guard catches the all-elapsed case (see limitations).

## Configuration

None. There is no setting — behavior is automatic based on the plan status and today's date.

## Known limitations

- **No persisted state**: expanding past weeks does not survive a reload (deliberate — keeps it pure CSS, no JS/localStorage).
- **All-elapsed active plan**: if an active plan has run entirely into the past (every week ends before today, e.g. it should have been archived but wasn't), collapsing would hide everything. The partial guards this by falling back to showing all weeks expanded with no toggle.
- **Definition of "current week"**: a week counts as visible from the moment it contains today through the end of the plan. Mid-week, the current week is always shown.

## Verification

1. Open the **Plans** page with an active plan that started several weeks ago.
2. Confirm the page opens with only the current + upcoming weeks visible and a **"↑ Show N previous weeks"** pill above them, where N matches the number of fully-past weeks.
3. Click the pill → past week cards appear, label flips to **"↓ Hide previous weeks"**. Click again → they collapse.
4. Open an **archived** plan → all weeks show, no toggle.

## Future improvements

- Persist expanded/collapsed state (localStorage) if the user finds themselves expanding history often.
- Optionally collapse far-future weeks too (e.g. show current ± a window) on very long plans.

---

*Last updated: 2026-06-27*
