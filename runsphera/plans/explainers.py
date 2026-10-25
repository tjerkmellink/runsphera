"""Long-form "Read more" content for each methodology.

Powers the detail modal on /plans/new (the "Read more" button on every
methodology tile). This is authored editorial copy — what the plan is, who
built it, why you might pick it, and what to expect — kept out of
`MethodologyInfo` so the tile metadata stays scannable.

Illustrations are *placeholders*: each carries a `concept` (a short caption
shown in the dashed placeholder box) and a `prompt` written in the same
house style as the hero images (see docs/methodology-hero-images-brief.md).
Drop a rendered PNG into /static/method-detail/<id>-<slug>-{light,dark}.png
and the template will show it in place of the placeholder.

Content deepens over time — a methodology without an entry here falls back to
its tile description in the template, so the button always works.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Shared negative prompt / style anchors, so every illustration prompt reads
# as one family with the hero tiles. Appended to each prompt by the template.
ILLUSTRATION_STYLE = (
    "Warm cream paper background, ink-black linework, a single orange-red "
    "#ff3b1f accent, muted warm neutrals, editorial risograph poster with grain "
    "texture, minimal, generous negative space, no text, no words, no letters, "
    "no numbers, no logos, not photorealistic, no 3d render, no glossy chrome. "
    "16:9. Also produce a dark variant on a near-black #0a0a0a ground with the "
    "same orange-red accent."
)


@dataclass
class Illustration:
    """A placeholder for a diagram/graph that would enrich the section.

    `concept` is the human caption shown in the placeholder box; `prompt` is the
    ready-to-paste generation prompt (house style anchors are appended by the
    template). `slug` names the asset file once one is generated:
    /static/method-detail/<methodology_id>-<slug>-{light,dark}.png.
    """
    slug: str
    concept: str
    # Language-independent (image-gen prompts read best in English). Dutch
    # explainers leave this empty and it's backfilled from the English entry
    # by matching slug — see _backfill_nl_prompts().
    prompt: str = ""


@dataclass
class ExplainerSection:
    heading: str
    # Paragraphs may contain light inline HTML (<b>, <em>) — authored, trusted
    # content, rendered |safe by the template.
    paragraphs: list[str] = field(default_factory=list)
    # Optional bullet list rendered after the paragraphs.
    bullets: list[str] = field(default_factory=list)
    illustration: Illustration | None = None


@dataclass
class MethodologyExplainer:
    methodology_id: str
    # One-line promise shown under the title in the modal masthead.
    tagline: str
    # Lead paragraph(s) that open the article.
    lead: list[str]
    sections: list[ExplainerSection]
    # Optional short attribution line ("Created by …, in …").
    credit: str = ""


_EXPLAINERS: dict[str, MethodologyExplainer] = {
    "daniels": MethodologyExplainer(
        methodology_id="daniels",
        tagline="Train by the numbers — five exact pace zones scaled to your current fitness.",
        credit="Dr. Jack Daniels · Daniels' Running Formula (3rd ed.)",
        lead=[
            "Jack Daniels is an exercise physiologist and one of the most decorated "
            "distance coaches in the world — <em>Runner's World</em> once called him "
            "\"the world's best coach.\" His method, laid out in "
            "<em>Daniels' Running Formula</em>, turns the guesswork out of training: "
            "instead of \"run hard today, easy tomorrow,\" every run has a purpose and "
            "a precise pace attached to it.",
            "The whole system hangs off a single number — your <b>VDOT</b> — that "
            "captures your current fitness. Get that number right and every workout "
            "in the plan is dialled to exactly the right effort for <em>you</em>.",
        ],
        sections=[
            ExplainerSection(
                heading="One number that drives everything: VDOT",
                paragraphs=[
                    "VDOT is a running-specific version of VO₂max — a measure of how "
                    "efficiently your body uses oxygen. Daniels derived it from race "
                    "results, so you don't need a lab: a recent race time (or a good "
                    "estimate from your VO₂max) is enough to place you on the scale.",
                    "That one number then generates all five of your training paces at "
                    "once. As you get fitter your VDOT rises, your paces tighten, and "
                    "the plan recalibrates — so the training always tracks your real, "
                    "current ability rather than a pace that's already gone stale.",
                ],
                illustration=Illustration(
                    slug="vdot-dial",
                    concept="A dial/gauge turning one race time into a VDOT number, "
                    "which fans out into five pace bands.",
                    prompt=(
                        "Editorial risograph diagram of a single clean gauge or dial on "
                        "the left, its needle sending a line that fans out on the right "
                        "into five distinct horizontal pace bands of increasing weight. "
                        "The idea: one measured input becoming five precise outputs. "
                    ),
                ),
            ),
            ExplainerSection(
                heading="The five pace zones",
                paragraphs=[
                    "Every Daniels workout is run in one of five zones. Each trains a "
                    "different physiological system, and mixing them in the right "
                    "proportion is what makes the plan work:",
                ],
                bullets=[
                    "<b>E — Easy.</b> Conversational running that builds your aerobic "
                    "engine and capillaries. The bulk of every week lives here.",
                    "<b>M — Marathon.</b> Steady goal-marathon effort; teaches your body "
                    "to burn fuel efficiently at race pace.",
                    "<b>T — Threshold.</b> \"Comfortably hard\" tempo running that lifts "
                    "the pace you can hold before lactate piles up.",
                    "<b>I — Interval.</b> Hard 3–5 min repeats at close to VO₂max — the "
                    "zone that raises your ceiling.",
                    "<b>R — Repetition.</b> Short, fast reps for speed, economy and "
                    "running form, run well within your limits.",
                ],
                illustration=Illustration(
                    slug="pace-spectrum",
                    concept="A horizontal spectrum from Easy to Repetition, with the "
                    "Easy band far wider than the rest (the 80/20 split).",
                    prompt=(
                        "Editorial risograph diagram of a single horizontal spectrum bar "
                        "divided into five segments that grow shorter and darker from "
                        "left to right, the leftmost 'easy' segment by far the widest to "
                        "signal that most training is gentle. A lone runner silhouette "
                        "sits along the bar. Clean, calm, infographic feel. "
                    ),
                ),
            ),
            ExplainerSection(
                heading="What a typical week looks like",
                paragraphs=[
                    "Daniels concentrates the hard work into <b>two quality sessions a "
                    "week</b> — say a threshold run and an interval session — and keeps "
                    "everything else genuinely easy. That's the classic ~80/20 "
                    "easy-to-hard balance that keeps you improving without digging a "
                    "fatigue hole.",
                    "A long run anchors the week, and the plan scales from about 5 days "
                    "a week upward. The discipline of running easy days <em>easy</em> is "
                    "the part most runners get wrong — and the part that makes the two "
                    "hard days actually land.",
                ],
            ),
            ExplainerSection(
                heading="Why choose Daniels — and what to expect",
                paragraphs=[
                    "Pick Daniels when you want precision and a reason behind every run. "
                    "It works for any distance from 1500 m to the marathon, it's "
                    "exhaustively documented, and because it's pace-based you always "
                    "know exactly how fast to go.",
                    "Expect to see paces, not just \"easy/hard\", on every session. "
                    "Expect the plan to nudge those paces as your fitness changes. And "
                    "expect to feel like you're running your easy days almost too slowly "
                    "at first — that's the method working, not you being lazy.",
                ],
                bullets=[
                    "<b>Best for:</b> runners at any level who want structure and have a "
                    "recent race time or VO₂max to anchor their VDOT.",
                    "<b>Needs:</b> honesty about your easy pace, and a willingness to let "
                    "the numbers lead.",
                    "<b>Less ideal if:</b> you'd rather train purely by feel, or you have "
                    "no recent performance to estimate fitness from.",
                ],
            ),
        ],
    ),
    "foppen_7heuvelen": MethodologyExplainer(
        methodology_id="foppen_7heuvelen",
        tagline="Effort-based, hill-smart training for the Netherlands' most famous 15 km.",
        credit="Mike Foppen · Olympic 5000 m runner · NN Zevenheuvelenloop",
        lead=[
            "This is a race-specific, eleven-week plan built by <b>Mike Foppen</b> — a "
            "Dutch Olympic 5000 m runner — for one target: the "
            "<b>NN Zevenheuvelenloop</b>, the legendary 15 km \"Seven Hills Run\" through "
            "Nijmegen and the surrounding countryside.",
            "Where Daniels hands you a stopwatch, Foppen hands you a feeling. Every "
            "session is prescribed in <em>minutes and effort</em> — never a target pace — "
            "so it works whether you're chasing a personal best or simply want to "
            "survive the hills.",
        ],
        sections=[
            ExplainerSection(
                heading="Train by effort, not by pace",
                paragraphs=[
                    "The whole plan runs on three effort cues you learn to feel rather "
                    "than read off a watch:",
                ],
                bullets=[
                    "<b>RD — rustige dribbel (easy jog).</b> Barely above walking; you "
                    "could hold a flowing conversation. Recovery and aerobic base.",
                    "<b>DT — duurloop tempo (tempo run).</b> Full sentences, but not a "
                    "relaxed chat. The steady engine of the plan.",
                    "<b>INT — interval.</b> Word-by-word breathing, deliberately "
                    "uncomfortable — but never all-out. You pick a pace you can repeat "
                    "across every rep.",
                ],
                illustration=Illustration(
                    slug="effort-bands",
                    concept="Three stacked effort bands (RD / DT / INT) rising in "
                    "intensity, gauged by breathing rather than a clock.",
                    prompt=(
                        "Editorial risograph diagram of three horizontal effort bands "
                        "stacked from calm at the bottom to intense at the top, each a "
                        "little denser and more energetic than the one below, suggesting "
                        "easy jog, tempo, and interval effort measured by breathing. A "
                        "small runner silhouette moves along them. No clock, no gauge — "
                        "the feeling of effort, not a number. "
                    ),
                ),
            ),
            ExplainerSection(
                heading="Built for seven hills",
                paragraphs=[
                    "The Zevenheuvelenloop is a hilly course: the <b>first 7 km climb "
                    "steadily</b>, a second set of climbs bites between kilometres 7 and "
                    "10 on the Zevenheuvelenweg, and the finish rolls mostly downhill. So "
                    "the plan is built on three pillars — <b>endurance, comfort at race "
                    "pace, and leg strength for the climbs</b> — with hill runs and "
                    "hill-sprint intervals woven in from week three.",
                ],
                illustration=Illustration(
                    slug="hill-profile",
                    concept="The race's elevation profile — a long rising climb, a "
                    "second cluster of peaks, then a downhill run to the finish.",
                    prompt=(
                        "Editorial risograph landscape of a race elevation profile drawn "
                        "as rolling hills: a long gradual climb on the left, a cluster of "
                        "steeper peaks in the middle, easing into a downhill on the "
                        "right, with a tiny runner cresting one of the hills at dawn. "
                        "Sense of a real, specific course. "
                    ),
                ),
            ),
            ExplainerSection(
                heading="A typical week (with a wink)",
                paragraphs=[
                    "Three sessions a week — an easy RD, a tempo DT, and an INT session "
                    "— anchored to a Sunday race, with an optional fourth recovery jog if "
                    "you want it. Volume climbs from ~40-minute runs early on to a "
                    "90-minute peak tempo, then tapers into race week.",
                    "Foppen keeps it playful, too: most weeks carry a light-hearted "
                    "<em>challenge</em> — run a route shaped like a \"7\", hit 40,000 "
                    "steps, or finish in 40:40 as a nod to the race's 40th edition. "
                    "They're optional flavour, not training load.",
                ],
            ),
            ExplainerSection(
                heading="Why choose it — and what to expect",
                paragraphs=[
                    "Pick this if the Zevenheuvelenloop is your race, or if you simply "
                    "want a proven, low-maths plan for a hilly 15 km from an athlete who "
                    "has run at the very top.",
                ],
                bullets=[
                    "<b>Best for:</b> runners targeting the NN Zevenheuvelenloop, or any "
                    "hilly 15 km, who prefer training by feel.",
                    "<b>Needs:</b> a Sunday race date — the fixed schedule is built "
                    "backward from it, so the day and days-per-week pickers step aside.",
                    "<b>Expect:</b> effort cues instead of paces, real hills in your "
                    "long runs, and a taper that leaves you fresh for the climbs.",
                ],
            ),
        ],
    ),
    "pfitzinger": MethodologyExplainer(
        methodology_id="pfitzinger",
        tagline="A serious, high-mileage marathon build — medium-long runs and lactate threshold.",
        credit="Pete Pfitzinger · Advanced Marathoning · the \"18/55\" plan",
        lead=[
            "<b>Pete Pfitzinger</b> is a two-time US Olympic marathoner and exercise "
            "physiologist, and his book <em>Advanced Marathoning</em> is a gold-standard "
            "reference for runners who want to take the distance seriously. This is his "
            "most popular schedule — the <b>\"18/55\"</b>: eighteen weeks peaking near "
            "55 miles (~88 km) a week.",
            "It asks more of you than a beginner plan, and gives more back: a "
            "progression-driven build whose signature sessions train the specific "
            "fatigue-resistance a marathon demands.",
        ],
        sections=[
            ExplainerSection(
                heading="Four mesocycles over eighteen weeks",
                paragraphs=[
                    "The plan moves through four deliberate phases, each building on the "
                    "last:",
                ],
                bullets=[
                    "<b>Endurance (wks 1–6).</b> General-aerobic and recovery runs, the "
                    "mid-week medium-long run, a weekend long run. Threshold work enters "
                    "around week 3.",
                    "<b>Lactate threshold (wks 7–11).</b> A weekly threshold tempo; long "
                    "runs grow toward the signature 32 km, one rehearsing marathon pace.",
                    "<b>Race preparation (wks 12–15).</b> VO₂max intervals, "
                    "marathon-pace long runs, and two tune-up races.",
                    "<b>Taper (wks 16–18).</b> Volume sheds while sharpness stays; week "
                    "18 is race week, ending on the marathon itself.",
                ],
                illustration=Illustration(
                    slug="mileage-ramp",
                    concept="The 18-week mileage ramp — a rising line with step-back "
                    "weeks, split into four phase bands, peaking then tapering.",
                    prompt=(
                        "Editorial risograph diagram of an ascending mileage line that "
                        "climbs over time with small regular step-back dips, divided into "
                        "four subtle vertical bands (phases), rising to a clear peak on "
                        "the right and then dropping into a short taper. A determined "
                        "marathoner runs along the rising line. Sense of structure and "
                        "endurance. "
                    ),
                ),
            ),
            ExplainerSection(
                heading="The signature: the medium-long run",
                paragraphs=[
                    "What sets Pfitzinger apart is the <b>mid-week medium-long run</b> — "
                    "a substantial run stacked in between your weekend long run and your "
                    "quality sessions. Paired with regular <b>lactate-threshold tempos</b>, "
                    "it keeps you running on gently tired legs, which is exactly the state "
                    "the last 10 km of a marathon demands. Every pace is calibrated to "
                    "your VDOT, so the effort is right for your fitness.",
                ],
            ),
            ExplainerSection(
                heading="Why choose it — and what to expect",
                paragraphs=[
                    "Choose Pfitzinger when the marathon is the goal and you're ready to "
                    "train like it. It rewards consistency and a decent mileage base with "
                    "a plan that leaves very little to chance.",
                ],
                bullets=[
                    "<b>Best for:</b> marathoners who can build toward higher mileage and "
                    "want a proven, structured 18-week plan.",
                    "<b>Needs:</b> an existing aerobic base and 5 running days a week — "
                    "the plan owns its own schedule around your race day.",
                    "<b>Less ideal if:</b> you're new to distance running or can't commit "
                    "to the mid-week volume; a Higdon tier or Daniels build is gentler.",
                ],
            ),
        ],
    ),
    "higdon": MethodologyExplainer(
        methodology_id="higdon",
        tagline="The friendliest way into your first half or marathon — pick a level and go.",
        credit="Hal Higdon · long-time Runner's World columnist · halhigdon.com",
        lead=[
            "<b>Hal Higdon</b> wrote for <em>Runner's World</em> for over half a century "
            "and has run dozens of marathons himself. His training plans are the "
            "most-followed beginner schedules on the internet for one reason: they're "
            "simple, forgiving, and they work.",
            "There's no VDOT to calculate and no mileage base assumed. You pick an "
            "<b>experience tier</b>, set a race date, and get a schedule you can actually "
            "stick to — mostly easy running with one long run a week.",
        ],
        sections=[
            ExplainerSection(
                heading="Pick your experience tier",
                paragraphs=[
                    "Six tiers ladder up from complete first-timer to seasoned racer, so "
                    "the plan meets you where you are:",
                ],
                bullets=[
                    "<b>Novice 1 & 2.</b> New to the distance — easy runs, one long run, "
                    "a cross-training day. Novice 2 adds a little goal-pace running.",
                    "<b>Intermediate 1 & 2.</b> Five days a week, back-to-back weekend "
                    "runs, and two or three 20-milers; Intermediate 2 adds a weekly tempo.",
                    "<b>Advanced 1 & 2.</b> Six days with hills, tempo, goal-pace and "
                    "even 800 m speed work for runners chasing a time.",
                ],
                illustration=Illustration(
                    slug="tier-ladder",
                    concept="Six ascending steps/tiers, a cheerful runner stepping up "
                    "them one level at a time.",
                    prompt=(
                        "Editorial risograph poster of six clean oversized steps rising "
                        "gently from left to right, a friendly runner stepping up them "
                        "one tier at a time, the top step marked by the accent colour. "
                        "Approachable, encouraging, uncomplicated. "
                    ),
                ),
            ),
            ExplainerSection(
                heading="Mostly easy miles, one long run",
                paragraphs=[
                    "The engine of every Higdon plan is steady, conversational mileage "
                    "plus a weekend long run that ramps up with a <b>step-back week</b> "
                    "every third week to let you absorb the work. The marathon build runs "
                    "18 weeks and the half 12, peaking at the classic 32 km (20-mile) "
                    "long run before a short taper.",
                    "Descriptions read as effort — \"easy, conversational\", "
                    "\"comfortably hard\" — true to Higdon's style. But under the hood "
                    "every run still carries a pace target, so your workouts sync to your "
                    "watch and adapt as you get fitter.",
                ],
            ),
            ExplainerSection(
                heading="Why choose it — and what to expect",
                paragraphs=[
                    "Pick Higdon when you want to get to the start line without "
                    "over-thinking it — especially for a first half or marathon.",
                ],
                bullets=[
                    "<b>Best for:</b> first-timers and runners who prefer a "
                    "low-complexity schedule.",
                    "<b>Needs:</b> a half-marathon or marathon goal and a race date; the "
                    "tier you pick owns its own weekly pattern.",
                    "<b>Expect:</b> a calm, repeatable rhythm — no speed sessions at the "
                    "lower tiers, and plenty of room to just build the habit.",
                ],
            ),
        ],
    ),
    "c25k": MethodologyExplainer(
        methodology_id="c25k",
        tagline="From the sofa to 30 minutes of continuous running, in nine gentle weeks.",
        credit="Couch to 5K · Josh Clark (1996), popularised by the NHS",
        lead=[
            "Couch to 5K is the world's best-known <b>on-ramp for absolute beginners</b>. "
            "Created by Josh Clark to coax his own mum off the sofa and later adopted by "
            "the NHS, it has started millions of people running.",
            "The genius is the <b>run/walk method</b>: you alternate short bursts of "
            "running with walking breaks, and over nine weeks the running stretches grow "
            "until you can run for 30 minutes — about 5 km — without stopping.",
        ],
        sections=[
            ExplainerSection(
                heading="Run a little, walk a little",
                paragraphs=[
                    "Every session is <b>time-based and paceless</b> — there are no "
                    "speeds to hit, just effort. You start with eight one-minute runs "
                    "separated by 90-second walks, and each week the balance shifts a "
                    "little further toward running. Three sessions a week, always with a "
                    "rest day in between — never two runs back-to-back.",
                ],
                illustration=Illustration(
                    slug="runwalk-rhythm",
                    concept="A path drawn as alternating dashed (walk) and solid (run) "
                    "segments that gradually merge into one continuous line.",
                    prompt=(
                        "Editorial risograph illustration of a gentle path that begins as "
                        "short dashed marks alternating with solid segments and gradually "
                        "merges into one continuous flowing line rising toward a low "
                        "sunrise, suggesting run/walk intervals becoming continuous "
                        "running. Hopeful, encouraging, beginner energy. "
                    ),
                ),
            ),
            ExplainerSection(
                heading="Why the walk breaks matter",
                paragraphs=[
                    "The walking isn't a compromise — it's the whole point. A new "
                    "runner's heart and lungs adapt quickly, but tendons, ligaments and "
                    "joints take longer. The walk breaks let you accumulate running time "
                    "while giving that connective tissue the <b>gentle, gradual loading</b> "
                    "it needs to stay injury-free. Rushing this is the fastest way to get "
                    "hurt.",
                ],
            ),
            ExplainerSection(
                heading="Nine weeks to graduation",
                paragraphs=[
                    "By week 5 you're running 20 minutes straight; by week 9, a full "
                    "30-minute <b>graduation run</b> that lands right around 5 km. Because "
                    "a beginner's pace is unknown, the app never fakes one — you'll see "
                    "durations and effort cues, not \"5:30/km\".",
                ],
                illustration=Illustration(
                    slug="nine-week-ramp",
                    concept="Nine ascending columns growing from many tiny run/walk "
                    "blocks to one tall solid block (30 min continuous).",
                    prompt=(
                        "Editorial risograph diagram of nine columns growing left to "
                        "right, the early ones made of many small alternating segments "
                        "and the final ones a single tall solid bar, showing a build from "
                        "short run/walk intervals to continuous running. A small goal "
                        "flag tops the last column. Gentle, motivating. "
                    ),
                ),
            ),
            ExplainerSection(
                heading="Why choose it — and what to expect",
                paragraphs=[
                    "This is the place to start if running feels out of reach today. It "
                    "asks for nothing but a willingness to show up three times a week.",
                ],
                bullets=[
                    "<b>Best for:</b> absolute beginners and returners after a long "
                    "layoff.",
                    "<b>Needs:</b> just three days a week — you pick which, and the app "
                    "spaces them out for you.",
                    "<b>Expect:</b> effort cues, not paces; walk breaks that shrink week "
                    "by week; and a real 5 km within reach by the end.",
                ],
            ),
        ],
    ),
    "hybrid": MethodologyExplainer(
        methodology_id="hybrid",
        tagline="Daniels' precise paces meet Hansons' cumulative-fatigue philosophy.",
        credit="In development · Daniels × Hansons Marathon Method",
        lead=[
            "The Hybrid plan is a fusion of two respected marathon methods. It borrows "
            "<b>Jack Daniels' pace zones</b> for precision, then follows the "
            "<b>Hansons Marathon Method</b> philosophy for how the week is shaped.",
            "<em>This methodology is still in development — here's what it will be.</em>",
        ],
        sections=[
            ExplainerSection(
                heading="The Hansons idea: cumulative fatigue",
                paragraphs=[
                    "Brothers Keith and Kevin Hanson built their method around one "
                    "insight: the marathon is won in the last 10 km, so training should "
                    "rehearse running on <b>already-tired legs</b>. Rather than one huge "
                    "weekend long run, they cap the long run (around 30% of weekly "
                    "volume) and push more volume into <b>mid-week medium-long runs</b> — "
                    "so you're rarely fully recovered, and your body learns to keep going "
                    "anyway.",
                ],
                illustration=Illustration(
                    slug="two-methods-merge",
                    concept="Two overlapping runner silhouettes — one crisp/precise, one "
                    "built from dense repeated stride-lines — merging into one form.",
                    prompt=(
                        "Editorial risograph poster of two overlapping runner "
                        "silhouettes in a slight offset print, one crisp and precise, one "
                        "built from dense repeated stride-lines suggesting cumulative "
                        "fatigue, merging into a single balanced form. Dual, layered, "
                        "two-ink look. "
                    ),
                ),
            ),
            ExplainerSection(
                heading="Daniels' precision on top",
                paragraphs=[
                    "Onto that structure the Hybrid plan layers Daniels' exact pace zones "
                    "— Easy, Marathon, Threshold, Interval — calibrated to your VDOT. The "
                    "result aims to train marathon-specific fatigue resistance "
                    "<em>without</em> the oversized 32 km weekend grind, while still "
                    "telling you precisely how fast to run each session.",
                ],
            ),
            ExplainerSection(
                heading="What to expect — when it lands",
                paragraphs=[
                    "The Hybrid engine isn't built yet, so you can't select it today. "
                    "When it ships it'll suit marathoners who want long-run fatigue "
                    "training on a busier mid-week schedule.",
                ],
                bullets=[
                    "<b>Best for:</b> marathoners who want fatigue-resistance training "
                    "without a 32 km weekend long run.",
                    "<b>Status:</b> coming soon — the tile is visible but not yet "
                    "selectable.",
                ],
            ),
        ],
    ),
}


# ── Dutch translations ───────────────────────────────────────────────────
# Full nl copy, same structure as the English entries. Kept here (not in the
# global i18n `_NL` catalog) because these are long paragraphs with inline
# HTML — terrible dict keys. Illustration prompts are omitted and backfilled
# from the English entry by slug. English zone names (Easy/Marathon/Threshold/
# Interval/Repetition) and RD/DT/INT stay as-is, matching the tile copy.
_EXPLAINERS_NL: dict[str, MethodologyExplainer] = {
    "daniels": MethodologyExplainer(
        methodology_id="daniels",
        tagline="Trainen op de cijfers — vijf exacte tempozones, afgestemd op je huidige vorm.",
        credit="Dr. Jack Daniels · Daniels' Running Formula (3e editie)",
        lead=[
            "Jack Daniels is inspanningsfysioloog en een van de meest gelauwerde "
            "afstandscoaches ter wereld — <em>Runner's World</em> noemde hem ooit "
            "\"the world's best coach\". Zijn methode, uitgewerkt in "
            "<em>Daniels' Running Formula</em>, haalt het giswerk uit je training: in "
            "plaats van \"vandaag hard, morgen rustig\" heeft elke loop een doel én een "
            "precies tempo.",
            "Het hele systeem draait om één getal — je <b>VDOT</b> — dat je huidige vorm "
            "samenvat. Klopt dat getal, dan is elke training in het plan afgesteld op "
            "precies de juiste inspanning voor <em>jou</em>.",
        ],
        sections=[
            ExplainerSection(
                heading="Eén getal dat alles stuurt: VDOT",
                paragraphs=[
                    "VDOT is een hardloopspecifieke versie van VO₂max — een maat voor hoe "
                    "efficiënt je lichaam zuurstof gebruikt. Daniels leidde het af uit "
                    "wedstrijduitslagen, dus een lab heb je niet nodig: een recente "
                    "wedstrijdtijd (of een goede schatting uit je VO₂max) volstaat om je "
                    "op de schaal te plaatsen.",
                    "Dat ene getal genereert vervolgens al je vijf trainingstempo's "
                    "tegelijk. Word je fitter, dan stijgt je VDOT, worden je tempo's "
                    "scherper en herijkt het plan zich — zodat de training altijd je "
                    "echte, huidige niveau volgt in plaats van een tempo dat allang "
                    "achterhaald is.",
                ],
                illustration=Illustration(
                    slug="vdot-dial",
                    concept="Een wijzerplaat die één wedstrijdtijd omzet in een "
                    "VDOT-getal, dat uitwaaiert naar vijf tempobanden.",
                ),
            ),
            ExplainerSection(
                heading="De vijf tempozones",
                paragraphs=[
                    "Elke Daniels-training loop je in één van vijf zones. Elke zone "
                    "traint een ander fysiologisch systeem, en ze in de juiste verhouding "
                    "mengen is wat het plan laat werken:",
                ],
                bullets=[
                    "<b>E — Easy.</b> Rustig, op gesprekstempo; bouwt je aerobe motor en "
                    "haarvaten. Het grootste deel van elke week zit hier.",
                    "<b>M — Marathon.</b> Gestaag marathondoeltempo; leert je lichaam "
                    "brandstof efficiënt te verbranden op wedstrijdtempo.",
                    "<b>T — Threshold.</b> \"Comfortabel zwaar\" temposlopen dat het tempo "
                    "verhoogt dat je kunt volhouden voordat het lactaat zich opstapelt.",
                    "<b>I — Interval.</b> Harde herhalingen van 3–5 min dicht bij VO₂max — "
                    "de zone die je plafond optrekt.",
                    "<b>R — Repetition.</b> Korte, snelle herhalingen voor snelheid, "
                    "loopeconomie en techniek, ruim binnen je grenzen gelopen.",
                ],
                illustration=Illustration(
                    slug="pace-spectrum",
                    concept="Een horizontaal spectrum van Easy tot Repetition, met de "
                    "Easy-band veel breder dan de rest (de 80/20-verhouding).",
                ),
            ),
            ExplainerSection(
                heading="Hoe een typische week eruitziet",
                paragraphs=[
                    "Daniels concentreert het zware werk in <b>twee kwaliteitssessies per "
                    "week</b> — bijvoorbeeld een threshold-loop en een intervalsessie — en "
                    "houdt al het andere echt rustig. Dat is de klassieke "
                    "~80/20-verhouding tussen rustig en hard die je laat verbeteren "
                    "zonder een vermoeidheidsput te graven.",
                    "Een lange duurloop verankert de week, en het plan schaalt vanaf "
                    "ongeveer 5 dagen per week omhoog. De discipline om rustige dagen ook "
                    "écht <em>rustig</em> te lopen is wat de meeste lopers verkeerd doen — "
                    "en juist dát maakt dat de twee harde dagen aankomen.",
                ],
            ),
            ExplainerSection(
                heading="Waarom Daniels — en wat je kunt verwachten",
                paragraphs=[
                    "Kies Daniels als je precisie wilt en een reden achter elke loop. Het "
                    "werkt voor elke afstand van 1500 m tot de marathon, het is "
                    "uitputtend gedocumenteerd, en omdat het op tempo is gebaseerd weet je "
                    "altijd precies hoe hard je moet lopen.",
                    "Verwacht tempo's, niet alleen \"rustig/hard\", op elke sessie. "
                    "Verwacht dat het plan die tempo's bijstelt naarmate je vorm "
                    "verandert. En verwacht dat je rustige dagen in het begin bijna té "
                    "langzaam voelen — dat is de methode die werkt, niet jij die lui is.",
                ],
                bullets=[
                    "<b>Het beste voor:</b> lopers van elk niveau die structuur willen en "
                    "een recente wedstrijdtijd of VO₂max hebben om hun VDOT op te baseren.",
                    "<b>Nodig:</b> eerlijkheid over je rustige tempo, en de bereidheid de "
                    "cijfers te laten leiden.",
                    "<b>Minder ideaal als:</b> je liever puur op gevoel traint, of geen "
                    "recente prestatie hebt om je vorm uit te schatten.",
                ],
            ),
        ],
    ),
    "foppen_7heuvelen": MethodologyExplainer(
        methodology_id="foppen_7heuvelen",
        tagline="Trainen op inspanning en heuvelslim, voor de beroemdste 15 km van Nederland.",
        credit="Mike Foppen · Olympisch 5000 m-loper · NN Zevenheuvelenloop",
        lead=[
            "Dit is een wedstrijdspecifiek plan van elf weken, gebouwd door "
            "<b>Mike Foppen</b> — een Nederlandse olympische 5000 m-loper — met één doel: "
            "de <b>NN Zevenheuvelenloop</b>, de legendarische 15 km \"Seven Hills Run\" "
            "door Nijmegen en het omringende landschap.",
            "Waar Daniels je een stopwatch geeft, geeft Foppen je een gevoel. Elke sessie "
            "wordt voorgeschreven in <em>minuten en inspanning</em> — nooit een doeltempo "
            "— dus het werkt of je nu jaagt op een persoonlijk record of gewoon de "
            "heuvels wilt overleven.",
        ],
        sections=[
            ExplainerSection(
                heading="Trainen op inspanning, niet op tempo",
                paragraphs=[
                    "Het hele plan draait op drie inspanningscues die je leert voelen in "
                    "plaats van aflezen van een horloge:",
                ],
                bullets=[
                    "<b>RD — rustige dribbel.</b> Nauwelijks sneller dan wandelen; je kunt "
                    "een vloeiend gesprek voeren. Herstel en aerobe basis.",
                    "<b>DT — duurloop tempo.</b> Hele zinnen, maar geen ontspannen keuvel. "
                    "De gestage motor van het plan.",
                    "<b>INT — interval.</b> Ademen per woord, bewust ongemakkelijk — maar "
                    "nooit voluit. Je kiest een tempo dat je elke herhaling opnieuw kunt "
                    "lopen.",
                ],
                illustration=Illustration(
                    slug="effort-bands",
                    concept="Drie gestapelde inspanningsbanden (RD / DT / INT) die "
                    "oplopen in intensiteit, gemeten op ademhaling in plaats van een klok.",
                ),
            ),
            ExplainerSection(
                heading="Gebouwd voor zeven heuvels",
                paragraphs=[
                    "De Zevenheuvelenloop is een heuvelachtig parcours: de <b>eerste 7 km "
                    "klimmen gestaag</b>, een tweede reeks klimmetjes bijt tussen "
                    "kilometer 7 en 10 op de Zevenheuvelenweg, en de finish rolt "
                    "grotendeels bergaf. Daarom rust het plan op drie pijlers — "
                    "<b>uithoudingsvermogen, comfort op wedstrijdtempo en beenkracht voor "
                    "de klimmen</b> — met heuvellopen en heuvelsprint-intervallen die er "
                    "vanaf week drie in verweven zitten.",
                ],
                illustration=Illustration(
                    slug="hill-profile",
                    concept="Het hoogteprofiel van de wedstrijd — een lange klim, een "
                    "tweede cluster toppen, dan bergaf naar de finish.",
                ),
            ),
            ExplainerSection(
                heading="Een typische week (met een knipoog)",
                paragraphs=[
                    "Drie sessies per week — een rustige RD, een tempo-DT en een "
                    "INT-sessie — verankerd aan een zondagse wedstrijd, met een optionele "
                    "vierde hersteldribbel als je wilt. Het volume klimt van ~40 minuten "
                    "lopen in het begin naar een piek-tempoloop van 90 minuten, en tapert "
                    "dan af naar de wedstrijdweek.",
                    "Foppen houdt het ook speels: de meeste weken kennen een luchtige "
                    "<em>challenge</em> — loop een route in de vorm van een \"7\", haal "
                    "40.000 stappen, of finish in 40:40 als knipoog naar de 40e editie van "
                    "de wedstrijd. Het is optionele smaakmaker, geen trainingslast.",
                ],
            ),
            ExplainerSection(
                heading="Waarom dit plan — en wat je kunt verwachten",
                paragraphs=[
                    "Kies dit als de Zevenheuvelenloop jouw wedstrijd is, of als je "
                    "simpelweg een beproefd, cijferarm plan wilt voor een heuvelachtige "
                    "15 km van een atleet die op het allerhoogste niveau heeft gelopen.",
                ],
                bullets=[
                    "<b>Het beste voor:</b> lopers die de NN Zevenheuvelenloop als doel "
                    "hebben, of welke heuvelachtige 15 km dan ook, en die liever op gevoel "
                    "trainen.",
                    "<b>Nodig:</b> een zondagse wedstrijddatum — het vaste schema wordt "
                    "daarvandaan teruggerekend, dus de dag- en dagen-per-week-keuzes "
                    "stappen opzij.",
                    "<b>Verwacht:</b> inspanningscues in plaats van tempo's, echte heuvels "
                    "in je duurlopen, en een taper die je fris houdt voor de klimmen.",
                ],
            ),
        ],
    ),
    "pfitzinger": MethodologyExplainer(
        methodology_id="pfitzinger",
        tagline="Een serieuze marathonopbouw met veel volume — middellange duurlopen en lactaatdrempel.",
        credit="Pete Pfitzinger · Advanced Marathoning · het \"18/55\"-plan",
        lead=[
            "<b>Pete Pfitzinger</b> is tweevoudig Amerikaans olympisch marathonloper en "
            "inspanningsfysioloog, en zijn boek <em>Advanced Marathoning</em> is een "
            "standaardwerk voor lopers die de afstand serieus willen aanpakken. Dit is "
            "zijn populairste schema — de <b>\"18/55\"</b>: achttien weken met een piek "
            "rond 55 mijl (~88 km) per week.",
            "Het vraagt meer van je dan een beginnersplan, en geeft ook meer terug: een "
            "opbouw gedreven door progressie, met kenmerkende sessies die precies de "
            "vermoeidheidsweerstand trainen die een marathon vergt.",
        ],
        sections=[
            ExplainerSection(
                heading="Vier mesocycli over achttien weken",
                paragraphs=[
                    "Het plan beweegt door vier bewuste fases, elk voortbouwend op de "
                    "vorige:",
                ],
                bullets=[
                    "<b>Uithouding (wk 1–6).</b> Algemeen-aerobe en herstellopen, de "
                    "middellange duurloop doordeweeks, een lange duurloop in het weekend. "
                    "Rond week 3 komt het drempelwerk erbij.",
                    "<b>Lactaatdrempel (wk 7–11).</b> Wekelijks een drempeltempo; "
                    "duurlopen groeien richting de kenmerkende 32 km, waarvan er één "
                    "marathontempo oefent.",
                    "<b>Wedstrijdvoorbereiding (wk 12–15).</b> VO₂max-intervallen, lange "
                    "duurlopen op marathontempo en twee tune-up-wedstrijden.",
                    "<b>Taper (wk 16–18).</b> Het volume zakt terwijl de scherpte blijft; "
                    "week 18 is wedstrijdweek en eindigt met de marathon zelf.",
                ],
                illustration=Illustration(
                    slug="mileage-ramp",
                    concept="De volumecurve van 18 weken — een stijgende lijn met "
                    "terugstapweken, verdeeld in vier fasebanden, die piekt en dan tapert.",
                ),
            ),
            ExplainerSection(
                heading="Het handelsmerk: de middellange duurloop",
                paragraphs=[
                    "Wat Pfitzinger onderscheidt is de <b>middellange duurloop "
                    "doordeweeks</b> — een stevige loop tussen je lange weekendduurloop en "
                    "je kwaliteitssessies in. Samen met regelmatige "
                    "<b>lactaatdrempel-tempo's</b> houdt die je lopend op licht vermoeide "
                    "benen, precies de toestand die de laatste 10 km van een marathon "
                    "vraagt. Elk tempo is afgestemd op je VDOT, zodat de inspanning bij je "
                    "vorm past.",
                ],
            ),
            ExplainerSection(
                heading="Waarom dit plan — en wat je kunt verwachten",
                paragraphs=[
                    "Kies Pfitzinger als de marathon het doel is en je klaar bent om er "
                    "ook naar te trainen. Het beloont consistentie en een degelijke "
                    "volumebasis met een plan dat weinig aan het toeval overlaat.",
                ],
                bullets=[
                    "<b>Het beste voor:</b> marathonlopers die naar hoger volume kunnen "
                    "opbouwen en een beproefd, gestructureerd plan van 18 weken willen.",
                    "<b>Nodig:</b> een bestaande aerobe basis en 5 loopdagen per week — het "
                    "plan bepaalt zijn eigen schema rond je wedstrijddag.",
                    "<b>Minder ideaal als:</b> je nieuw bent in het afstandslopen of het "
                    "doordeweekse volume niet aankunt; een Higdon-niveau of "
                    "Daniels-opbouw is milder.",
                ],
            ),
        ],
    ),
    "higdon": MethodologyExplainer(
        methodology_id="higdon",
        tagline="De vriendelijkste weg naar je eerste halve of hele marathon — kies een niveau en ga.",
        credit="Hal Higdon · jarenlang Runner's World-columnist · halhigdon.com",
        lead=[
            "<b>Hal Higdon</b> schreef ruim een halve eeuw voor <em>Runner's World</em> en "
            "liep zelf tientallen marathons. Zijn trainingsschema's zijn de meest "
            "gevolgde beginnersplannen op internet, om één reden: ze zijn eenvoudig, "
            "vergevingsgezind en ze werken.",
            "Er is geen VDOT om te berekenen en geen volumebasis die verondersteld wordt. "
            "Je kiest een <b>ervaringsniveau</b>, stelt een wedstrijddatum in en krijgt "
            "een schema dat je echt kunt volhouden — vooral rustig lopen met één lange "
            "duurloop per week.",
        ],
        sections=[
            ExplainerSection(
                heading="Kies je ervaringsniveau",
                paragraphs=[
                    "Zes niveaus klimmen op van complete debutant tot doorgewinterde "
                    "wedstrijdloper, zodat het plan je opzoekt waar je staat:",
                ],
                bullets=[
                    "<b>Novice 1 & 2.</b> Nieuw op de afstand — rustige lopen, één lange "
                    "duurloop, een dag crosstraining. Novice 2 voegt wat lopen op "
                    "doeltempo toe.",
                    "<b>Intermediate 1 & 2.</b> Vijf dagen per week, back-to-back "
                    "weekendlopen en twee of drie lopen van 32 km; Intermediate 2 voegt "
                    "een wekelijkse tempoloop toe.",
                    "<b>Advanced 1 & 2.</b> Zes dagen met heuvels, tempo, doeltempo en "
                    "zelfs 800 m-snelheidswerk voor wie op een tijd jaagt.",
                ],
                illustration=Illustration(
                    slug="tier-ladder",
                    concept="Zes oplopende treden/niveaus, met een opgewekte loper die er "
                    "stap voor stap één omhoog gaat.",
                ),
            ),
            ExplainerSection(
                heading="Vooral rustige kilometers, één lange duurloop",
                paragraphs=[
                    "De motor van elk Higdon-plan is gestage, op gesprekstempo gelopen "
                    "kilometers plus een lange weekendduurloop die oploopt, met elke derde "
                    "week een <b>terugstapweek</b> om het werk te verwerken. De "
                    "marathonopbouw duurt 18 weken en de halve 12, met een piek op de "
                    "klassieke lange duurloop van 32 km voor een korte taper.",
                    "De omschrijvingen lezen als inspanning — \"rustig, op gesprekstempo\", "
                    "\"comfortabel zwaar\" — trouw aan Higdons stijl. Maar onder de "
                    "motorkap draagt elke loop nog steeds een doeltempo, zodat je "
                    "trainingen naar je horloge synchroniseren en meebewegen naarmate je "
                    "fitter wordt.",
                ],
            ),
            ExplainerSection(
                heading="Waarom dit plan — en wat je kunt verwachten",
                paragraphs=[
                    "Kies Higdon als je de startstreep wilt halen zonder het te "
                    "overdenken — zeker voor een eerste halve of hele marathon.",
                ],
                bullets=[
                    "<b>Het beste voor:</b> debutanten en lopers die een eenvoudig schema "
                    "verkiezen.",
                    "<b>Nodig:</b> een doel op de halve of hele marathon en een "
                    "wedstrijddatum; het gekozen niveau bepaalt zijn eigen weekpatroon.",
                    "<b>Verwacht:</b> een rustig, herhaalbaar ritme — geen "
                    "snelheidssessies op de lagere niveaus, en volop ruimte om simpelweg "
                    "de gewoonte op te bouwen.",
                ],
            ),
        ],
    ),
    "c25k": MethodologyExplainer(
        methodology_id="c25k",
        tagline="Van de bank naar 30 minuten aaneengesloten hardlopen, in negen rustige weken.",
        credit="Couch to 5K · Josh Clark (1996), populair gemaakt door de NHS",
        lead=[
            "Couch to 5K is 's werelds bekendste <b>opstap voor absolute beginners</b>. "
            "Bedacht door Josh Clark om zijn eigen moeder van de bank te krijgen en later "
            "overgenomen door de Britse NHS, heeft het miljoenen mensen aan het "
            "hardlopen gekregen.",
            "De clou is de <b>ren/wandel-methode</b>: je wisselt korte stukjes hardlopen "
            "af met wandelpauzes, en over negen weken worden de renstukken langer tot je "
            "30 minuten — zo'n 5 km — kunt lopen zonder te stoppen.",
        ],
        sections=[
            ExplainerSection(
                heading="Loop een beetje, wandel een beetje",
                paragraphs=[
                    "Elke sessie is <b>op tijd gebaseerd en tempoloos</b> — er zijn geen "
                    "snelheden om te halen, alleen inspanning. Je begint met acht "
                    "renstukjes van één minuut, gescheiden door wandelpauzes van 90 "
                    "seconden, en elke week verschuift de balans wat verder richting "
                    "hardlopen. Drie sessies per week, altijd met een rustdag ertussen — "
                    "nooit twee lopen op rij.",
                ],
                illustration=Illustration(
                    slug="runwalk-rhythm",
                    concept="Een pad getekend als afwisselend gestippelde (wandel) en "
                    "doorgetrokken (ren) stukken die geleidelijk samensmelten tot één "
                    "doorlopende lijn.",
                ),
            ),
            ExplainerSection(
                heading="Waarom de wandelpauzes ertoe doen",
                paragraphs=[
                    "Het wandelen is geen compromis — het is juist de kern. Het hart en "
                    "de longen van een beginnende loper passen zich snel aan, maar pezen, "
                    "banden en gewrichten hebben langer nodig. De wandelpauzes laten je "
                    "looptijd opbouwen terwijl ze dat bindweefsel de <b>zachte, "
                    "geleidelijke belasting</b> geven die het nodig heeft om blessurevrij "
                    "te blijven. Dit overhaasten is de snelste weg naar een blessure.",
                ],
            ),
            ExplainerSection(
                heading="Negen weken tot je diploma",
                paragraphs=[
                    "In week 5 loop je 20 minuten aan één stuk; in week 9 een volledige "
                    "<b>diplomaloop</b> van 30 minuten die rond de 5 km uitkomt. Omdat het "
                    "tempo van een beginner onbekend is, verzint de app er nooit een — je "
                    "ziet tijden en inspanningscues, geen \"5:30/km\".",
                ],
                illustration=Illustration(
                    slug="nine-week-ramp",
                    concept="Negen oplopende kolommen die groeien van veel kleine "
                    "ren/wandel-blokjes naar één hoog massief blok (30 min aaneengesloten).",
                ),
            ),
            ExplainerSection(
                heading="Waarom dit plan — en wat je kunt verwachten",
                paragraphs=[
                    "Dit is de plek om te beginnen als hardlopen vandaag nog onbereikbaar "
                    "voelt. Het vraagt niets meer dan de bereidheid om drie keer per week "
                    "te komen opdagen.",
                ],
                bullets=[
                    "<b>Het beste voor:</b> absolute beginners en herstarters na een lange "
                    "onderbreking.",
                    "<b>Nodig:</b> slechts drie dagen per week — jij kiest welke, en de "
                    "app spreidt ze voor je.",
                    "<b>Verwacht:</b> inspanningscues, geen tempo's; wandelpauzes die week "
                    "na week korter worden; en een echte 5 km binnen bereik aan het eind.",
                ],
            ),
        ],
    ),
    "hybrid": MethodologyExplainer(
        methodology_id="hybrid",
        tagline="De precieze tempo's van Daniels ontmoeten de cumulatieve-vermoeidheidsfilosofie van Hansons.",
        credit="In ontwikkeling · Daniels × Hansons Marathon Method",
        lead=[
            "Het Hybride plan is een versmelting van twee gerespecteerde "
            "marathonmethodes. Het leent <b>Jack Daniels' tempozones</b> voor precisie en "
            "volgt vervolgens de filosofie van de <b>Hansons Marathon Method</b> voor hoe "
            "de week is vormgegeven.",
            "<em>Deze methodologie is nog in ontwikkeling — dit is wat het gaat "
            "worden.</em>",
        ],
        sections=[
            ExplainerSection(
                heading="Het Hansons-idee: cumulatieve vermoeidheid",
                paragraphs=[
                    "De broers Keith en Kevin Hanson bouwden hun methode rond één "
                    "inzicht: de marathon wordt in de laatste 10 km beslist, dus training "
                    "moet het lopen op <b>al vermoeide benen</b> oefenen. In plaats van "
                    "één enorme weekendduurloop houden ze de lange duurloop in toom (rond "
                    "30% van het weekvolume) en verschuiven ze meer volume naar "
                    "<b>middellange duurlopen doordeweeks</b> — zodat je zelden volledig "
                    "hersteld bent en je lichaam leert tóch door te gaan.",
                ],
                illustration=Illustration(
                    slug="two-methods-merge",
                    concept="Twee overlappende loper-silhouetten — één strak/precies, één "
                    "opgebouwd uit dichte, herhaalde paslijnen — die samensmelten tot één "
                    "vorm.",
                ),
            ),
            ExplainerSection(
                heading="De precisie van Daniels erbovenop",
                paragraphs=[
                    "Op die structuur legt het Hybride plan Daniels' exacte tempozones — "
                    "Easy, Marathon, Threshold, Interval — afgestemd op je VDOT. Het doel "
                    "is marathonspecifieke vermoeidheidsweerstand trainen <em>zonder</em> "
                    "de overdreven lange duurloop van 32 km in het weekend, terwijl het je "
                    "nog steeds precies vertelt hoe hard je elke sessie moet lopen.",
                ],
            ),
            ExplainerSection(
                heading="Wat je kunt verwachten — als het er is",
                paragraphs=[
                    "De Hybride-engine is nog niet gebouwd, dus je kunt hem vandaag nog "
                    "niet selecteren. Wanneer hij verschijnt, past hij bij marathonlopers "
                    "die vermoeidheidstraining uit lange duurlopen willen op een voller "
                    "doordeweeks schema.",
                ],
                bullets=[
                    "<b>Het beste voor:</b> marathonlopers die vermoeidheidstraining "
                    "willen zonder een lange duurloop van 32 km in het weekend.",
                    "<b>Status:</b> binnenkort beschikbaar — de tegel is zichtbaar maar "
                    "nog niet selecteerbaar.",
                ],
            ),
        ],
    ),
}


def _backfill_nl_prompts() -> None:
    """Dutch illustrations omit the (language-independent) generation prompt;
    copy it over from the English entry with the same slug."""
    for mid, nl_ex in _EXPLAINERS_NL.items():
        en_ex = _EXPLAINERS.get(mid)
        if not en_ex:
            continue
        en_prompt = {
            s.illustration.slug: s.illustration.prompt
            for s in en_ex.sections
            if s.illustration
        }
        for s in nl_ex.sections:
            if s.illustration and not s.illustration.prompt:
                s.illustration.prompt = en_prompt.get(s.illustration.slug, "")


_backfill_nl_prompts()


def get_explainer(methodology_id: str, locale: str = "en") -> MethodologyExplainer | None:
    """Long-form content for a methodology, in `locale` when a translation
    exists (falls back to English), or None if not authored at all."""
    if locale == "nl" and methodology_id in _EXPLAINERS_NL:
        return _EXPLAINERS_NL[methodology_id]
    return _EXPLAINERS.get(methodology_id)
