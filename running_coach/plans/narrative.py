"""Turn a planned workout into plain-language coaching prose.

## Why this exists

Every plan engine stores a *shorthand* description — `WU 2 km, 6×1000 m @ I
pace (4:37/km) w/ 2:00 jog, CD 2 km.` — which is dense, correct, and reads
like a training log. Fine on a day card; poor guidance when you open the
workout the morning you have to run it.

`narrate()` renders the same workout as three-to-four short paragraphs in a
coach's voice: warm-up → main set → cool-down → *why you're doing this*.

## Why it's derived, never stored

The narrative is computed at render time from `workout_structure` (plus the
row's target fields), so it is **always** in sync:

- Pace recalibration rewrites structure paces → the prose follows for free.
- Manual edits / moves / event swaps → the prose follows for free.
- Nothing new lands in the DB, and the pace-refresh regex in
  `service._refresh_description_paces` never has to parse prose (it would
  corrupt it — see the description-idiom contract in that module).

## Contract with the engines

The renderer understands exactly the step vocabulary every engine emits:

    step.type   ∈ warmup | active | recovery | cooldown | repeat
    step.end    = {"distance_m": …} | {"duration_s": …}
    step.pace_s_per_km, step.zone   (optional)
    repeat.iterations + repeat.steps

Paceless engines (Couch to 5K, Foppen) emit no paces anywhere — the renderer
detects that and switches to effort language rather than inventing numbers.
When a workout carries no structure *and* no safely-narratable target (taper
strides are the case that matters: an easy run whose pace field holds R pace),
it falls back to the shorthand description so nothing is ever lost or, worse,
misstated.

Everything is routed through `i18n.t()` — see the `narrative` section of the
Dutch catalog in running_coach/i18n.py.
"""
from __future__ import annotations

import json
from typing import Any, Mapping

from ..i18n import t
from .service import zone_for_workout


# Zone → the noun phrase used inside "at your {…} pace of 4:37/km". The
# letter rides along because the rest of the UI (Steps strip, titles,
# methodology explainers) speaks in E/M/T/I/R and the runner should be able
# to connect the prose to those chips.
_ZONE_PHRASE = {
    "E": "easy (E)",
    "M": "marathon (M)",
    "T": "threshold (T)",
    "I": "interval (I)",
    "R": "repetition (R)",
    "HM": "half-marathon (HM)",
}

# Closing "why am I doing this" paragraph, keyed by (workout_type, zone).
# Zone is the *effective* zone: a long run with an M-pace finish is keyed
# ("long", "M") even though `zone_for_workout` calls the row E, because the
# M finish is the whole point of the session.
_PURPOSE = {
    ("intervals", "I"): (
        "This session is built to raise your VO₂max — the ceiling on your "
        "aerobic capacity. Repeats at this intensity train your body to take "
        "in and use oxygen faster, which makes every slower pace feel easier."
    ),
    ("intervals", "R"): (
        "Short and fast, this one sharpens your speed, running economy and "
        "form. The goal is to move quickly and smoothly — not to get tired."
    ),
    ("tempo", "T"): (
        "Threshold work lifts the pace you can hold before lactate starts to "
        "pile up. It's the single biggest lever on how fast you can race "
        "anything from 10 km upward."
    ),
    ("tempo", "M"): (
        "Running at goal marathon pace is a rehearsal for race day: it teaches "
        "your body to burn fuel efficiently at exactly the effort you'll be "
        "holding for hours."
    ),
    ("long", "E"): (
        "The long run is the backbone of your endurance. It grows capillaries, "
        "toughens connective tissue and trains your body to burn fat for fuel "
        "— adaptations that only come from time on your feet."
    ),
    ("long", "M"): (
        "Finishing a long run at marathon pace is the closest thing to race "
        "day in the whole plan: it rehearses goal effort on legs that are "
        "already tired, which is exactly what the last 10 km will ask of you."
    ),
    ("easy", "E"): (
        "Easy running is where most of your aerobic engine actually gets "
        "built. It looks unremarkable, but this is the volume that lets the "
        "hard sessions land."
    ),
    ("recovery", "E"): (
        "This is active recovery — gentle movement to clear out the fatigue "
        "from your last hard session. Running it faster than easy only delays "
        "the adaptation you're waiting on."
    ),
    ("race", None): (
        "Race day. Everything in the plan has been pointing at this — run your "
        "own effort, start conservatively, and trust the work you've put in."
    ),
}

