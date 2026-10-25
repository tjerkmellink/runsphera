# This week, wrapped

> A dashboard stats strip for the active plan's current training week — live all week, celebratory when you close it out.

## Purpose

The plan week is the unit of training that actually moves fitness, but the dashboard had no single place that said "here's your week." This block gives the runner a running tally of the current training week and turns finishing the last session into a moment — big numbers, a consistency streak, and a coach line that makes the effort feel earned. It's the endorphin payoff for closing a week, not another table.

## How it works (user view)

A strip on the dashboard (`/`), styled exactly like the ③ **The numbers** stats wall, sitting just below it as section ④ **This week**. It appears whenever an active plan has a current training week with at least one running session.

- **All week** it shows progress — `2/4 sessions`, distance banked so far, time on feet — with a calm one-line nudge ("2 of 4 done — 2 to go this week. Keep it rolling.").
- **On the last session** (all planned sessions matched to runs) it flips to a **complete** state: an accent top-rule, the streak number turns red with a 🔥, the eyebrow reads `Done ✓`, and the coach line becomes a genuine celebration.

The four big italic numbers:

| Cell | Value |
|---|---|
| **Distance** | actual km run this week (sub-line: sessions done, weekly load) |
| **Time on feet** | total moving time this week (sub-line: longest run) |
| **Plan total** | cumulative actual km banked across the whole plan (sub-line: runs since day one) |
| **Streak** | consecutive weeks at ≥80% adherence (🔥 from 2+) |

The block **resets automatically** when the next training week starts — that week is incomplete, so the strip simply renders its progress state again. No dismiss, no persistence flag.

The coach line is **LLM-generated** when the week is complete and a coach-voice model is configured (with a ↻ regenerate button, same as the weekly recap). When the LLM is unavailable, or any time the week is mid-progress, it renders an **instant rules-based line** instead — so a normal page load never blocks on the model.

## How it works (implementation)

- **Modules**:
  - `runsphera/plans/service.py` — `week_stats()` (the aggregator), `current_plan_week()`, `streak_weeks()` + `_week_qualifies_for_streak()`, `week_end_iso()`, and `STREAK_MIN_ADHERENCE = 0.8`.
  - `runsphera/llm/commentary.py` — `week_wrapped()` (cached LLM celebration), `peek_week_wrapped()`, `week_wrapped_generated_at()`, `_week_wrapped_key()`.
  - `runsphera/llm/prompts.py` — `WEEK_WRAPPED_SYSTEM_PROMPT` + `week_wrapped_request_block()`.
  - `runsphera/web/app.py` — `_build_week_wrapped()` helper, wired into the `index` route; `POST /week-wrapped/refresh`.
- **Templates**: `_week_wrapped.html` (the section + rules-based fallback copy), included from `index.html`.
- **Routes**: `GET /` (renders the block), `POST /week-wrapped/refresh` (↻ regenerate on a complete week).
- **DB**: reads `plan_workouts` joined to `activities` (distance, duration, training load, elevation). LLM output caches in `llm_cache` under `week_wrapped:{plan_id}:{week_number}:{sessions_done}`.
- **External services**: Anthropic/Gemini via the existing coach connector — only when the week is complete.

**Data flow:** the `index` route calls `_build_week_wrapped(conn, active_plan, today_iso)`, which finds the current plan week (`current_plan_week`), aggregates actuals + streak (`week_stats`), and — only if the week is `complete` — fetches the celebration line (`week_wrapped`, cache-first). The template renders the stats always and picks LLM line → rules line → progress line by state.

**Caching / invalidation:** the LLM cache key embeds `sessions_done`, so any change to the week's completion state naturally produces a new key — a stale pre-completion line can never be served, and no explicit invalidation hook is needed. The line is generated once, on the completion transition.

**Streak semantics:** a week keeps the streak alive at ≥80% of its qualifying (non-rest/cross) sessions. Strictly-prior weeks are fully elapsed, so their ratio is final; the current week joins the streak only once it crosses 80%, so mid-week the counter reflects the runner's prior run and ticks up when they complete enough of this week. All-rest weeks are transparent — they neither count nor break the streak.

## Configuration

- **Coach voice** (Settings → Coach voice): when configured, complete weeks get an LLM celebration; otherwise the rules-based line is used. No other knobs.
- **`STREAK_MIN_ADHERENCE`** (in `service.py`) — the 0.8 threshold, if the forgiveness ever needs tuning.

## Known limitations

- "Distance/time this week" counts only runs **matched to a plan workout** — an unplanned bonus run in the same week isn't in the tally (by design: this is plan adherence, not raw log volume).
- The LLM celebration is generated synchronously on the first dashboard load after a week completes (same pattern as the weekly recap) — a one-off ~1 s wait on that single load.
- Elevation is aggregated but not currently shown in a cell (available for the LLM context and future use).
- Streak counts plan weeks only; it resets across a plan boundary (a new plan starts a fresh streak).

## Verification

1. On an active plan, open `/` mid-week → the ④ **This week** strip shows `X/Y sessions` and a "keep it rolling" line.
2. Match runs to every planned session of the current week (sync, or set `actual_activity_id`) → reload `/` → the strip flips to the **complete** state (accent rule, 🔥 streak, celebration line).
3. With coach voice configured, click ↻ → the line regenerates via `POST /week-wrapped/refresh`.
4. Roll into the next week → the block returns to its progress state for the new week.

`pytest tests/test_week_stats.py` covers the aggregation, cumulative plan distance, streak counting, and the `complete` flag.

## Future improvements

- A compact "week wrapped" flourish on the run-detail Replay slide for the run that *closes* the week.
- Split/pace PB detection folded into the celebration facts.
- Surface elevation as a swappable cell (user-chosen fourth stat).

---

*Last updated: 2026-07-26*
