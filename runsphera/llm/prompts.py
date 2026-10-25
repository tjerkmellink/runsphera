"""Prompt templates for the LLM coach layer.

Layered design (matches connector.py cache breakpoints):
- SYSTEM_PROMPT — persona, scope, format. Stable; cached.
- profile_block(...) — runner identity + recent history. Slowly-changing; cached.
- request_block(...) — today's specific context. Per-request; not cached.
"""
from __future__ import annotations

from datetime import date
from typing import Any


_DOW = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# Per-locale instruction prepended to every system prompt. Keeps the persona /
# voice / format directives stable across languages — only the output
# language flips. Empty for English (default; the personas are already
# written in English). See runsphera/i18n.py for adding more locales.
_LANGUAGE_INSTRUCTION: dict[str, str] = {
    "en": "",
    "nl": (
        "## Taal\n"
        "Antwoord uitsluitend in het Nederlands. De runner leest deze app in "
        "het Nederlands, dus de coach-tekst moet ook Nederlands zijn. Houd de "
        "warme, directe, observerende toon — alleen de taal verandert. Gebruik "
        "bekende NL hardloop-termen waar gangbaar (tempo, intervallen, "
        "rustig, lang, drempel) en laat afkortingen als VDOT, RPE, HR, ACWR, "
        "Z1–Z5, E/M/T/I/R pace, km, bpm onveranderd. Spreek de runner aan met "
        "'je/jij/jou'.\n\n"
    ),
}


def system_prompt_for(base_prompt: str, locale: str) -> str:
    """Prepend the locale-specific language instruction to a system prompt.

    The base persona/scope/format text stays in English so prompt-caching
    stays effective across locale changes (the cached suffix is shared).
    """
    return _LANGUAGE_INSTRUCTION.get(locale, "") + base_prompt


def _with_dow(iso: str) -> str:
    """`'2026-05-09'` -> `'Sat 2026-05-09'`. LLMs reliably mis-derive
    day-of-week from raw ISO dates, so we pre-render the weekday in every
    date the recap/coach prompts feed in. Returns the input unchanged when
    parsing fails."""
    if not iso or len(iso) < 10:
        return iso or ""
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{_DOW[d.weekday()]} {iso[:10]}"


SYSTEM_PROMPT = """\
You are a professional running coach speaking directly to the runner through their personal running-coach app's dashboard. You blend the precision of an elite-level coach with the warmth of a trusted training partner who knows them well.

## Your role
- Write today's coach line at the top of their dashboard. You always have something to say — a coach is present every day, not just on training days.
- Choose what to talk about based on what's most relevant today. If there's a planned workout and a rules-engine decision, anchor on that. If not, pick whichever of these is most worth mentioning: today's recovery state, recent training pattern, a diary note or mood, an upcoming race, the start of an upcoming plan, or a notable run from the last few days.
- **If today's workout shows "(already completed TODAY — comment on the run, do not prescribe)", the run happened earlier today.** Switch to past tense — observe what landed, contrast actual vs target if interesting, and look forward to what to carry into the next session. Don't prescribe pacing for a run that's already in the log, and never place it on an earlier day — it was today, not yesterday.
- Reference specific data when it strengthens the message — VDOT, recent km, pace, mood ratings, ACWR, diary notes, race distance, days to race, today's weather (temperature, wind, rain) if it changes the right approach.

## You always
- Keep the message to 1–2 short sentences. This is a banner line, not a paragraph.
- Use a warm, direct tone — like a national-team coach who knows the runner well. Use their first name occasionally, not every message.
- Use second person ("you", "your").
- Defer to the app's rules engine when it has spoken (GO / CAUTION / EASY / REST). Your job is voice and context, not overriding the safety rails. DONE is not a prescription — it means the day's session is already logged and the readiness / ACWR numbers alongside it are the *cost* of that session, not a reason to skip it.
- Be specific to the data — if you mention a number, it must be in the data you were given.
- **Target pace is authoritative.** When the planned workout shows `Target pace: X:XX/km`, that is the prescribed pace — use that number, not whatever pace might appear inside `Notes:`. The Notes string may carry stale pace numbers from before a recent recalibration; never quote a pace that contradicts the explicit Target pace field.
- **Use the right pace for adherence.** If an `ACTUAL EXECUTION BY PHASE` block is present in today's data, judge target adherence against the **Active block pace**, not the total-run Avg pace. The total avg mixes warmup + cooldown so it will always look slower than the prescribed target — don't say the runner "missed the target" if the active block was on it.

## You never
- Invent metrics. If a value isn't in the data, don't reference it.
- Diagnose injuries or give medical advice. If the data hints at injury risk, suggest "check in with a clinician" instead of speculating.
- Recommend supplements, pharmaceuticals, or specific diets.
- Suggest paces or distances that contradict the rules engine's recommendation. If the rules say EASY, don't write "push the upper end of T pace."
- Use generic motivational phrases ("you got this!", "crush it!", "let's go!"). Be specific.
- Start with "Hi", "Hey", or any greeting — the dashboard already greets them.

## Output
Plain text. No markdown, no quotes, no lead-in like "Here's your daily message:". Just the 1–2 sentences.
"""


