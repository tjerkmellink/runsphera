# {{ Feature name }}

> One-line tagline describing what this feature is and who it's for.

## Purpose

What problem this solves for the runner. Why it exists in the app. The user-facing payoff.

## How it works (user view)

Where the user encounters this feature, what they see, what they do. Include the UI surfaces (routes, modals, cards). Step-by-step where helpful. Screenshots optional — link them under `docs/img/<feature>/...` if added.

## How it works (implementation)

The code surface area:

- **Modules**: list the `.py` files involved and one-line summary of each.
- **Templates**: list any `.html` files involved.
- **Routes**: HTTP routes added or touched by the feature.
- **DB**: tables / columns added or read.
- **External services**: Garmin / Anthropic / etc., if any.

Then narrative for the **data flow** — input → transform → output. Caching/invalidation strategy if any.

## Configuration

Anything the user (or operator) can change to influence behavior: settings page entries, env vars, defaults. Note where each is stored.

## Known limitations

Edge cases the implementation doesn't handle, scope boundaries chosen deliberately, things that need manual work today. Be honest — this section is gold for future maintenance.

## Verification

How to confirm the feature works as documented. A short manual smoke test the user can run themselves (URL to hit, button to click, expected output). Useful as a "did I break it?" regression check after refactors.

## Future improvements

Ideas worth picking up next, ordered by rough payoff. Cross-link the [project README](../README.md) roadmap section if there's overlap.

---

*Last updated: YYYY-MM-DD*
