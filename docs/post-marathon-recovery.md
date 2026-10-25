# Post-marathon recovery plan — design brief

> **Status:** **ready to build** — body-map shipped (the Day 1-2 triage dependency is satisfied) and sleep+HRV is parked because the runner doesn't wear the watch overnight, so the recovery-vitals strip (HRV / RHR / sleep / body-battery trends during the 28 days) becomes a **v1.1 follow-up** rather than a v1 dependency. The schedule + Day 1-2 body-map triage + LLM coach voice pivot + nutrition milestones + Day 28 transition all ship in v1. Roadmap entry: [roadmap.md](roadmap.md) → *Next up · #1*. Source grounding: internal grounding notes. Not in [docs/README.md](README.md)'s "Documented features" table — that's for shipped features.

## What the feature is

The day after the runner completes their A-race marathon, the app auto-generates a 28-day structured recovery plan that picks up where the marathon plan ended:

- **Week 1** — rest + walks only, no running
- **Week 2** — short easy jogs gated on soreness, walks on off-days
- **Weeks 3-4** — gradual mileage ramp back to baseline, no quality work

Reuses the existing `plan_workouts` schema (`workout_type='rest'` / `'easy'`, plus a new `'walk'` type — see §4). The countdown card already flips through phases (`tomorrow → today → recap`); recap extends from 48h to the full 28-day recovery view ("RECOVERY · DAY 5 OF 28"). The LLM coach voice naturally pivots once the race is in the past.

Real implementation lift is the **plan-state transition** (auto-create on race-day completion, link to the just-finished plan, switch the active plan pointer), not the per-day content — that's prescribed in the grounding doc.

---

## 1. Trigger / activation

### Default: auto-fire on race-day completion

The moment we ingest a Garmin activity that matches the A-race day + is reasonably close to marathon distance (≥ ~38km, ≥ ~3h), the system:

1. Flips the marathon plan to `archived` (`active=0`)
2. Generates the 28-day recovery plan
3. Sets the recovery plan as the new `active=1` plan
4. Links recovery → marathon via a new `plans.recovery_of_plan_id` FK
5. Same `RACE DAY → RECAP` transition the countdown card already does; the recap phase now extends to 28 days

### Three corner cases

- **DNS (did-not-start)** — no race activity ever appears. Marathon plan just ends; no recovery plan auto-fires. Manual creation is the escape hatch.
- **DNF / shortened race** — activity exists but well under marathon distance (e.g. 25km in 2:45). Still fire. Body still needs recovery. Either keep the same 28-day window (runner fast-forwards Week 1 if they recover faster) or scale by `actual_distance_m / 42195` — keep the simpler "same 28 days, fast-forward allowed" for v1.
- **Runner already created the next plan** (rare; mid-marathon-block they queued a *Spring base build*). Detect overlap on auto-fire; ask: "you have *Spring base build* queued — replace it with recovery, or stack recovery in front of it?"

### Manual creation path (always available)

- Settings → "Create recovery plan" button
- Archived marathon plan's detail page → "Generate recovery from this race"

Handles: runners who ran a marathon outside the app · runners who toggled auto-fire off · runners who DNF'd and disabled auto.

### Opt-out toggle

Plan-settings field on the marathon plan: `recovery_plan_after_race: true|false`, default true. Surfaces as a checkbox on plan creation ("Auto-build a 28-day recovery plan after race day") and on plan-edit. Easy to disable for the beach-holiday-after-the-race case.

---

## 2. Where it lands — UI surfaces

The recovery plan is a **plan**, not a banner. Five touchpoints:

| Surface | What changes |
|---|---|
| **Countdown card** | Flips from `RACE RECAP (48h)` to `RECOVERY · DAY 5 OF 28` for the full 28 days. Same card slot, calmer accent color (soft green, not race red). |
| **Today's flagship hero** | Shows the day's prescription. Day 1: "Walk 20 min · hydrate · eat carbs + protein within 3h." Day 12: "Easy 4km · keep HR < 140." Same hero shape, prescription describes a walk or rest. |
| **Plan detail page** (`/plans/<id>`) | 28-day schedule rendered like any other plan. Week 1 = mostly rest + walk tiles. Week 4 = building easy runs. |
| **Calendar view** | Recovery days get a new soft-green stripe (or muted reuse of `easy`-green) — distinguishable from the marathon plan above. |
| **LLM coach voice** | System prompt picks up `plan_kind = 'recovery'`; cached profile gets a "you finished the {race} on {date} — coaching focus is recovery, not training stimulus" line. No readiness gating; no ACWR; empathy + the day's rationale. |

---

## 3. The "already active plan" problem

Mostly already solved by the existing plan-state model — marathon plan's `target_date == race_date`; on the day after race day, it flips to `active=0` regardless. The new step: on that flip, generate the recovery plan and set it `active=1`, linked back to the just-finished marathon plan via `plans.recovery_of_plan_id`. Single transaction.