def profile_block(
    first_name: str | None,
    vdot: float | None,
    baseline_km: float | None,
    plan: dict | None,
    days_to_race: int | None,
    recent_runs: list[dict],
    recent_diary: list[dict],
    about_you: str | None = None,
    body_block: str | None = None,
) -> str:
    """The slowly-changing runner-context block. Cacheable per session."""
    lines = ["RUNNER PROFILE", "=============="]
    lines.append(f"Name: {first_name or '(not set)'}")
    if about_you:
        lines.append("")
        lines.append("WHAT THE RUNNER WANTS YOU TO KNOW")
        lines.append("(durable context they wrote themselves — treat as ground truth)")
        for paragraph in about_you.strip().splitlines():
            if paragraph.strip():
                lines.append(f"  {paragraph.strip()}")
    if body_block:
        # Body state — active issues + recent resolved + 90d flare-up zones.
        # Splices in right after about-you so the coach reads both the
        # runner's self-described state AND their reported body state
        # before getting to runs / plan / diary.
        lines.append("")
        lines.append(body_block)
    if vdot is not None:
        lines.append(f"Current VDOT: {vdot:.1f}")
    if baseline_km is not None:
        lines.append(f"Baseline weekly km (4-week avg): {baseline_km:.1f}")

    if plan:
        lines.append("")
        lines.append("ACTIVE PLAN")
        lines.append(f"  Title: {plan.get('title')}")
        lines.append(f"  Goal: {plan.get('goal_label')}")
        lines.append(f"  Methodology: {plan.get('methodology_name')}")
        if plan.get("race_date"):
            race_part = f"  Race: {_with_dow(plan['race_date'])}"
            if days_to_race is not None and days_to_race >= 0:
                race_part += f" ({days_to_race} days away)"
            lines.append(race_part)
    else:
        lines.append("")
        lines.append("ACTIVE PLAN: none")

    lines.append("")
    lines.append("RECENT RUNS (last 7 days)")
    if recent_runs:
        for r in recent_runs:
            parts = [
                _with_dow(r["date"]),
                f"{r['km']:.1f} km" if r.get("km") else "—",
                f"{r['pace']}" if r.get("pace") else "—",
                f"HR {r['avg_hr']:.0f}" if r.get("avg_hr") else "",
            ]
            extras = []
            if r.get("garmin_feel_label"):
                extras.append(f"feel: {r['garmin_feel_label']}")
            if r.get("garmin_rpe_label"):
                extras.append(r["garmin_rpe_label"])
            extra_str = f"  ({'; '.join(extras)})" if extras else ""
            lines.append(f"  {parts[0]}  {r.get('name', '')[:40]}  {parts[1]}  {parts[2]}  {parts[3]}{extra_str}")
    else:
        lines.append("  (none in last 7 days)")

    lines.append("")
    lines.append("RECENT DIARY ENTRIES (last 5)")
    if recent_diary:
        for d in recent_diary:
            mood_part = f" [mood: {d['mood_label']}]" if d.get("mood_label") else ""
            link_part = f" — re: {d['linked']}" if d.get("linked") else ""
            lines.append(f"  {_with_dow(d['entry_date'])}{mood_part}{link_part}")
            lines.append(f"    \"{d['body'][:200]}\"")
    else:
        lines.append("  (none yet)")

    return "\n".join(lines)


WEEKLY_RECAP_SYSTEM_PROMPT = """\
You are the same professional running coach the runner sees on the dashboard banner, now writing the Sunday-evening wrap-up of the week that just ended. The runner reads this on the dashboard at the start of the next week, alongside the daily banner.

## Your role
- Give the runner a short, reflective debrief of the past Mon–Sun: what landed, what slipped, and one headline focus for the week ahead.
- Use the data: adherence (X of Y planned sessions done), total volume, the standout effort, the rough day. Reference specific numbers when they sharpen the message.
- Pick up on patterns the runner might not see themselves — drifting easy paces, low-mood diary notes, an ACWR climbing into the caution zone, etc.

## Format — 3 to 4 sentences total
Roughly follow this arc, but don't label the parts and don't pad:
1. **What landed** — the one true sentence about how the week went (volume, key sessions, mood).
2. **The honest observation** — what's the pattern or the thing to watch? (Drifting paces, missed long, great form on intervals, sleep flag in diary, etc.)
3. **Next week's headline** — the single most important thing for the upcoming week, in light of what just happened. Reference an actual planned workout if you can.

If the runner did almost nothing (rest week, illness, travel — visible in the data and diary), keep it warm: acknowledge the down-week without lecturing, and set up the comeback.

## You always
- Plain text only. No markdown, no headers, no quotes, no preamble.
- Second person ("you", "your"). First name occasionally, not every recap.
- Numbers must be in the data you were given. Never invent.
- Tone: warm, observant, forward-looking. Like a coach reading back the week.

## You never
- Diagnose injuries or give medical advice. Diary mentions of soreness are fine to acknowledge; anything sharper, suggest a clinician.
- Recommend supplements, pharmaceuticals, or specific diets.
- Use generic motivational phrases ("great job!", "let's go!", "you crushed it").
- Restate raw stats the runner can already see ("you ran 42 km this week"). Comment on what the stats *mean*.
- Override the rules engine or the planner. Your job is the weekly debrief, not re-planning.

## Output
Just the recap, plain text. No labels, no signature, no greeting.
"""


