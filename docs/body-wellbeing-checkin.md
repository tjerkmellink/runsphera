# Body — wellbeing check-in (design brief)

> **Status:** pre-implementation design brief. Currently roadmap *Next up · #1* ([roadmap.md](roadmap.md)). Foundational input mechanism that several downstream features depend on (post-marathon Day 1-2 triage, daily coach prescription softening, strength-session exercise avoidance, plan re-flex on escalation). Frozen reference for the actual implementation. Not in [docs/README.md](README.md)'s *Documented features* table yet — that's for shipped features.

## What the feature is

A dedicated *Body* tab in the app where the runner taps an interactive full-body SVG (front + back views, side-by-side on desktop) to log how their body actually feels. Each entry is a structured record — region · side · issue type · severity 1-10 · optional anatomical structure name · optional note. Active issues persist as a daily-updatable list with a trend curve; resolved issues feed a history timeline and a trouble-zone heatmap painted onto the body.

The runner does this in roughly 15 seconds per check-in (tap region → pick a quick-tap severity chip → done). The coach reads the active-issue state on every dashboard render and threads it into the daily prescription, the LLM voice, and downstream gates (e.g. recovery plan's Day 7 jog gate). The runner's vague *"my calf has been weird lately"* becomes the app's structured *"left gastrocnemius — tight — 4/10 for 6 days, trend slight worsening"* — same fact, but actionable.

Foundational because no current input surface captures *body state.* Diary captures vibes and free text but doesn't aggregate. Garmin gives us readiness scores and ACWR ratios but knows nothing about a niggle. Without this feature, every wellbeing-driven prescription change in the app is guessing.

## 1. Tab + nav placement

- **Name:** *Body*
- **Placement:** in the main nav between *Calendar* and *Diary*. Daily-glance surface; should be reachable in one click from the dashboard.
- **Icon (suggestion):** simple human-silhouette glyph in the nav. Stays neutral; doesn't imply "broken" or "checkup".

## 2. Region model

Full-body SVG, front + back rendered **side-by-side on desktop**, **toggle on mobile <600px** (front by default; *"view back"* flips it). Each region is a clickable `<path>` with an ID. Hover/tap highlights the region; click opens the entry panel.

### The 27-region set

**Front view (14 regions):**

| Region | L/R | Notes |
|---|---|---|
| Shoulder | L · R | Catches strength/yoga shoulder, not strictly running |
| Hip flexor | L · R | Tight-hip-flexor is endemic in desk-bound runners |
| Quad | L · R | DOMS hotspot post-long-run |
| Knee | L · R | One region; structure-name field captures medial / lateral / patellar etc. |
| Shin | L · R | Stress-reaction / splints territory |
| Ankle | L · R | Anterior — pairs with achilles on back |
| Foot | L · R | Top of foot — pairs with heel on back |

**Back view (13 regions):**

| Region | L/R | Notes |
|---|---|---|
| Neck | midline | Single region |
| Upper back | midline | Covers traps + rhomboids + erectors |
| Lower back | midline | Covers lumbar + SI joint + QL |
| Glute | L · R | Including piriformis (captured via structure name) |
| Hamstring | L · R | DOMS hotspot post-long-run |
| Calf | L · R | Most-common running niggle zone |
| Achilles | L · R | Distinct from calf — tendinopathy has its own arc |
| Heel | L · R | Plantar fascia territory; bottom-of-foot |

**Total: 27 clickable regions.** L/R is encoded as separate clickable regions on the diagram, not a panel field — the runner taps the actual side they mean, no extra step.

Muscle-level anatomy (e.g. *"medial gastrocnemius"* as its own region) is **parked for v2**. The structure-name field on each entry gives finer detail without exploding the diagram.

## 3. Issue model

### Issue types (six)

| Type | Description | Typical severity range |
|---|---|---|
| **Soreness** | General DOMS, normal post-run feel | 1-5 |
| **Tight / stiff** | Range of motion compromised | 2-6 |
| **Sharp pain** | Acute pain on specific movement | 4-10 |
| **Dull ache** | Chronic, lingering, bothersome | 2-7 |
| **Numb / tingling** | Neural symptoms — concerning | 3-9 |
| **Known injury** | Recurring named issue (ITB, PF, etc.) | varies |

### Severity entry

- **Quick-tap chips** above the slider: *Mild* (= 2) · *Moderate* (= 5) · *Severe* (= 8). One click for the common case.
- **1-10 slider** below the chips. For exact value or daily tracking nuance.
- **Severity color mapping** (used everywhere severity is shown):
  - 1-3: muted green (mild, monitor)
  - 4-6: amber (managing, modify training)
  - 7-10: red (serious, rest + probable physio referral)

### Structure name (optional)

Autocomplete from a per-region library (below), with freeform override. Keeps data queryable while not locking the runner out of describing their actual experience.

### Note (optional)

Free-text textarea. *"Started after the hill repeats Thursday."*

### Per-region structure library

| Region | Library |
|---|---|
| Foot | Plantar fascia, Metatarsals, Arch, Big toe, Forefoot |
| Heel | Heel pad, Heel spur, Calcaneus |
| Ankle | Peroneal, Posterior tib, Anterior compartment, Deltoid lig, ATFL |
| Achilles | Achilles tendon, Insertion, Retrocalcaneal bursa |
| Shin | Tibialis anterior, Posterior tib, Bone (stress) |
| Calf | Gastrocnemius, Soleus |
| Knee | IT band, Patellar tendon, Meniscus, MCL, LCL, Patella, Quad tendon |
| Quad | Rectus femoris, Vastus medialis, Vastus lateralis, Quad tendon |
| Hamstring | Biceps femoris, Semitendinosus, Hamstring origin |
| Hip flexor | Iliopsoas, Rectus femoris, TFL, Sartorius |
| Glute | Glute med, Glute max, Piriformis |
| Lower back | Lumbar erectors, SI joint, QL |
| Upper back | Trap, Rhomboid, Erectors |
| Neck | Cervical, SCM |
| Shoulder | AC joint, Rotator cuff, Deltoid |

Library grows over time. Start with this; add as we discover gaps.

## 4. Entry lifecycle

```
[Logged] → [Active, updates allowed] → [Resolved]
                       ↓
              10d idle → nudge: "Still there?"
                       ↓
              14d idle → auto-archive (with note)
                       ↓
              Severity = 0 for 2 days → soft prompt to close
```

### States

- **Active**: open issue, severity > 0, no resolution date. Renders on the Body tab's *Active issues* list and on the dashboard widget.
- **Resolved**: explicitly closed by the runner (or auto-archived). Persists in history + the heatmap aggregate. Can be un-resolved if a runner accidentally closed it.

### Nudge mechanics

- At **day 10** with no update: app shows the issue with a *"Still bothering you?"* prompt. One-tap *"Resolved"* or *"Still active — new severity: __"*.
- At **day 14** with no update and no nudge response: auto-archive as *resolved (auto: no recent updates)* with a timestamp + flag. Runner can un-archive if it was a false close.
- **Severity hits 0 for 2 consecutive days**: soft prompt *"Looks like this cleared up — close it?"* One-tap close.

### Daily severity updates

Each active issue card on the Body tab has a slider. Tap the new severity → recorded with timestamp. The series of severity points per issue drives the trend curve (improving / steady / worsening shown on the active-issue card).

## 5. UI surfaces

### A. Body tab (the main surface)

Five sub-surfaces inside the tab:

1. **Body diagram** (top) — front + back side-by-side desktop, toggle on mobile. Inactive regions are subtle outline; active regions are filled with severity-mapped color. Clicking opens the entry panel (or, if there's already an active issue for that region+side, opens the update sheet).

2. **Active issues list** — cards under the diagram. Each shows: region + side, issue type, current severity (color + number), days open, severity trend mini-curve, quick-update slider, mark-resolved button. Sorted by severity descending, then days-open descending.

3. **History timeline** — toggle view (default: Active). Every entry in reverse chronological order, with a small body-icon showing the region.

4. **Trouble-zone heatmap** — second toggle view. Aggregate severity over rolling 90/180/365 days painted onto the body. Catches the runner who's had four right-calf flare-ups this year and hasn't connected the dots.

5. **Onboarding zero-state** — first-open of the tab shows the diagram + an explainer banner: *"Tap any area you'd like to track. The coach will use this to keep your training honest with how your body actually feels."* Plus a default *"I'm all good right now"* button that creates a clean-slate timestamp (logged as a "body clear" event — useful negative-case data).

### B. Dashboard widget

Small *Body status* card on the dashboard, placed **below or aside of *Today's note***. Shows:

- Top 2-3 active issues with severity dots + region label, OR
- *"All clear ✓"* if no active issues, with a tap-to-log-something link.

One-click into the Body tab.

### C. Daily check-in prompt

Once per day, a small banner on the dashboard: *"Anything new today?"* with *"All good"* or *"Log something"* buttons. *All good* logs a zero-state timestamp ("12 consecutive clear days" is itself valuable signal). Skip if any issue was updated in the last 12 hours.

### D. Run-detail modal integration (Garmin RPE auto-suggest)

The run-detail modal already shows Garmin's per-run *feel* (1-5) and *RPE*. If either is bad (RPE ≥ 8 on an easy run, or feel = *Very strong* but pace was slow), prompt: *"That felt harder than expected — anything bothering you?"* with a one-click open-body-map button.

### E. Visual style

- Minimalist editorial silhouette — gender-neutral, line-art, neither clinical nor cartoonish.
- Matches the *Tempo* theme's calm + accent palette.
- Inactive regions: subtle outline only.
- Active regions: filled with severity-mapped color.
- Heatmap mode: regions filled with intensity proportional to aggregate severity over the selected window.
- Start v1 with an open-source SVG body (Wikimedia / heroicons-style); redraw bespoke later if visual cohesion needs it.

## 6. LLM coach integration

**Default ON; Settings opt-out toggle (*"Include body check-in data in coach context"*).**

What gets sent to the LLM, joined to the cached profile block:

```
ACTIVE BODY ISSUES (treat as ground truth, runner-reported):
- Left calf · soreness · 4/10 · 6 days · trend slight worsening · note "started after Thursday's hills"
- Right knee · tight/stiff · 3/10 · 2 days · trend steady · IT band
RECENTLY RESOLVED (last 30 days):
- Right achilles · dull ache · resolved 12 days ago (manual)
RECENT BODY HEATMAP (top zones):
- Right calf — 4 flare-ups in last 90 days
- Lower back — 3 flare-ups in last 180 days
```

How this lands in coach behavior:

- **Daily prescription**: any active issue ≥ 5/10 → soften today's session (tempo → easy, long → shorter easy); ≥ 7/10 → push toward rest + suggest physio referral.
- **Run-detail reaction**: coach can name the issue specifically *("right knee was at 5/10 yesterday — how did it feel during this tempo?")*.
- **Weekly recap**: if a chronic issue persisted through the week, the recap mentions it.
- **Plan re-flex**: a worsening trend triggers a soft prescription shift before fatigue evidence accumulates in ACWR.

### Privacy posture

- Data lives in local SQLite. Leaves the machine only through LLM API calls (Anthropic / OpenAI / Gemini, per the runner's chosen provider), where the provider's data-retention policy applies.
- The Settings toggle drops the body section from the cached profile prompt. Body tab continues to work; the LLM just doesn't know about issues.

## 7. Data model (sketch)

Two tables, one optional:

```sql
-- One row per logged issue
CREATE TABLE body_issues (
    id INTEGER PRIMARY KEY,
    region TEXT NOT NULL,              -- canonical region key
    side TEXT NOT NULL,                -- 'left' | 'right' | 'midline'
    issue_type TEXT NOT NULL,          -- one of the 6 types
    structure_name TEXT,               -- optional (autocomplete or freeform)
    note TEXT,                         -- optional free text
    created_at TEXT NOT NULL,
    resolved_at TEXT,                  -- NULL while active
    resolved_reason TEXT,              -- 'manual' | 'auto_idle' | 'severity_zero' | NULL
    last_nudge_at TEXT
);
CREATE INDEX idx_body_issues_active ON body_issues(resolved_at) WHERE resolved_at IS NULL;
CREATE INDEX idx_body_issues_region ON body_issues(region, side);

-- Severity audit log — one row per severity report (initial + each update)
CREATE TABLE body_severity_log (
    id INTEGER PRIMARY KEY,
    issue_id INTEGER NOT NULL REFERENCES body_issues(id) ON DELETE CASCADE,
    severity INTEGER NOT NULL,         -- 1-10
    recorded_at TEXT NOT NULL
);
CREATE INDEX idx_body_severity_issue ON body_severity_log(issue_id, recorded_at);

-- Optional: "all clear" timestamps for the daily-check-in zero-state
CREATE TABLE body_clear_logs (
    id INTEGER PRIMARY KEY,
    recorded_at TEXT NOT NULL
);
```

Region keys are stable canonical strings: `foot` / `heel` / `ankle` / `achilles` / `shin` / `calf` / `knee` / `quad` / `hamstring` / `hip_flexor` / `glute` / `lower_back` / `upper_back` / `neck` / `shoulder`.

## 8. Routes

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/body` | Renders the Body tab (diagram + active issues + onboarding/history toggle) |
| `POST` | `/body/issues` | Create a new issue (region, side, type, severity, optional structure_name, optional note) |
| `PATCH` | `/body/issues/{id}` | Update severity / note / type / structure_name |
| `POST` | `/body/issues/{id}/resolve` | Mark resolved (with optional reason) |
| `POST` | `/body/issues/{id}/unresolve` | Reopen a resolved/auto-archived issue |
| `POST` | `/body/clear` | Log an "all clear" check-in |
| `GET` | `/body/region/{region}/{side}` | Render the entry panel partial (HTMX target) |
| `GET` | `/body/heatmap?window=90` | Heatmap data — aggregated severities per region |

All HTMX-driven; no full-page reloads.

## 9. v1 minimum recommendation

**Ship in v1:**

- *Body* tab in nav
- Full-body SVG (front + back side-by-side desktop, toggle mobile) — 27 regions
- Entry panel with type + side + severity (quick-tap chips + slider) + structure-name autocomplete + note
- Active issues list with daily-update sliders + trend mini-curves
- History timeline + trouble-zone heatmap
- Manual mark-resolved + 10/14-day nudge & auto-archive logic
- Dashboard *Body status* widget
- LLM context integration + Settings opt-out toggle
- Onboarding zero-state + daily check-in prompt
- Garmin RPE / feel auto-suggest in run-detail modal

**Defer to v1.1:**

- Strength-session exercise avoidance (needs exercise → region mapping table)
- Plan re-flex on body-issue escalation
- Muscle-level anatomy view (the *"see the actual muscle, point at it"* upgrade — would let the LLM be more specific about which structure to load/unload)
- Bilateral asymmetry detection (*"right calf flares up every 4-5 weeks; left calf hasn't in a year — worth a gait check"*)

## 10. Open questions / future ideas

- **Muscle-level anatomy view (v2)** — overlay an anatomical layer on the silhouette where the runner can point at specific muscles (medial gastrocnemius vs lateral, vastus medialis vs lateralis). LLM gets even more specific context for prescription tweaks. Bigger SVG, bigger structure library, deferred.
- **Cross-walk to a body-map exercise database** — every exercise in the strength library carries muscle-group tags. With this feature live, the strength session can auto-skip exercises that load any active ≥ 5/10 region.
- **Trend detection across weeks** — when a region flares up repeatedly with similar pattern (e.g. always after a long run), surface that as an insight: *"your right calf has flared after 4 of your last 6 long runs — worth a calf-strengthening block?"*
- **Mental wellbeing companion** — separate domain, but the same tab could grow a *Mood / energy / motivation* check-in section. Particularly relevant for the post-marathon blues window.
- **Garmin sleep score & body battery on the Body tab** — when sleep+HRV (roadmap #2) lands, surface today's recovery vitals here too (one-stop wellbeing view). Body tab becomes the holistic *"how is the runner today"* surface.

## Cross-references

- Roadmap entry: [roadmap.md](roadmap.md) → *Next up — committed · #1*
- Downstream feature waiting on this: [post-marathon-recovery.md](post-marathon-recovery.md) (Day 1-2 body triage + Wk2 jog gate)
- Related daily-readiness logic: [daily-tips.md](daily-tips.md), [llm-coach.md](llm-coach.md)
- Adjacent input surfaces: [runners-diary.md](runners-diary.md) (subjective notes + mood), Garmin RPE / feel surfaced in [post-run-flagship.md](post-run-flagship.md)

---

*Design brief written: 2026-06-14. Update once implementation lands.*