Tricky case: marathon plan re-activation (runner clicks "make active" on the archived plan to look at it). UI should refuse, or warn that doing so deactivates the recovery plan. Simplest fix: don't expose re-activation of archived race-bracket plans.

---

## 4. Per-day content

### Day-by-day skeleton

| Days | Prescription | Workout type |
|---|---|---|
| **1** (race day +0) | Rest. Hydration + carb + protein milestones in the day-tile note. | `rest` (with `recovery_focus='nutrition'`) |
| **2-3** | Optional 20-min walk. Sleep + mobility. | `rest` or new `walk` type |
| **4-7** | Walks daily 30-45 min. Day 7 optional "test jog" 15-20 min very easy if soreness gone. | `walk` + 1× `easy` (gated) |
| **Week 2** | 3 easy runs, 4-5km, every other day. Walks on off days. No quality. | `easy` + `walk` |
| **Week 3** | 4 easy runs ramping 5km → 8km. Optional drills late-week. | `easy` + maybe strides Friday |
| **Week 4** | Return to ~75% of pre-plan baseline weekly km. Last day: short tempo to test legs (optional). | `easy` + 1× optional `tempo` |

### Baseline-km source

Use the marathon plan's **average non-taper weekly km** (Wks 4-12 of the just-finished plan) as the Week-4 target. Falls back to runner's pre-plan average if missing.

### Strength sessions during recovery

Yes — rotation continues, but on Days 1-7 only the *Recovery & Mobility* session is allowed (rotation gets overridden). Week 2+ resumes normal rotation. The existing recovery-after-quality override generalizes naturally.

### New `walk` workout type — recommended

- Reuses `rest`'s "no Garmin push" behaviour
- Renders differently on day-tiles ("WALK 30:00") and counts toward an adherence pill
- Alternative: reuse `rest` + render a note. Cleaner if we add it, simpler if we don't.
- **Decision: add `walk` as a real type.** Recovery plans will look like all-rest otherwise; runner will feel like they're being told to do nothing for 4 weeks.

---

## 5. Explanations

The science from the grounding doc is the *reason* the runner trusts the schedule. Three layers:

### Layer A — One-time recovery primer

A banner the first time the runner opens the recovery plan: *"Why this plan looks the way it does"* → expandable card with the carbs/kg, peak DOMS, glycogen replenishment timeline, etc. Dismissible. Stored in `app_state` so it doesn't reappear.

### Layer B — Per-day rationale

Short contextual line in the day-tile / flagship.

- Day 2 → *"Quads + calves are at peak soreness today. Movement helps; intensity hurts."*
- Day 12 → *"First real run since the race. Conversational pace only — your aerobic system is back, your tendons and connective tissue still aren't."*

Static strings in the day's prescription, LLM coach voice overlays where it adds value.

### Layer C — LLM coach voice continuity

Draws on the runner's diary entries (post-race emotional dump, "knee felt weird on day 5") to keep the prescription honest. Lighter prompt than training-block coaching — no readiness gating, no ACWR; just empathy + the day's rationale.

### Per-week summary

On the plan-detail page: *"Week 1 — Rest & repair"*, *"Week 2 — Reintroduce running"*, *"Week 3 — Gradual ramp"*, *"Week 4 — Building back to baseline"*.

---

## 6. Open questions to pin before / during build

- **Generalize beyond marathon?** Should this fire after halves and 15k races too, with scaled windows (HM = 14d, 15k = 7-10d)? Lean: **marathon-only for v1** — the science gap is biggest there and we have grounding for it. Halves later.
- **Mental-recovery / post-race blues** — grounding doc mentions it. Do we surface it (diary prompt around Day 4-7: *"how are you feeling about running this week?"*) or keep it implicit?
- **Sub-distance variants** — does a 5h hobby jogger need the same plan as a 2:55 competitive finisher? Could be a single dial: "intensity of race" (PR effort vs cruising), set on plan creation or auto-derived from `execution_score` / pace-vs-target on the race-day activity. Simpler: one plan, runners can fast-forward Week 1 if they recover faster.
- **Strength-session interaction** — confirmed: the runner explicitly toggled strength on the marathon plan; carry to recovery plan automatically. Same runner, same preferences.

---

## 7. Wellbeing review — additions to bake in before build

Added 2026-06-14 after a critical pass with the lens *"runner health & wellbeing is the top priority."* The §1-6 brief gets us *a schedule;* these additions are what make it *a coach.* All to be folded into the final implementation, none to be skipped.

### Tier 1 — health gaps (must-have for v1)

1. **Body check-in / injury triage (Day 1-2)** — marathons commonly leave blisters, hot spots, calf strains, IT band issues, lower-back tweaks. None of those are normal-soreness; they're real injuries that need different handling. We need a Day 1-2 prompt: *"How's your body? Anything sharper than just sore?"* with the body-map (#1) as the input surface. If anything reads sharp / moderate+, we extend rest, suppress the Wk2 jog, suggest a physio. **Hard dependency on body-map feature.**