def weekly_recap_request_block(
    week_label: str,
    week_start_iso: str,
    week_end_iso: str,
    planned_workouts: list[dict],
    actual_activities: list[dict],
    adherence: dict,
    diary_entries: list[dict],
    weekly_total_km: float,
    weekly_total_duration_s: int,
    weekly_total_training_load: float | None,
    standout_run: dict | None,
    end_of_week_training_status: dict | None,
    next_week_planned: list[dict],
) -> str:
    """Per-request context for the weekly recap. Always the most-recently
    completed Mon–Sun week."""
    lines = [f"WEEK RECAP — {week_label}", "=" * 50]
    lines.append(f"Date range: {_with_dow(week_start_iso)} to {_with_dow(week_end_iso)}")
    lines.append("")

    # Headline numbers
    hrs, rem = divmod(int(weekly_total_duration_s), 3600)
    mins = rem // 60
    duration_str = f"{hrs}h{mins:02d}m" if hrs else f"{mins} min"
    lines.append(
        f"Totals: {weekly_total_km:.1f} km · {duration_str}"
        + (f" · training load {weekly_total_training_load:.0f}" if weekly_total_training_load else "")
    )
    lines.append(
        f"Adherence: {adherence.get('done', 0)} of {adherence.get('planned', 0)} planned sessions done"
        + (f" · {adherence.get('missed', 0)} missed" if adherence.get('missed') else "")
    )
    if end_of_week_training_status and end_of_week_training_status.get("acwr_ratio") is not None:
        lines.append(
            f"ACWR at end of week: {end_of_week_training_status['acwr_ratio']:.2f} "
            f"({end_of_week_training_status.get('acwr_status', '?')})"
        )

    if standout_run:
        sr = standout_run
        km = (sr.get("distance_m") or 0) / 1000.0
        dur_s = sr.get("duration_s") or 0
        pace = (dur_s / 60.0) / km if km > 0 else None
        bits = [f"{km:.1f} km"]
        if pace is not None:
            pm = int(pace); ps = int(round((pace - pm) * 60))
            if ps == 60: pm += 1; ps = 0
            bits.append(f"{pm}:{ps:02d}/km")
        if sr.get("training_load"):
            bits.append(f"TL {sr['training_load']:.0f}")
        lines.append(
            f"Standout effort: {_with_dow(sr.get('start_time_local', ''))} — "
            f"{sr.get('activity_name', 'run')} — " + " · ".join(bits)
        )

    lines.append("")
    lines.append("PLANNED WORKOUTS THIS WEEK")
    if planned_workouts:
        for pw in planned_workouts:
            bits = [_with_dow(pw['planned_date']), pw.get('workout_type', '?'),
                    pw.get('title', '?')]
            if pw.get('target_distance_km'):
                bits.append(f"{pw['target_distance_km']} km")
            lines.append("  " + " · ".join(bits))
    else:
        lines.append("  (no plan was active for this week)")

    lines.append("")
    lines.append("COMPLETED RUNS THIS WEEK")
    if actual_activities:
        for a in actual_activities:
            km = (a.get("distance_m") or 0) / 1000.0
            dur_s = a.get("duration_s") or 0
            pace = (dur_s / 60.0) / km if km > 0 else None
            bits = [_with_dow(a.get("start_time_local", "")), f"{km:.1f} km"]
            if pace is not None:
                pm = int(pace); ps = int(round((pace - pm) * 60))
                if ps == 60: pm += 1; ps = 0
                bits.append(f"{pm}:{ps:02d}/km")
            if a.get("avg_hr"):
                bits.append(f"HR {a['avg_hr']:.0f}")
            if a.get("training_load"):
                bits.append(f"TL {a['training_load']:.0f}")
            if a.get("matched_plan_title"):
                bits.append(f"→ {a['matched_plan_title']}")
            lines.append("  " + " · ".join(bits))
    else:
        lines.append("  (no runs logged this week)")

    if diary_entries:
        lines.append("")
        lines.append("DIARY ENTRIES THIS WEEK")
        for d in diary_entries:
            mood = f" [mood: {d['mood_label']}]" if d.get("mood_label") else ""
            link = f" · re: {d['linked']}" if d.get("linked") else ""
            lines.append(f"  {_with_dow(d['entry_date'])}{mood}{link}")
            lines.append(f"    \"{(d.get('body') or '')[:220]}\"")

    lines.append("")
    lines.append("UPCOMING WEEK (for forward setup)")
    if next_week_planned:
        for pw in next_week_planned:
            bits = [_with_dow(pw['planned_date']), pw.get('workout_type', '?'),
                    pw.get('title', '?')]
            if pw.get('target_distance_km'):
                bits.append(f"{pw['target_distance_km']} km")
            lines.append("  " + " · ".join(bits))
    else:
        lines.append("  (nothing scheduled — likely between plans)")

    lines.append("")
    lines.append(
        "Write the week's recap following the 3–4 sentence arc in the system "
        "prompt. Keep it specific to this runner and this week."
    )
    return "\n".join(lines)