_PURPOSE_REST = (
    "Rest is when training turns into fitness. Take the day fully off, or keep "
    "it gentle — a walk, a swim, an easy bike ride."
)

# Effort-based plans (C25K, Foppen) get their own closing line for repeat
# sessions. The Daniels I-zone copy talks about VO₂max repeats — true of a
# Foppen INT block, badly wrong for a beginner's 8×1-minute run/walk. This
# wording is honest for both.
_PURPOSE_PACELESS_REPEATS = (
    "Breaking the work into repeats with recovery in between lets you spend "
    "time at a harder effort than you could hold continuously — that's what "
    "builds both speed and aerobic fitness. Run every rep at the same effort: "
    "the last one should look like the first."
)

# An engine's own description is folded into the narrative as a coach's note
# when it's long enough to be authored prose rather than a spec line. Daniels
# and Pfitzinger shorthand ("WU 2 km easy, 6×1000 m @ I pace …") sits below
# this; the Foppen / C25K / Higdon copy sits above it and is kept.
#
# The threshold is deliberately biased toward *keeping*. A note can carry cues
# the structure JSON has no field for — Higdon's hill repeats are "8×400 m at
# I pace" structurally, and only the note says *uphill*. Dropping that is a
# real loss; keeping a note that restates the walkthrough is only redundant.
# So when in doubt, it stays. (See Known limitations in
# docs/workout-narrative.md.)
_NOTE_MIN_CHARS = 110


# ── formatting helpers ───────────────────────────────────────────────────

def _dist(meters: float) -> str:
    """Distance the way the plan titles say it: metres up to 1000, km above.

    Keeps the prose reading the same as the workout title and the Steps strip
    ("6×1000 m" → "1000 m", "6×1.5 km" → "1.5 km") instead of silently
    renaming the runner's session. Units are identical in both languages, so
    they don't go through the catalog (see i18n's "what we don't translate").
    """
    if meters <= 1000:
        return f"{meters:g} m"
    return f"{meters / 1000:g} km"


def _time(seconds: int, locale: str) -> str:
    """A duration as words — "90 seconds", "2 minutes", "2:30 min".

    Sub-two-minute odd durations read better in whole seconds (a C25K walk
    break is "90 seconds", never "1:30"); longer ones fall back to mm:ss.
    """
    seconds = int(seconds)
    if seconds < 120:
        if seconds % 60 == 0:
            return t("1 minute", locale=locale) if seconds == 60 else \
                t("{n} seconds", n=seconds, locale=locale)
        return t("{n} seconds", n=seconds, locale=locale)
    minutes, rest = divmod(seconds, 60)
    if rest:
        return t("{m}:{s} min", m=minutes, s=f"{rest:02d}", locale=locale)
    return t("{n} minutes", n=minutes, locale=locale)


def _pace(pace_s: int) -> str:
    return f"{pace_s // 60}:{pace_s % 60:02d}/km"


def _zone_phrase(zone: str | None) -> str:
    """Zone names stay English in every locale — same convention as the
    methodology explainers and the E/M/T/I/R chips everywhere else in the UI."""
    return _ZONE_PHRASE.get(zone or "", "easy (E)")


def _amount(step: Mapping[str, Any], locale: str) -> str | None:
    """Render a step's `end` clause — a distance or a duration, whichever
    the engine used. Returns None for open-ended steps (there are none
    today, but a lap-button step would be one)."""
    end = step.get("end") or {}
    if end.get("distance_m"):
        return _dist(end["distance_m"])
    if end.get("duration_s"):
        return _time(end["duration_s"], locale)
    return None


# ── structure inspection ─────────────────────────────────────────────────

def _parse_structure(workout: Mapping[str, Any]) -> dict | None:
    """The already-parsed structure if the caller supplied one, else parse
    the raw JSON column. Bad JSON degrades to 'no structure', which the
    caller handles by falling back to the shorthand description."""
    parsed = workout.get("structure_parsed")
    if isinstance(parsed, dict):
        return parsed
    raw = workout.get("workout_structure")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:  # noqa: BLE001 — malformed JSON is not fatal here
            return None
    return None


def _has_any_pace(structure: dict | None, workout: Mapping[str, Any]) -> bool:
    """True when this session is prescribed by pace at all.

    Effort-based engines (C25K, Foppen) emit no pace on any step and no
    `target_pace_s_per_km` — the renderer must then talk about effort and
    duration only, never invent a speed.
    """
    if workout.get("target_pace_s_per_km"):
        return True
    for step in _walk(structure):
        if step.get("pace_s_per_km"):
            return True
    return False


