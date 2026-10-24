# Workout narrative

> The plan-workout modal explains the session in a coach's voice — warm-up, main set, cool-down, and why you're running it — instead of a shorthand spec line.

## Purpose

Every plan engine stores a compact description of each session:

```
WU 2 km easy, 6×1000 m @ I pace (4:37/km) w/ 2:00 jog, CD 2 km.
```

That's dense, correct, and perfectly readable *if you already know what it means*. It's a training-log entry, not guidance. Opening the modal on the morning you have to run the session, you want a coach talking to you:

> You'll start with an easy 2 km warm-up to gradually bring your body up to speed for the work ahead.
>
> After warming up, you'll run 6 repetitions of 1000 m at your interval (I) pace of 4:37/km. Between each effort, take 2 minutes of easy jogging to recover and get ready for the next one.
>
> You'll finish with a relaxed 2 km cool-down to ease your body back down and start the recovery.
>
> *This session is built to raise your VO₂max — the ceiling on your aerobic capacity. Repeats at this intensity train your body to take in and use oxygen faster, which makes every slower pace feel easier.*

The last paragraph is the payoff the shorthand never had room for: **why this session exists in the plan**.

## How it works (user view)

Open any day cell on `/plans` → the workout modal. The narrative is the first thing under the title, above the *Target* and *Steps* sections.

- Every workout in every plan gets one — all five methodologies, every workout type.
- Structure is one paragraph per beat: warm-up → main set → cool-down → why.
- Simple sessions collapse to two paragraphs ("Today is 8 km at your easy (E) pace of 6:23/km…" plus the why); rest days to one.
- It follows your UI language (English / Nederlands).
- Where an engine wrote its own prose (Foppen, Couch to 5K, Higdon), those words are kept as their own paragraph — they carry cues the structured data has no field for.

The *Steps* strip below it still gives the same session as scannable chips. The narrative is for reading; the chips are for glancing.

## How it works (implementation)

- **Modules**: `running_coach/plans/narrative.py` — the whole renderer. `narrate(workout, locale) -> list[str]` returns display paragraphs. `running_coach/plans/service.py` gained one public alias, `zone_for_workout` (see below).
- **Templates**: `_plan_workout_modal.html` — the `.tp-pw-desc` block loops the paragraphs into `<p>` elements.
- **Routes**: none added. `GET /plan-workouts/{id}` renders the modal as before.
- **DB**: nothing added. Reads existing `plan_workouts` columns only.
- **External services**: none. This is rules-based; no LLM is involved, so it works offline and costs nothing per render.

### Derived, never stored

The narrative is computed on every render from `workout_structure` plus the row's target fields. That's the central design decision, and it buys three things:

1. **It can't go stale.** Recalibrating your VDOT rewrites the paces inside `workout_structure`; the prose reads those, so it updates for free. Same for manual edits, moves, and event swaps.
2. **It doesn't collide with the pace-refresh regex.** `service._refresh_description_paces` rewrites embedded pace numbers in the *stored* description and only understands a few idioms (see the description-idiom contract in that module). Prose stored in that column would get mangled. Prose derived at render time never enters the picture.
3. **No migration, no backfill.** Existing plans got the feature the moment the code shipped.

### The data it reads

The renderer speaks exactly the step vocabulary every engine already emits:

```
step.type   ∈ warmup | active | recovery | cooldown | repeat
step.end    = {"distance_m": N} | {"duration_s": N}
step.pace_s_per_km, step.zone        (optional)
repeat.iterations + repeat.steps
```

Shapes it recognises, in order: a `repeat` block (intervals, cruise intervals, run/walk repeats) · a single continuous `active` block (tempo, marathon-pace) · two paced `active` blocks (the easy→M-pace long run) · alternating active/recovery with no `repeat` wrapper (hand-built C25K ladders) · no structure at all (plain easy/long runs, read off `target_distance_km` + `target_pace_s_per_km`).