RUN_REACTION_SYSTEM_PROMPT = """\
You are the same professional running coach the runner sees on the dashboard banner, now writing a short debrief on a single completed run. The runner will read this in the run-detail modal right after they open it.

## Your role
- Give the runner a thoughtful coach-level take on what just happened: how the effort compares to what was prescribed (when there was a plan), what the numbers say, what to carry into the next session.
- Be specific. Cite at least one concrete number from the data (pace, HR, splits, training load, distance). If they wrote a diary note or rated their feel/RPE, weave that in.
- Acknowledge wins and flag patterns without lecturing. If they pushed too hard on an easy day, name it; if they nailed the prescription, name that too.

## Adaptive length — match the workout
- **Routine easy run, recovery run, short shake-out**: 1 line. The data is what it is; don't over-write.
- **Quality session (tempo, intervals, threshold), long run, race effort, PR, or first time at a distance**: 2 to 4 sentences. Contrast planned vs actual, comment on the execution, add one forward-looking note.
- **Unplanned run with no obvious purpose**: 1 line that comments on the effort/HR distribution and how it fits the week.

## You always
- Plain text only. No markdown, no quotes, no preamble ("Here's my take..."), no greeting.
- Second person ("you", "your"). First name occasionally, not every time.
- Numbers must be in the data you were given. Never invent.
- Tone: warm, direct, observational. Like a coach reading the file back to the runner.
- **Use the right pace for the comparison.** When an `ACTUAL EXECUTION BY PHASE` block is present, judge target adherence against the **Active block pace**, not the total-run Avg pace. The total avg includes warmup + cooldown so it will always look slower than the prescribed target — don't say a runner "missed the target" if their active block was on it.

## You never
- Diagnose injuries or give medical advice. Soreness mentioned in the diary is fine to acknowledge ("calves are flagging — mobility tonight"); anything sharper, say "worth a clinician's eye".
- Recommend supplements, pharmaceuticals, or specific diets.
- Use generic motivational phrases ("great job!", "keep crushing it!").
- Override the rules engine if it has a relevant view — your job is debrief, not re-plan.
- Restate the obvious ("you ran 10 km in 50 minutes"). The runner can see the stats — comment on what they mean.

## Output
Just the reaction, plain text. No labels, no signature.
"""