def _walk(structure: dict | None):
    """Yield every step, descending one level into repeats."""
    for step in (structure or {}).get("steps") or []:
        yield step
        if step.get("type") == "repeat":
            yield from step.get("steps") or []


def _effective_zone(workout: Mapping[str, Any], structure: dict | None) -> str | None:
    """The zone the *purpose* paragraph should speak to.

    Normally `zone_for_workout` (the same title/type vocabulary the pace
    recalibrator uses, so prose and paces can never disagree). The one
    override: a long run whose structure ends on an M-pace segment is a
    marathon-pace rehearsal, not a plain endurance run.
    """
    zone = zone_for_workout(workout)
    if workout.get("workout_type") == "long":
        zones = [s.get("zone") for s in _walk(structure)]
        if "M" in zones:
            return "M"
    return zone


# ── section renderers ────────────────────────────────────────────────────

def _is_timed(step: Mapping[str, Any]) -> bool:
    """True when the step is prescribed in time rather than distance. Drives
    the sentence choice: "an easy 2 km warm-up" vs "5 minutes of easy warm-up"
    — "a relaxed 5 minutes cool-down" is not English."""
    return not (step.get("end") or {}).get("distance_m")


def _warmup_sentence(step: Mapping[str, Any], paced: bool, locale: str) -> str | None:
    amount = _amount(step, locale)
    if not amount:
        return None
    if not paced:
        return t(
            "You'll start with {amount} of easy warm-up — a brisk walk or gentle "
            "jog — to loosen your legs before the work starts.",
            amount=amount, locale=locale,
        )
    if _is_timed(step):
        return t(
            "You'll start with {amount} of easy warm-up to gradually bring your "
            "body up to speed for the work ahead.",
            amount=amount, locale=locale,
        )
    return t(
        "You'll start with an easy {amount} warm-up to gradually bring your "
        "body up to speed for the work ahead.",
        amount=amount, locale=locale,
    )


def _cooldown_sentence(step: Mapping[str, Any], locale: str) -> str | None:
    amount = _amount(step, locale)
    if not amount:
        return None
    if _is_timed(step):
        return t(
            "You'll finish with {amount} of relaxed cool-down to ease your body "
            "back down and start the recovery.",
            amount=amount, locale=locale,
        )
    return t(
        "You'll finish with a relaxed {amount} cool-down to ease your body back "
        "down and start the recovery.",
        amount=amount, locale=locale,
    )


def _repeat_sentences(
    step: Mapping[str, Any],
    after_warmup: bool,
    paced: bool,
    zone: str | None,
    locale: str,
) -> list[str]:
    """The main-set paragraph for a `repeat` block: what you run, how many
    times, at what pace or effort, and what you do between reps."""
    reps = step.get("iterations") or 0
    work = next((s for s in step.get("steps") or [] if s.get("type") == "active"), None)
    recovery = next((s for s in step.get("steps") or [] if s.get("type") == "recovery"), None)
    if not reps or not work:
        return []

    amount = _amount(work, locale)
    if not amount:
        return []
    pace_s = work.get("pace_s_per_km")
    work_zone = work.get("zone") or zone

    out: list[str] = []
    if paced and pace_s:
        key = (
            "After warming up, you'll run {reps} repetitions of {amount} at your "
            "{zone} pace of {pace}."
            if after_warmup else
            "The main set is {reps} repetitions of {amount} at your {zone} pace "
            "of {pace}."
        )
        out.append(t(
            key, reps=reps, amount=amount,
            zone=_zone_phrase(work_zone), pace=_pace(pace_s),
            locale=locale,
        ))
    else:
        # No intensity claim here on purpose: the same shape covers a Foppen
        # INT block and a beginner's 8×1-minute C25K jog, and the engine's own
        # note (kept below) is the one that says which.
        key = (
            "After warming up, you'll run {reps} repetitions of {amount}, at an "
            "effort you can hold just as well on the last one as on the first."
            if after_warmup else
            "The main set is {reps} repetitions of {amount}, at an effort you can "
            "hold just as well on the last one as on the first."
        )
        out.append(t(key, reps=reps, amount=amount, locale=locale))

    if recovery:
        rec = _amount(recovery, locale)
        if rec and paced:
            out.append(t(
                "Between each effort, take {rec} of easy jogging to recover and "
                "get ready for the next one.",
                rec=rec, locale=locale,
            ))
        elif rec:
            out.append(t(
                "Between each effort, walk or jog gently for {rec} until your "
                "breathing settles.",
                rec=rec, locale=locale,
            ))
    return out