The closing "why" paragraph is a lookup keyed by `(workout_type, zone)`. Zone comes from `service.zone_for_workout` — **the same function the pace recalibrator uses**. That's deliberate: if the prose and the recalibrator ever disagreed about what zone a session is, the modal would describe a workout the watch isn't running. One function, two readers. The single override is a long run whose structure ends on an M-pace segment: it's keyed as a marathon-pace rehearsal rather than a plain endurance run.

### Two safety rules

**Never invent a pace.** Couch to 5K and Foppen are effort-based by contract (`MethodologyInfo.uses_vdot_paces=False`). The renderer detects that no step and no target carries a pace, and switches to duration + effort language. Repeat sessions on those plans also get their own closing paragraph — the Daniels VO₂max copy is true of a Foppen INT block and badly wrong for a beginner's 8×1-minute run/walk. Locked by tests.

**Never misstate a session.** Taper strides are the case that matters: the row is an easy run with 4–6 fast bursts, but it carries R pace and no structure. Narrating "run 4 km at your repetition (R) pace" would be flatly wrong, so structureless *quality* rows fall back to the engine's own description. Race rows do the same — a race's distance is the event, not a prescription, and the engine's course briefing shouldn't be talked over.

## Configuration

Nothing to configure. Language follows the existing UI language setting (Settings → Language); translations live in the *Workout narrative* section of `running_coach/i18n.py`.

## Known limitations

- **A handful of notes restate the walkthrough.** Higdon's tempo and marathon-pace descriptions ("Warm up, then a sustained block at threshold pace (T, 4:50/km). Cool down.") say the same thing the generated paragraphs just said. The keep/drop rule is a length threshold (`_NOTE_MIN_CHARS`), deliberately biased toward keeping: dropping a note that carries an un-encodable cue — Higdon's hill repeats are "8×400 m at I pace" structurally, and only the note says *uphill* — is a real loss, while a redundant note is only noise. A cleaner fix would be a structured `terrain` / `cue` field on the step schema so engines stop smuggling cues in prose.
- **Engine descriptions aren't translated.** The generated sentences are; the authored notes kept alongside them render in English even with the UI in Dutch. Same as before this feature — the engines author in English only.
- **Nuance in short shorthand is dropped.** Daniels' "Cut-back long run, fully easy" becomes "Today is 12 km at your easy (E) pace…" — accurate, but the *cut-back* framing is lost because it's below the note threshold and isn't in the structure.
- **Only the modal.** Day cards, the dashboard "Today" hero and the Garmin push payload still use the stored shorthand. That's intentional — those surfaces are space-constrained — but the dashboard hero is the obvious next candidate.
- **Ladders read long.** A C25K hand-built week renders as "run 5 minutes, walk 3 minutes, run 8 minutes, …" in one sentence. Fine at five blocks, unwieldy at twelve.

## Verification

```
.venv/Scripts/python.exe tests/test_workout_narrative.py     # 18 tests
```

Manual smoke test:

1. Start the app, go to `/plans`, open any interval session on the active plan. You should see three instruction paragraphs plus an italic "why" paragraph, and the pace in the prose must match the *Target* pace shown below it.
2. Open a rest day → one paragraph, no numbers.
3. Switch Settings → Language to Nederlands and reopen the same interval session → the paragraphs are Dutch; the paces, distances and zone letters (E/M/T/I/R) are unchanged.
4. Recalibrate the plan's paces, then reopen the workout → the pace in the prose has moved with it. (This is the regression that motivated deriving rather than storing.)

## Future improvements

1. **Put it on the dashboard "Today" hero.** The one surface where you'd read it before heading out the door. Would need a condensed one-or-two-paragraph mode.
2. **Feed it to the LLM coach.** `llm/context.py` currently passes the shorthand; the narrative is a better-grounded prompt input and would stop the coach re-deriving session intent from abbreviations.
3. **A structured cue field on the step schema** (`terrain: uphill`, `surface: track`), which would let the renderer absorb the last things only the prose notes carry — and retire the length threshold described above.
4. **Per-workout coach commentary**, layering the runner's recent execution scores onto the "why" paragraph ("you nailed this one last week — same effort again").

---

*Last updated: 2026-07-29*