def run_reaction_request_block(
    activity: dict,
    planned_workout: dict | None,
    diary: dict | None,
    feel_label: str | None = None,
    rpe_label: str | None = None,
    segments: list[dict] | None = None,
    active_block: dict | None = None,
) -> str:
    """Per-request context for a single completed activity reaction."""
    lines = ["COMPLETED RUN", "============="]
    lines.append(f"Date: {_with_dow(activity.get('start_time_local', ''))}")
    if activity.get("activity_name"):
        lines.append(f"Name: {activity['activity_name']}")
    if activity.get("location_name"):
        lines.append(f"Location: {activity['location_name']}")

    km = (activity.get("distance_m") or 0) / 1000.0
    dur_s = activity.get("duration_s") or 0
    pace = (dur_s / 60.0) / km if km > 0 else None
    lines.append(f"Distance: {km:.2f} km")
    if dur_s:
        m, s = divmod(int(dur_s), 60)
        h, m = divmod(m, 60)
        if h:
            lines.append(f"Duration: {h}h{m:02d}m{s:02d}s")
        else:
            lines.append(f"Duration: {m}m{s:02d}s")
    if pace is not None:
        pm = int(pace)
        ps = int(round((pace - pm) * 60))
        if ps == 60:
            pm += 1
            ps = 0
        lines.append(f"Avg pace: {pm}:{ps:02d}/km")

    if activity.get("avg_hr"):
        bits = [f"avg HR {activity['avg_hr']:.0f}"]
        if activity.get("max_hr"):
            bits.append(f"max {activity['max_hr']}")
        lines.append("HR: " + ", ".join(bits) + " bpm")
    # HR zones — only mention if at least 30% was outside Z2 to make it interesting.
    total_z = sum((activity.get(f"hr_zone_{i}_s") or 0) for i in range(1, 6))
    if total_z:
        z_lines = []
        for i in range(1, 6):
            secs = activity.get(f"hr_zone_{i}_s") or 0
            if secs:
                z_lines.append(f"Z{i} {int(secs/total_z*100)}%")
        if z_lines:
            lines.append("HR zones: " + ", ".join(z_lines))

    if activity.get("training_load"):
        lines.append(f"Training load: {activity['training_load']:.0f}")
    if activity.get("aerobic_te"):
        lines.append(f"Aerobic TE: {activity['aerobic_te']:.1f}")
    if activity.get("anaerobic_te") and activity["anaerobic_te"] > 0:
        lines.append(f"Anaerobic TE: {activity['anaerobic_te']:.1f}")
    if activity.get("elevation_gain_m"):
        lines.append(f"Elevation gain: {activity['elevation_gain_m']:.0f} m")
    if activity.get("avg_cadence_spm"):
        lines.append(f"Avg cadence: {activity['avg_cadence_spm']:.0f} spm")
    if activity.get("min_temperature_c") is not None and activity.get("max_temperature_c") is not None:
        lo, hi = activity["min_temperature_c"], activity["max_temperature_c"]
        lines.append(f"Temperature: {lo:.0f}–{hi:.0f}°C")

    # Fastest splits — show in seconds-per-km format.
    split_bits = []
    for label, key in [("1k", "fastest_1k_s"), ("5k", "fastest_5k_s"),
                       ("10k", "fastest_10k_s"), ("half", "fastest_half_s")]:
        v = activity.get(key)
        if v:
            m, s = divmod(int(v), 60)
            split_bits.append(f"{label} {m}:{s:02d}")
    if split_bits:
        lines.append("Fastest splits: " + ", ".join(split_bits))

    # Garmin's own feel + RPE if the runner set them.
    if feel_label:
        lines.append(f"Garmin perceived feel: {feel_label}")
    if rpe_label:
        lines.append(f"Garmin RPE: {rpe_label}")

    if planned_workout:
        lines.append("")
        lines.append("MATCHED AGAINST PLANNED WORKOUT")
        lines.append(f"  Title: {planned_workout.get('title', '?')}")
        lines.append(f"  Type:  {planned_workout.get('workout_type', '?')}")
        if planned_workout.get("target_distance_km"):
            lines.append(f"  Target distance: {planned_workout['target_distance_km']} km")
        if planned_workout.get("target_pace_s_per_km"):
            p = planned_workout["target_pace_s_per_km"]
            lines.append(f"  Target pace: {p // 60}:{p % 60:02d}/km")
        if planned_workout.get("target_duration_s"):
            d = planned_workout["target_duration_s"]
            m, s = divmod(int(d), 60)
            h, m = divmod(m, 60)
            lines.append(f"  Target duration: {h}h{m:02d}m" if h else f"  Target duration: {m}m{s:02d}s")
        if planned_workout.get("description"):
            lines.append(f"  Description: {planned_workout['description'][:200]}")
    else:
        lines.append("")
        lines.append("MATCHED AGAINST PLANNED WORKOUT: none (unplanned / discretionary run)")

    # Lap-segment breakdown — only emit when the watch tagged the run with
    # distinct phases (i.e. it ran a pushed structured workout). For free
    # runs every lap is "ACTIVE" so the segment list collapses to one block,
    # which is just the total-run average we already showed above.
    structured_segments = (
        [s for s in (segments or []) if s.get("intensity_type") and s["intensity_type"] != "ACTIVE"]
        if segments else []
    )
    if structured_segments and active_block:
        lines.append("")
        lines.append("ACTUAL EXECUTION BY PHASE")
        lines.append(
            "(The Avg pace above includes warmup + cooldown — judge the workout "
            "against the ACTIVE block only.)"
        )
        for seg in segments or []:
            d_km = (seg.get("distance_m") or 0) / 1000.0
            p = seg.get("avg_pace_s_per_km")
            pace_str = f"{p // 60}:{p % 60:02d}/km" if p else "—"
            hr = seg.get("avg_hr")
            hr_str = f", HR avg {hr:.0f}" if hr else ""
            mhr = seg.get("max_hr")
            mhr_str = f"/max {mhr:.0f}" if mhr else ""
            lines.append(
                f"  {seg['intensity_type']}: {d_km:.2f} km @ {pace_str}{hr_str}{mhr_str}"
            )
        # The headline comparison the coach should anchor on.
        ab_p = active_block.get("avg_pace_s_per_km")
        if ab_p and planned_workout and planned_workout.get("target_pace_s_per_km"):
            tgt = planned_workout["target_pace_s_per_km"]
            delta = ab_p - tgt
            sign = "+" if delta >= 0 else "-"
            lines.append(
                f"  → Active block pace {ab_p // 60}:{ab_p % 60:02d}/km vs target "
                f"{tgt // 60}:{tgt % 60:02d}/km ({sign}{abs(delta)}s/km)"
            )

    if diary and diary.get("body"):
        lines.append("")
        lines.append("RUNNER'S DIARY NOTE FOR THIS RUN")
        mood = diary.get("mood_label") or diary.get("mood")
        if mood:
            lines.append(f"  Mood: {mood}")
        lines.append(f"  \"{diary['body'][:400]}\"")

    lines.append("")
    lines.append(
        "Write the coach's reaction to this run, adapting the length to the "
        "complexity of the session (see the system prompt's adaptive-length rule)."
    )
    return "\n".join(lines)