def _active_sentences(
    actives: list[Mapping[str, Any]],
    after_warmup: bool,
    paced: bool,
    zone: str | None,
    locale: str,
) -> list[str]:
    """Main-set paragraph for continuous work: one steady block, or the
    two-step easy→marathon-pace long run the marathon engines build."""
    if not actives:
        return []

    if len(actives) == 1:
        step = actives[0]
        amount = _amount(step, locale)
        if not amount:
            return []
        pace_s = step.get("pace_s_per_km")
        if paced and pace_s:
            key = (
                "After warming up, you'll run {amount} at your {zone} pace of "
                "{pace} — one continuous block, holding the effort steady all "
                "the way through."
                if after_warmup else
                "The session is {amount} at your {zone} pace of {pace}, held "
                "steady all the way through."
            )
            return [t(
                key, amount=amount,
                zone=_zone_phrase(step.get("zone") or zone),
                pace=_pace(pace_s), locale=locale,
            )]
        key = (
            "After warming up, you'll run {amount} at a controlled, steady "
            "effort."
            if after_warmup else
            "The session is {amount} of running at a controlled, steady effort."
        )
        return [t(key, amount=amount, locale=locale)]

    # Two or more paced blocks back to back — the progression long run.
    if len(actives) == 2 and paced and all(s.get("pace_s_per_km") for s in actives):
        first, last = actives
        return [t(
            "You'll run the first {first} at your {zone1} pace of {pace1}, then "
            "pick it up for the final {last} at your {zone2} pace of {pace2}.",
            first=_amount(first, locale), last=_amount(last, locale),
            zone1=_zone_phrase(first.get("zone") or zone),
            pace1=_pace(first["pace_s_per_km"]),
            zone2=_zone_phrase(last.get("zone") or zone),
            pace2=_pace(last["pace_s_per_km"]),
            locale=locale,
        )]

    # Anything else (the hand-crafted run/walk ladders) — list the blocks in
    # order rather than pretending they fit a neat shape.
    blocks = [b for b in (_amount(s, locale) for s in actives) if b]
    if not blocks:
        return []
    return [t(
        "The main set runs as a ladder of {n} blocks: {blocks}, with an easy "
        "walk or jog between them.",
        n=len(blocks), blocks=", ".join(blocks), locale=locale,
    )]


def _ladder_sentence(steps: list[Mapping[str, Any]], locale: str) -> str | None:
    """Run/walk ladders (C25K's uneven weeks) alternate active and recovery
    blocks at the top level. Read them out in order — the sequence *is* the
    workout."""
    parts: list[str] = []
    for step in steps:
        amount = _amount(step, locale)
        if not amount:
            continue
        if step.get("type") == "active":
            parts.append(t("run {amount}", amount=amount, locale=locale))
        else:
            parts.append(t("walk {amount}", amount=amount, locale=locale))
    if len(parts) < 2:
        return None
    return t(
        "The main set alternates in this order: {blocks}. Follow the sequence "
        "as written — the walk breaks are what let the running blocks grow.",
        blocks=", ".join(parts), locale=locale,
    )


def _plain_run_sentence(workout: Mapping[str, Any], zone: str | None, locale: str) -> str | None:
    """Structureless easy / long / recovery runs — distance (or time) at one
    pace. Deliberately limited to E-zone rows: a structureless *quality* row
    (taper strides carry R pace on what is really an easy run) would be
    misdescribed, so those fall back to the shorthand instead."""
    if zone != "E":
        return None
    km = workout.get("target_distance_km")
    pace_s = workout.get("target_pace_s_per_km")
    duration_s = workout.get("target_duration_s")
    if km and pace_s:
        return t(
            "Today is {amount} at your easy (E) pace of {pace}. Keep it "
            "conversational — if you couldn't hold a chat, you're going too "
            "fast.",
            amount=_dist(km * 1000), pace=_pace(pace_s),
            locale=locale,
        )
    if km:
        return t(
            "Today is {amount} at an easy, conversational effort.",
            amount=_dist(km * 1000), locale=locale,
        )
    if duration_s:
        return t(
            "Today is {amount} of running at an easy, conversational effort.",
            amount=_time(duration_s, locale), locale=locale,
        )
    return None