2. **Sleep + HRV + RHR monitoring during the 28 days** — we already sync HRV, sleep duration, resting HR, body battery, training readiness. None surfaced during recovery in the current brief. This is *exactly* the period where these signals matter most — sustained HRV depression past Day 10 = overtraining / illness; RHR +10bpm above baseline = the immune-system alarm the grounding doc references. Add a *recovery vitals strip* on the dashboard (HRV trend · sleep last night · RHR delta · body battery) + a rule: *"these are out of range — we're holding Wk2's first run back another 2 days."* **Hard dependency on sleep+HRV feature (#2).**

3. **Soreness self-report scale, not a vague gate** — §4 says Wk2 first run is "gated on soreness" but has no input mechanism. The body-map (#1) provides it: severity slider per affected region, with the Day 7 gate keyed off worst-region severity. Without a real gate input, the rule is decorative.

4. **Mental wellbeing surfaced, not implicit** — §6 leaves post-race blues as an open question; flip it to *yes, surface.* Day 4-7 is the peak window — well-documented psychological phenomenon, not optional. Concrete shape: a diary prompt on Day 5 and Day 9 (*"how are you feeling about running this week — flat, restless, fine, motivated?"*) + LLM coach voice picks up the response and either normalises it or gently steers. Cheap to add, high wellbeing payoff.

5. **Hydration milestones alongside carbs/protein** — §4 Day 1 has carbs + protein, no hydration. A marathon loses 2-4kg of water; glycogen replenishment requires water with the carbs. Day 1 note needs a third line. Days 2-3 too — sustained rehydration matters more than people think.

### Tier 2 — guidance gaps (must-have for v1)

6. **Guided race recap during the 48h recap phase** — the runner just ran their A-race, the most reflection-worthy moment in their training year. A short guided form: *finish time vs goal · what worked · what didn't · biggest takeaway · would-you-train-the-same-way.* Saved as a special diary entry; surfaceable when they create their next plan. Closes the loop on the whole training block.

7. **Day 28 transition — what comes next** — §1-6 doesn't address this. Day 29 dawns with no active plan. The runner should be asked on ~Day 25: *"recovery is wrapping up — pick a next chapter: maintenance / new race / extended break."* Otherwise they fall off the app or impulsively restart hard training.

8. **Pacing prescription that's actually achievable** — §4 says "HR < 140" for Wk2 easy runs. For a marathon-fit runner, that HR cap is often unreachable at any running pace. Replace with perceived-effort language (*"conversational; you should be able to sing a song"*) or VDOT-derived pace + 60s/km. Not an HR ceiling that frustrates the runner into stopping the watch.

### Tier 3 — nice-to-have (v1.1 OK)

9. **Adherence reframe** — during training, ✓ = ran the workout. During recovery, ✓ should = *respected the rest.* A runner who runs 12km on Day 5 when the plan says "rest" should get a soft warning, not a green check. Tiny logic flip in the adherence renderer.

10. **Cross-training options** — grounding doc mentions swimming + easy cycling as Wk1-2 options. Right now we only prescribe walks. Allow a swim or bike instead — coach line ("if a walk feels too sedentary, a 20-min easy swim is fine") + counts toward the day's check.

11. **Stats wrap / celebration** — cumulative km in the training block, longest week, biggest single run, PRs broken. Day 1 of recovery is the perfect surface — *"you ran 612km in 16 weeks to get here. Take this in."* The marathon achievement deserves explicit celebration in-app, not just by Garmin.

12. **Fresh-shoe reminder for Wk2** — marathon shoes are beat. One-liner *"swap to a fresh easy shoe for these first runs back."* Tiny but real injury-prevention.

### Updated v1 dependency chain

The implementation order is now:
1. Body-map (#1 on roadmap) ships
2. Sleep+HRV signal (#2 on roadmap) ships
3. Resume this brief: bake Tier-1 + Tier-2 gaps into §1-6, then build

Without #1 and #2, the recovery plan is a static schedule that ignores how the runner is actually responding. Worth the wait.

---

## v1 minimum recommendation

> **Superseded.** The original v1 minimum below captures the *schedule* shape only. The §7 wellbeing review adds the *coach* layer — body-map triage, recovery vitals, soreness gate, mental-wellbeing prompts, hydration, race recap, Day 28 transition, achievable pacing. Both are required for v1. Treat the list below as the schedule-shape subset; add §7 Tier 1+2 on top.

The schedule-shape subset:

- **Marathon-only auto-fire** with opt-out checkbox at plan creation
- **Manual creation path** from the archived marathon's detail page
- **Four UI surfaces**: countdown card, flagship, plan-detail, calendar — skip the explicit primer banner for v1 and rely on per-day rationale + LLM voice
- **Build the `walk` workout type**
- **Ship the explanation primer (Layer A) as v1.1**

---

## Cross-references

- Grounding science: internal grounding notes
- Roadmap entry: [roadmap.md](roadmap.md) → *Next up — committed · #1*
- Related: countdown card recap-phase logic ([race-day-countdown.md](race-day-countdown.md)) — recovery view is its 28-day extension

---

*Design brief written: 2026-06-14. Update once implementation lands.*