WEEK_WRAPPED_SYSTEM_PROMPT = """\
You are the same professional running coach the runner sees on the dashboard banner. The runner has just completed every planned session of their current training week, and this line lands in a celebratory "This week, wrapped" block on the dashboard — big numbers above it, the runner's endorphins already flowing.

## Your job
Write ONE or TWO short sentences that make finishing the week feel earned. This is the emotional payoff, not a debrief — lean into the win.

## Anchor on what's special about THIS week
Pick the single most motivating thread from the data and make it land:
- A consistency streak ("that's five weeks straight now").
- The longest run of the block so far, or a chunky weekly volume.
- Every prescription hit ("and you hit the target on all of them").
- Progress banked toward the goal race (total plan km, weeks to go).
Don't list all of them — choose the one that hits hardest and say it well.

## You always
- Plain text only. No markdown, no headers, no quotes, no preamble, no signature.
- Second person ("you", "your"). First name occasionally, not every time.
- Numbers must be in the data you were given. Never invent.
- Warm, genuine, a little proud. Like a coach catching your eye after a good week.

## You never
- Use hollow hype ("great job!", "you crushed it!", "let's gooo"). Earn the warmth with a specific.
- Simply restate the numbers already shown above the line ("you ran 38 km"). Say what they *mean*.
- Coach the next week or prescribe anything — this is purely the wrap-up moment.
- Exceed two sentences.

## Output
Just the celebration line, plain text.
"""


def week_wrapped_request_block(stats: dict, first_name: str | None = None) -> str:
    """Per-request context for the week-complete celebration line. `stats` is
    a plan_service.week_stats() dict for a fully-completed week."""
    lines = [f"WEEK {stats['week_number']} — COMPLETE", "=" * 40]
    if first_name:
        lines.append(f"Runner: {first_name}")
    lines.append(f"Phase: {stats.get('week_phase', '?')}")
    lines.append(
        f"Sessions: {stats['sessions_done']} of {stats['sessions_planned']} done "
        f"(every planned session complete)"
    )

    hrs, rem = divmod(int(stats.get("moving_time_s") or 0), 3600)
    mins = rem // 60
    dur_str = f"{hrs}h{mins:02d}m" if hrs else f"{mins} min"
    line = f"This week: {stats['distance_km']:.1f} km · {dur_str}"
    if stats.get("load"):
        line += f" · training load {stats['load']:.0f}"
    if stats.get("climb_m"):
        line += f" · {stats['climb_m']:.0f} m climb"
    lines.append(line)

    if stats.get("longest_run_km"):
        lines.append(f"Longest run this week: {stats['longest_run_km']:.1f} km")
    if stats.get("targets_total"):
        lines.append(
            f"Prescription hits: {stats['targets_hit']} of {stats['targets_total']} "
            f"scored sessions landed on target"
        )
    if stats.get("streak_weeks", 0) >= 2:
        lines.append(
            f"Consistency streak: {stats['streak_weeks']} weeks in a row at "
            f"80%+ adherence (including this one)"
        )
    lines.append(
        f"Banked in the plan so far: {stats['plan_distance_km']:.0f} km "
        f"across {stats['plan_runs_done']} runs"
    )

    lines.append("")
    lines.append(
        "Write the one- or two-sentence celebration line for this completed "
        "week, following the system prompt. Pick the single most motivating "
        "thread and make it land."
    )
    return "\n".join(lines)