# ── entry point ──────────────────────────────────────────────────────────

def narrate(workout: Mapping[str, Any], locale: str = "en") -> list[str]:
    """Plain-language paragraphs describing how to run `workout`.

    `workout` is a `plan_workouts` row (as a dict); `structure_parsed` is used
    when the caller has already decoded the JSON. One paragraph per beat of the
    session — warm-up · main set · cool-down · why — and always at least one,
    worst case the engine's shorthand, so callers can render unconditionally.
    """
    wtype = workout.get("workout_type") or "easy"
    shorthand = (workout.get("description") or "").strip()

    if wtype in ("rest", "cross"):
        return [t(_PURPOSE_REST, locale=locale)]

    # Race rows carry hand-authored pacing notes (Foppen's seven-hills
    # briefing, C25K's graduation line) and a distance that is the *event*,
    # not a prescription. Narrating "15 km at a steady effort" would talk over
    # the coach — so the note and the why-paragraph carry the day on their own.
    if wtype == "race":
        return _note_paragraphs(shorthand) + [t(_PURPOSE[("race", None)], locale=locale)]

    structure = _parse_structure(workout)
    paced = _has_any_pace(structure, workout)
    zone = zone_for_workout(workout)
    effective_zone = _effective_zone(workout, structure)

    steps = list((structure or {}).get("steps") or [])
    warmup = next((s for s in steps if s.get("type") == "warmup"), None)
    cooldown = next((s for s in steps if s.get("type") == "cooldown"), None)
    repeat = next((s for s in steps if s.get("type") == "repeat"), None)
    actives = [s for s in steps if s.get("type") == "active"]
    top_recoveries = [s for s in steps if s.get("type") == "recovery"]

    paragraphs: list[str] = []

    if warmup:
        sentence = _warmup_sentence(warmup, paced, locale)
        if sentence:
            paragraphs.append(sentence)
    has_warmup = bool(paragraphs)

    # Main set — one paragraph, however many sentences it takes to describe.
    main: list[str] = []
    if repeat:
        main = _repeat_sentences(repeat, has_warmup, paced, zone, locale)
    elif actives and top_recoveries:
        # Alternating blocks with no repeat wrapper — a hand-built ladder.
        ladder = _ladder_sentence(
            [s for s in steps if s.get("type") in ("active", "recovery")], locale
        )
        main = [ladder] if ladder else _active_sentences(actives, has_warmup, paced, zone, locale)
    elif actives:
        main = _active_sentences(actives, has_warmup, paced, zone, locale)
    elif not structure:
        sentence = _plain_run_sentence(workout, zone, locale)
        main = [sentence] if sentence else []

    # The engine's own words, when they're authored prose rather than a spec
    # line. Hill repeats are the case that proves the rule: the structure says
    # "8×400 m at I pace", and only the note says *uphill*.
    note = _note_paragraphs(shorthand) if len(shorthand) >= _NOTE_MIN_CHARS else []

    # A session with no warm-up, cool-down or repeats has nothing to decompose
    # — it's one continuous run. Where the engine already described that in its
    # own voice (Foppen's "RD 40 min", Higdon's easy runs), our generic "the
    # session is 40 minutes at a steady effort" only says it worse.
    is_single_block = not (warmup or cooldown or repeat)
    if main and not (note and is_single_block):
        paragraphs.append(" ".join(main))

    if cooldown:
        sentence = _cooldown_sentence(cooldown, locale)
        if sentence:
            paragraphs.append(sentence)

    if note:
        paragraphs.extend(note)
    elif not paragraphs and shorthand:
        # Nothing safely narratable (taper strides) — show the engine's
        # shorthand rather than an invented or empty session.
        paragraphs.extend(_note_paragraphs(shorthand))

    if repeat and not paced:
        purpose = _PURPOSE_PACELESS_REPEATS
    else:
        purpose = _PURPOSE.get((wtype, effective_zone))
    if purpose:
        paragraphs.append(t(purpose, locale=locale))

    # A row with no structure, no targets and no description yields nothing —
    # return an empty list, not [""], so the template's `if` hides the block.
    return paragraphs or _note_paragraphs(shorthand)


def _note_paragraphs(text: str) -> list[str]:
    """Split an engine description into display paragraphs. Foppen's copy
    carries a blank-line-separated "Weekly challenge" block; collapsing that
    into one run-on paragraph loses the shape the author intended."""
    if not text:
        return []
    return [block.strip() for block in text.split("\n\n") if block.strip()]