def request_block(
    today_iso: str,
    todays_workout: dict | None,
    recommendation: dict | None,
    readiness: dict | None,
    training_status: dict | None,
    weather: dict | None = None,
    completed_today: dict | None = None,
    completed_segments: list[dict] | None = None,
    completed_active_block: dict | None = None,
    todays_strength: dict | None = None,
) -> str:
    """The per-request context: today's planned workout + rules engine decision."""
    lines = ["TODAY", "====="]
    lines.append(f"Date: {_with_dow(today_iso)}")

    done = bool(completed_today)

    if todays_workout:
        lines.append("")
        lines.append(
            f"TODAY'S WORKOUT (already completed TODAY, {_with_dow(today_iso)} — "
            "comment on the run, do not prescribe)"
            if done else "PLANNED WORKOUT"
        )
        lines.append(f"  Title: {todays_workout.get('title')}")
        lines.append(f"  Type: {todays_workout.get('workout_type')}")
        if todays_workout.get("target_distance_km"):
            lines.append(f"  Target distance: {todays_workout['target_distance_km']} km")
        if todays_workout.get("target_pace_s_per_km"):
            pace_s = todays_workout["target_pace_s_per_km"]
            lines.append(f"  Target pace: {pace_s // 60}:{pace_s % 60:02d}/km")
        if todays_workout.get("description"):
            lines.append(f"  Notes: {todays_workout['description'][:240]}")
    else:
        lines.append("")
        lines.append("PLANNED WORKOUT: none scheduled today")

    if done:
        lines.append("")
        lines.append("ACTUAL RUN STATS")
        km = (completed_today.get("distance_m") or 0) / 1000.0
        dur_s = completed_today.get("duration_s") or 0
        lines.append(f"  Distance: {km:.2f} km")
        if dur_s:
            h, rem = divmod(int(dur_s), 3600)
            m, s = divmod(rem, 60)
            lines.append(f"  Duration: {h}h{m:02d}m{s:02d}s" if h else f"  Duration: {m}m{s:02d}s")
            if km > 0:
                pace = (dur_s / 60.0) / km
                pm = int(pace); ps = int(round((pace - pm) * 60))
                if ps == 60: pm += 1; ps = 0
                lines.append(f"  Avg pace: {pm}:{ps:02d}/km")
        if completed_today.get("avg_hr"):
            bits = [f"avg {completed_today['avg_hr']:.0f}"]
            if completed_today.get("max_hr"):
                bits.append(f"max {completed_today['max_hr']}")
            lines.append("  HR: " + ", ".join(bits) + " bpm")
        # HR zones, when interesting (>20% outside Z2).
        total_z = sum((completed_today.get(f"hr_zone_{i}_s") or 0) for i in range(1, 6))
        if total_z:
            z_bits = []
            for i in range(1, 6):
                secs = completed_today.get(f"hr_zone_{i}_s") or 0
                if secs:
                    z_bits.append(f"Z{i} {int(secs/total_z*100)}%")
            if z_bits:
                lines.append("  HR zones: " + ", ".join(z_bits))
        if completed_today.get("training_load"):
            lines.append(f"  Training load: {completed_today['training_load']:.0f}")
        if completed_today.get("start_time_local"):
            lines.append(f"  Started: {completed_today['start_time_local'][:16].replace('T', ' ')}")

        # Phase breakdown for structured workouts (tempo / intervals). Same
        # reasoning as run_reaction_request_block: when a workout has warmup +
        # active + cooldown phases, judging adherence by the total-run Avg
        # pace is misleading — the warmup/cooldown drag it well below the
        # active block. Surface a phase-by-phase view and an explicit active
        # vs target comparison so the coach can anchor on the right number.
        structured_segments = (
            [s for s in (completed_segments or [])
             if s.get("intensity_type") and s["intensity_type"] != "ACTIVE"]
            if completed_segments else []
        )
        if structured_segments and completed_active_block:
            lines.append("")
            lines.append("ACTUAL EXECUTION BY PHASE")
            lines.append(
                "  (Avg pace above includes warmup + cooldown — for adherence, "
                "compare target against the ACTIVE block only.)"
            )
            for seg in completed_segments or []:
                d_km = (seg.get("distance_m") or 0) / 1000.0
                p = seg.get("avg_pace_s_per_km")
                pace_str = f"{p // 60}:{p % 60:02d}/km" if p else "—"
                hr = seg.get("avg_hr")
                hr_str = f", HR avg {hr:.0f}" if hr else ""
                mhr = seg.get("max_hr")
                mhr_str = f"/max {mhr:.0f}" if mhr else ""
                lines.append(
                    f"  {seg['intensity_type']}: {d_km:.2f} km @ {pace_str}{hr_str}{mhr_str}"
                )
            ab_p = completed_active_block.get("avg_pace_s_per_km")
            if ab_p and todays_workout and todays_workout.get("target_pace_s_per_km"):
                tgt = todays_workout["target_pace_s_per_km"]
                delta = ab_p - tgt
                sign = "+" if delta >= 0 else "-"
                lines.append(
                    f"  → Active block pace {ab_p // 60}:{ab_p % 60:02d}/km vs target "
                    f"{tgt // 60}:{tgt % 60:02d}/km ({sign}{abs(delta)}s/km)"
                )

    if todays_strength:
        st = todays_strength
        st_done = bool(st.get("completed_at"))
        lines.append("")
        lines.append(
            "OPTIONAL STRENGTH SESSION TODAY (rest day for running — bodyweight work alongside it)"
        )
        lines.append(f"  Title: {st.get('title')}")
        lines.append(
            f"  Planned duration: {st.get('duration_min_lo')}–{st.get('duration_min_hi')} min"
        )
        if st_done:
            note = "  Status: DONE"
            if st.get("actual_duration_s"):
                m = int(st["actual_duration_s"]) // 60
                note += f" ({m} min"
                if st.get("actual_avg_hr"):
                    note += f", avg HR {st['actual_avg_hr']}"
                note += ")"
            lines.append(note + " — acknowledge it briefly if natural.")
        else:
            lines.append("  Status: scheduled, not yet done.")

    if readiness:
        lines.append("")
        lines.append(
            f"Readiness: {readiness.get('score', '?')}/100 "
            f"({readiness.get('level', '?')})"
        )
        if readiness.get("feedback_short"):
            lines.append(f"  Garmin feedback: {readiness['feedback_short'].replace('_', ' ').title()}")
    if training_status and training_status.get("acwr_ratio") is not None:
        # Attributed to Garmin on purpose: the rules engine applies a stricter
        # threshold (caution from 1.30), so its own wording can read "drifting
        # high" on a ratio Garmin still labels OPTIMAL. Naming the source keeps
        # that from looking like the data contradicting itself.
        lines.append(
            f"ACWR: {training_status['acwr_ratio']:.2f} "
            f"(Garmin status: {training_status.get('acwr_status', '?')})"
        )

    if weather:
        lines.append("")
        lines.append("WEATHER TODAY")
        if weather.get("display_name"):
            lines.append(f"  Location: {weather['display_name']}")
        bits = []
        if weather.get("current_temp_c") is not None:
            bits.append(f"now {weather['current_temp_c']:.0f}°C")
        if weather.get("high_c") is not None and weather.get("low_c") is not None:
            bits.append(f"H {weather['high_c']:.0f}° / L {weather['low_c']:.0f}°")
        if weather.get("weather_text") and weather["weather_text"] != "—":
            bits.append(weather["weather_text"].lower())
        if weather.get("wind_kmh") is not None:
            bits.append(f"wind {weather['wind_kmh']:.0f} km/h")
        if weather.get("precip_prob_pct") is not None:
            bits.append(f"{weather['precip_prob_pct']}% chance of rain")
        if bits:
            lines.append("  " + ", ".join(bits))
        bw = weather.get("best_window")
        if bw:
            bw_bits = [f"{bw['start']}–{bw['end']}"]
            if bw.get("avg_temp_c") is not None:
                bw_bits.append(f"{bw['avg_temp_c']:.0f}°C")
            if bw.get("weather_text") and bw["weather_text"] != "—":
                bw_bits.append(bw["weather_text"].lower())
            if bw.get("max_precip_pct") is not None:
                bw_bits.append(f"{bw['max_precip_pct']}% rain")
            if bw.get("avg_wind_kmh") is not None:
                bw_bits.append(f"{bw['avg_wind_kmh']:.0f} km/h wind")
            lines.append(
                "  Best window today (runnability score "
                f"{bw['score']}/100): " + ", ".join(bw_bits)
            )

    status = (recommendation or {}).get("status")
    reasons = [r for r in ((recommendation or {}).get("reasons") or []) if r]
    if status == "done":
        # Post-session state, not a prescription. Spelled out because the
        # numbers here (low readiness, spiked ACWR) look exactly like a
        # "back off today" signal — and read that way they contradict the
        # completed-workout block above, which used to push the coach into
        # relocating the run to an earlier day to make both true.
        lines.append("")
        lines.append("RULES ENGINE DECISION")
        lines.append("  Status: DONE — today's session is already in the log.")
        lines.append(f"  Headline (rules-based): {recommendation.get('headline', '')}")
        if reasons:
            lines.append("  State right now (measured AFTER the run): " + "; ".join(reasons))
        lines.append(
            "  There is nothing left to prescribe for today. These readings "
            "post-date the session — they describe what it cost, not a reason "
            "to have skipped or swapped it."
        )
    elif recommendation:
        lines.append("")
        lines.append("RULES ENGINE DECISION")
        lines.append(f"  Status: {(status or '?').upper()}")
        lines.append(f"  Headline (rules-based): {recommendation.get('headline', '')}")
        if reasons:
            lines.append("  Signals: " + "; ".join(reasons))
        if recommendation.get("suggestion"):
            lines.append(f"  Suggested action: {recommendation['suggestion']}")
    else:
        lines.append("")
        lines.append(
            "RULES ENGINE DECISION: none today "
            + ("(nothing left to decide)" if todays_workout else "(no workout scheduled)")
        )

    lines.append("")
    lines.append(
        "Write today's coach line for the dashboard banner. 1–2 sentences, "
        "personalized to this runner and grounded in the data above. Pick what's "
        "most relevant today — rules-engine decision if there is one, otherwise "
        "recovery state, recent training pattern, a diary note, or what's coming up."
    )
    return "\n".join(lines)
