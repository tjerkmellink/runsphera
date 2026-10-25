"""Lightweight i18n for Running Coach.

## Design

- **English is the source-of-truth language.** English literals double as
  the translation lookup keys — no separate key namespace to maintain.
- **Missing keys fall back to the source.** If a string hasn't been
  ported yet, it still renders in English instead of throwing — so we
  can land features without translating everything in the same PR.
- **Two languages**: `en` (default), `nl` (Nederlands). Add more by
  extending `LANGUAGES` and dropping a new dict alongside `_NL`.

## Usage

In Jinja templates the `t` function is registered as a per-request
template global already bound to the user's locale:

    {{ t("Distance") }}
    {{ t("{n} days to race", n=days_to_race) }}

In Python:

    from .i18n import t
    msg = t("Recalibrated {n} workouts", n=4, locale="nl")

## Adding a Dutch translation

Open this file and add the English source → Dutch target pair to
`_NL`. Keep keys in roughly alphabetical order within each section
header so new strings are easy to slot in without conflicts. Use
`{name}` placeholders for interpolation — they survive translation
because `.format()` runs *after* the lookup.

## Pluralization

Both EN and NL share the same simple plural rule (`1 day` / `2 days`,
`1 dag` / `2 dagen`) so use the `plural` helper for the common case:

    {{ plural(n, "{n} day", "{n} days") }}        → EN: 1 day, 2 days
    {{ plural(n, "{n} dag", "{n} dagen") }}       → NL: 1 dag, 2 dagen

For sentences where the count drives a full phrase (e.g. "{n} days
to race"), prefer translating the whole sentence as a single key so
word order isn't locked.

## What we DON'T translate

- Pace strings ("4:59/km"), HR numbers, dates rendered via ISO/format.
- Coach LLM output — that's controlled by the prompt language
  instruction in runsphera/llm/prompts.py, not the dict here.
- Pace zone abbreviations (E/M/T/I/R) — universal in running coaching.
"""
from __future__ import annotations


LANGUAGES: dict[str, str] = {
    "en": "English",
    "nl": "Nederlands",
}


# ── Dutch translations ─────────────────────────────────────────────────
# Keys are the English source string. If a key is missing here, the
# English source is rendered instead — so unported pages stay readable.
_NL: dict[str, str] = {
    # ── Nav / global ────────────────────────────────────────────────
    "Dashboard": "Dashboard",
    "Plans": "Plannen",
    "Calendar": "Kalender",
    "Diary": "Dagboek",
    "Fuel": "Voeding",
    "Settings": "Instellingen",
    "Sign in": "Inloggen",
    "Sign out": "Uitloggen",
    "Connected": "Verbonden",
    "Not connected": "Niet verbonden",
    "Sync from Garmin": "Synchroniseren met Garmin",
    "Syncing…": "Synchroniseren…",

    # ── Common actions ──────────────────────────────────────────────
    "Save": "Opslaan",
    "Cancel": "Annuleren",
    "Delete": "Verwijderen",
    # Inline confirm strips (see the handler in base.html). "Yes, continue"
    # is the fallback when a form doesn't name its own confirm label.
    "Yes, continue": "Ja, doorgaan",
    "Yes, delete": "Ja, verwijderen",
    "Yes, clear": "Ja, wissen",
    "Yes, deactivate": "Ja, deactiveren",
    "Yes, disconnect": "Ja, verbinding verbreken",
    "Yes, recalibrate": "Ja, herkalibreren",
    "Edit": "Bewerken",
    "Edit plan": "Plan bewerken",
    "Archive": "Archiveren",
    "Close": "Sluiten",
    "Confirm": "Bevestigen",
    "Open": "Openen",
    "Loading…": "Laden…",
    "Apply": "Toepassen",
    "Refresh": "Vernieuwen",
    "Regenerate": "Opnieuw genereren",

    # ── Fuel — nutrition & hydration ────────────────────────────────
    "// Fuel · Eat for the work": "// Voeding · Eet voor de inspanning",
    "Calorie, carbohydrate and hydration targets that follow your plan — more on long-run days, less on rest days. Rules-based, computed on this machine.":
        "Calorie-, koolhydraat- en vochtdoelen die je plan volgen — meer op lange-duurloopdagen, minder op rustdagen. Op regels gebaseerd, berekend op deze machine.",
    "Energy & macros": "Energie & macro's",
    "Energy target": "Energiedoel",
    "Energy": "Energie",
    "Carbs": "Koolhydraten",
    "carbs": "koolhydraten",
    "carbs / hr": "koolhydraten / uur",
    "Protein": "Eiwit",
    "protein": "eiwit",
    "Fat": "Vet",
    "fat": "vet",
    "run": "loop",
    "Meals": "Maaltijden",
    "What to eat": "Wat te eten",
    "Breakfast": "Ontbijt",
    "Lunch": "Lunch",
    "Dinner": "Avondeten",
    "Snack": "Tussendoortje",
    "These meals ≈ {a} g of your {b} g carb target": "Deze maaltijden ≈ {a} g van je {b} g koolhydraatdoel",
    "plus {n} g during the run": "plus {n} g tijdens de loop",
    "Top up with extra snacks — portions are a starting point.": "Vul aan met extra tussendoortjes — porties zijn een startpunt.",
    "Fuel the run": "Voeding tijdens de loop",
    "~{n} min effort": "~{n} min inspanning",
    "Before": "Vooraf",
    "During": "Tijdens",
    "After": "Achteraf",
    "2–3 h before": "2–3 u vooraf",
    "≈ 1 gel every {n} min": "≈ 1 gel elke {n} min",
    "fluid / hr": "vocht / uur",
    "within 30–60 min": "binnen 30–60 min",
    "Hydration today": "Vocht vandaag",
    "Hydration": "Vocht",
    "Baseline": "Basis",
    "warm-day bump": "warme-dag toeslag",
    "Carb load by day": "Koolhydraatbelasting per dag",
    "Week {n} of {total}": "Week {n} van {total}",
    "Mon": "Ma", "Tue": "Di", "Wed": "Wo", "Thu": "Do",
    "Fri": "Vr", "Sat": "Za", "Sun": "Zo",
    "Gels": "Gels",
    "every {n}'": "elke {n}'",
    "Eat for the {kind}": "Eet voor de {kind}",
    "rest / low-carb day": "rustdag / koolhydraatarm",
    "cross-training day": "cross-trainingsdag",
    "easy day": "rustige dag",
    "quality day": "kwaliteitsdag",
    "long-run / high-carb day": "lange-duurloop / koolhydraatrijk",
    "race day": "wedstrijddag",
    "Previous day": "Vorige dag",
    "Next day": "Volgende dag",
    "Tell us about your body first.": "Vertel ons eerst iets over je lichaam.",
    "Fuel needs your weight (and ideally height, birth year and sex) to turn training load into eat-and-drink targets. It's two minutes in Settings and never leaves this laptop.":
        "Voeding heeft je gewicht nodig (en idealiter lengte, geboortejaar en geslacht) om trainingsbelasting om te zetten in eet- en drinkdoelen. Twee minuten in Instellingen en het verlaat deze laptop nooit.",
    "Set up body profile": "Lichaamsprofiel instellen",
    "Add your height, birth year and sex in Settings for a calorie target — carbs and protein are already personalised by weight.":
        "Voeg je lengte, geboortejaar en geslacht toe in Instellingen voor een caloriedoel — koolhydraten en eiwit zijn al op gewicht afgestemd.",
    "BMR from Garmin (add height, birth year & sex for the formula-based estimate).":
        "BMR van Garmin (voeg lengte, geboortejaar & geslacht toe voor de formule-schatting).",
    # ── Settings — body profile card ────────────────────────────────
    "Body profile": "Lichaamsprofiel",
    "Powers the Fuel tab — turns your training load into calorie, carb and hydration targets. Weight is the one field that's required; the rest sharpen the numbers.":
        "Voedt het Voeding-tabblad — zet je trainingsbelasting om in calorie-, koolhydraat- en vochtdoelen. Gewicht is het enige verplichte veld; de rest verfijnt de cijfers.",
    "Weight": "Gewicht",
    "Height": "Lengte",
    "Birth year": "Geboortejaar",
    "Sex": "Geslacht",
    "Male": "Man",
    "Female": "Vrouw",
    "Diet": "Dieet",
    "Omnivore": "Alleseter",
    "Vegetarian": "Vegetarisch",
    "Vegan": "Veganistisch",
    "Save profile": "Profiel opslaan",
    "Pre-fill from Garmin": "Voorinvullen vanuit Garmin",
    "Pull weight, height, sex and birth year from your Garmin profile. You can still edit afterwards.":
        "Haal gewicht, lengte, geslacht en geboortejaar uit je Garmin-profiel. Je kunt het daarna nog aanpassen.",
    "Import": "Importeren",
    "Body profile saved. Your fuel targets are now personalised.":
        "Lichaamsprofiel opgeslagen. Je voedingsdoelen zijn nu gepersonaliseerd.",
    "Pre-filled from Garmin. Check the values and adjust if needed.":
        "Voorgevuld vanuit Garmin. Controleer de waarden en pas ze indien nodig aan.",
    "Couldn't save — check the values (weight 30–250 kg, height 100–250 cm).":
        "Kon niet opslaan — controleer de waarden (gewicht 30–250 kg, lengte 100–250 cm).",
    "Garmin didn't return usable body data. Enter it manually below.":
        "Garmin gaf geen bruikbare lichaamsgegevens terug. Voer ze hieronder handmatig in.",

    # ── Dashboard headlines (rules-engine status) ──────────────────
    "Go.": "Gas erop.",
    "Caution.": "Voorzichtig.",
    "Easy.": "Rustig.",
    "Rest.": "Rust.",
    "Done.": "Gedaan.",
    "Green light": "Groen licht",
    "Ease off": "Rustig aan",
    "Rest day": "Rustdag",
    "Logged": "Afgevinkt",
    # Lowercase "Caution" (the pill, separate from "Caution." headline)
    # — duplicates with the all-caps coach status; keep the casing that
    # matches the source for unambiguous lookup.
    "Caution": "Voorzichtig",

    # ── Dashboard subhead + welcome ─────────────────────────────────
    "last ingest:": "laatste synchronisatie:",
    "rows": "rijen",
    "error:": "fout:",
    "no data yet — click \"Sync from Garmin\"": "nog geen data — klik op \"Synchroniseren met Garmin\"",
    "Hi {name}!": "Hoi {name}!",
    "Welcome!": "Welkom!",
    "I'll be your personal running coach. Pull your training data from Garmin to get started, then create a plan toward your next race.": "Ik ben je persoonlijke hardloopcoach. Synchroniseer je trainingsdata vanuit Garmin om te beginnen, en maak dan een plan richting je volgende wedstrijd.",
    "Sync your Garmin data": "Garmin-data synchroniseren",
    "Create your first plan": "Maak je eerste plan",
    "Apply swap": "Wissel toepassen",
    "HI": "HOI",

    # ── Dashboard weather aside ─────────────────────────────────────
    "Weather · 48h": "Weer · 48u",
    "wind": "wind",
    "rain": "regen",
    "Best window": "Beste moment",

    # ── Today's workout flagship ────────────────────────────────────
    "Today": "Vandaag",
    "session": "sessie",
    "View plan →": "Plan bekijken →",
    "Target time": "Doeltijd",
    "Plan": "Plan",
    "Bonus": "Bonus",
    "Open event details": "Evenementdetails openen",
    # Post-run summary (flagship flips from prescription → actuals once matched)
    "Done ✓": "Klaar ✓",
    "Time": "Tijd",
    "Avg HR": "Gem. HS",
    "Planned:": "Gepland:",
    "vs {target} km target": "t.o.v. doel {target} km",
    "vs {target} target": "t.o.v. doel {target}",
    # Rest-day strength session on the flagship
    "Strength": "Kracht",
    "Active recovery": "Actief herstel",
    "Duration": "Duur",
    "Blocks": "Blokken",
    "Exercises": "Oefeningen",
    "Calories": "Calorieën",
    "min": "min",
    "min planned": "min gepland",
    "Mark done ✓": "Markeer als klaar ✓",
    "Open session": "Sessie openen",
    "Rest day for running. This bodyweight session keeps the engine strong — tap for the full breakdown.": "Rustdag voor het hardlopen. Deze bodyweight-sessie houdt de motor sterk — tik voor het volledige overzicht.",
    "Bodyweight session done — tap for the full breakdown.": "Bodyweight-sessie gedaan — tik voor het volledige overzicht.",

    # ── Dashboard stats wall ────────────────────────────────────────
    "VO₂ max": "VO₂ max",
    "measured {date}": "gemeten {date}",
    "Readiness": "Gereedheid",
    "Acute / chronic": "Acuut / chronisch",
    "load ratio": "belastingsverhouding",

    # ── Dashboard charts ────────────────────────────────────────────
    "Weekly mileage · 12 weeks": "Wekelijkse kilometers · 12 weken",
    "HR zones · 7 days": "HR-zones · 7 dagen",
    "No HR-zone data in the last 7 days.": "Geen HR-zone data in de afgelopen 7 dagen.",
    "Acute training load · 28 days": "Acute trainingsbelasting · 28 dagen",
    "Optimal Range": "Optimale zone",
    "Acute load": "Acute belasting",
    "load": "belasting",
    "No training-load data yet — sync to populate.": "Nog geen trainingsbelasting — synchroniseer om te vullen.",
    "No training-load data — this chart fills from a connected Garmin watch.":
        "Geen trainingsbelasting — deze grafiek vult zich via een gekoppeld Garmin-horloge.",

    # ── Dashboard recent runs ───────────────────────────────────────
    "Recent": "Recent",
    "Last out the door.": "Laatst de deur uit.",
    "Date": "Datum",
    "Session": "Sessie",
    "Avg HR": "Gem HR",
    "Load": "Belasting",
    "Newer": "Nieuwer",
    "Older": "Ouder",
    "Page": "Pagina",

    # ── Dashboard (other) ───────────────────────────────────────────
    "Welcome back": "Welkom terug",
    "Today.": "Vandaag.",
    "Rest day.": "Rustdag.",
    "Recovery is part of the plan. Hydrate, eat well, walk easy. Tomorrow's session starts here.": "Herstel is onderdeel van het plan. Hydrateer, eet goed, wandel rustig. De training van morgen begint hier.",
    "View plan →": "Plan bekijken →",
    "Today · {plan_title}": "Vandaag · {plan_title}",
    "Race day": "Wedstrijddag",
    "Bonus · {category} · {min} min": "Bonus · {category} · {min} min",
    "Recent runs.": "Recente runs.",
    "No runs yet. Click \"Sync from Garmin\" to load activity history.": "Nog geen runs. Klik op \"Synchroniseren met Garmin\" om je activiteiten te laden.",
    "No run history — this list fills from a connected Garmin watch. Your plan progress lives on the Plans tab.":
        "Geen rungeschiedenis — deze lijst vult zich via een gekoppeld Garmin-horloge. Je planvoortgang vind je op het tabblad Plannen.",
    "The numbers": "De cijfers",
    "You, by the digits.": "Jij, in cijfers.",
    # This week, wrapped — current training-week stats block.
    "This week": "Deze week",
    "Week {n}, wrapped": "Week {n}, afgerond",
    "Week {n} so far": "Week {n} tot nu toe",
    "km this week": "km deze week",
    "sessions": "sessies",
    "load": "belasting",
    "Time on feet": "Tijd op de benen",
    "moving time": "bewegingstijd",
    "longest {km} km": "langste {km} km",
    "Plan total": "Plantotaal",
    "km banked": "km op de teller",
    "{n} run": "{n} run",
    "{n} runs": "{n} runs",
    "since day one": "sinds dag één",
    "Streak": "Reeks",
    "week": "week",
    "weeks": "weken",
    "80%+ adherence": "80%+ naleving",
    "Regenerate this week's celebration": "Deze weekviering opnieuw genereren",
    "That's {n} weeks in a row. This is what consistency looks like.":
        "Dat zijn {n} weken op rij. Zo ziet consistentie eruit.",
    "Every session done — and every target hit. Textbook week.":
        "Elke sessie gedaan — en elk doel gehaald. Voorbeeldige week.",
    "Week complete, capped by a {km} km long run. Money in the bank.":
        "Week compleet, bekroond met een lange duurloop van {km} km. Geld in het laatje.",
    "Every planned session, done. That's the week — well run.":
        "Elke geplande sessie gedaan. Dat is de week — sterk gelopen.",
    "{done} of {planned} done — one more to close out the week.":
        "{done} van {planned} gedaan — nog één om de week af te sluiten.",
    "{done} of {planned} done — {left} to go this week. Keep it rolling.":
        "{done} van {planned} gedaan — nog {left} te gaan deze week. Zet 'm door.",
    "Training status": "Trainingsstatus",
    "7d trend": "7d trend",
    "as of {date}": "per {date}",
    "Updated {date}": "Bijgewerkt {date}",
    "UPDATED {date}": "BIJGEWERKT {date}",
    "Weekly mileage": "Wekelijkse kilometers",
    "Last {n} weeks": "Laatste {n} weken",
    "HR zones": "HR-zones",
    "Last 7 days": "Laatste 7 dagen",
    "Total": "Totaal",
    "Total km": "Totaal km",
    "VDOT": "VDOT",
    "Adherence": "Naleving",
    "{n} of {planned} planned sessions done": "{n} van {planned} geplande sessies gedaan",
    "{n} missed": "{n} gemist",
    "Today's note": "Notitie van vandaag",
    "Diary": "Dagboek",
    "A few words about today…": "Een paar woorden over vandaag…",

    # ── Coach banner / weekly recap ─────────────────────────────────
    "Coach": "Coach",
    "Coach is reading the file…": "De coach leest het dossier…",
    "↻ Regenerate": "↻ Opnieuw genereren",
    "Week recap": "Weekoverzicht",
    "Pull from Garmin, then I'll have something to say.": "Synchroniseer met Garmin, dan heb ik iets te zeggen.",

    # ── Plans page ──────────────────────────────────────────────────
    "+ New plan": "+ Nieuw plan",
    "+ Create your first plan": "+ Maak je eerste plan",
    "No active plan.": "Geen actief plan.",
    "Create one to get a methodology-driven schedule built around your current fitness.": "Maak een plan voor een methodisch schema rond je huidige fitheid.",
    "no active plan": "geen actief plan",
    "active plan · {goal}": "actief plan · {goal}",
    "Goal": "Doel",
    "Methodology": "Methodologie",
    "Days": "Dagen",
    "to race": "tot wedstrijd",
    "since race": "sinds wedstrijd",
    "no race date": "geen wedstrijddatum",
    "race {date}": "wedstrijd {date}",
    "at start": "bij start",
    "km · {n} wks": "km · {n} wkn",
    "not yet": "nog niet",
    "{n}/{due} done": "{n}/{due} gedaan",
    "{n} days/week, long run on {day}s.": "{n} dagen/week, lange run op {day}.",
    "Started {date}.": "Gestart {date}.",
    "Calibrated to VDOT {vdot} at start.": "Gekalibreerd op VDOT {vdot} bij start.",
    "Re-match": "Opnieuw matchen",
    "Re-run adherence matching": "Naleving opnieuw bepalen",
    "Edit plan title and notes": "Plan titel en notities bewerken",
    "Block map · {n} weeks": "Blokkenkaart · {n} weken",
    "↓ Upcoming & reworking": "↓ Aankomend & in revisie",
    "Previous plans": "Eerdere plannen",
    "View": "Bekijken",
    "ACTIVE PLAN · {n} WEEKS": "ACTIEF PLAN · {n} WEKEN",

    # ── New-plan builder (/plans/new) ───────────────────────────────
    "New training plan": "Nieuw trainingsplan",
    "Built from your current data:": "Gebaseerd op je huidige data:",
    "baseline (4-week average).": "basis (gemiddelde over 4 weken).",
    "Building a plan toward": "Een plan opbouwen richting",
    "Date, goal, and title are pre-filled. Pick a methodology and the schedule details below.":
        "Datum, doel en titel zijn alvast ingevuld. Kies hieronder een methodologie en de schemadetails.",
    # Goal tiles + their duration hints
    "Stay fit": "Fit blijven",
    "5 km race": "5 km-wedstrijd",
    "10 km race": "10 km-wedstrijd",
    "15 km race": "15 km-wedstrijd",
    "Half marathon": "Halve marathon",
    "Marathon": "Marathon",
    "rolling 4-week cycle": "doorlopende cyclus van 4 weken",
    "~8 weeks": "~8 weken",
    "~10 weeks": "~10 weken",
    "~11 weeks": "~11 weken",
    "~12 weeks": "~12 weken",
    "~16 weeks": "~16 weken",
    # Methodology cards
    "Coming soon": "Binnenkort",
    "Best for:": "Geschikt voor:",
    # Methodology picker tiles — hooks, badges, chips, states
    "Pace zones derived from your VO₂max.": "Tempozones afgeleid van je VO₂max.",
    "Effort-based, with an eye for the hills.": "Op inspanning gebaseerd, met oog voor de heuvels.",
    "18-week marathon build, ~88 km peak.": "18-weeks marathonopbouw, piek van ~88 km.",
    "Step-up plans by experience tier.": "Opbouwende plannen per ervaringsniveau.",
    "From the couch to 30 minutes of running.": "Van de bank naar 30 minuten hardlopen.",
    "Race-specific · 15K": "Wedstrijdspecifiek · 15K",
    "Race-specific · Marathon": "Wedstrijdspecifiek · Marathon",
    "Beginner-friendly": "Beginnersvriendelijk",
    "Beginner · 5K": "Beginner · 5K",
    "wks": "wkn",
    "days/wk": "dagen/wk",
    "min/session": "min/sessie",
    "peak": "piek",
    "Low intensity": "Lage intensiteit",
    "Moderate intensity": "Gemiddelde intensiteit",
    "High intensity": "Hoge intensiteit",
    "Fixed schedule": "Vast schema",
    "Read more": "Meer lezen",
    "Show less": "Minder",
    # Methodology "Read more" detail modal (long-form copy lives in
    # runsphera/plans/explainers.py; these are the template chrome bits)
    "Illustration:": "Illustratie:",
    "Generation prompt": "Beeldprompt",
    "Best for": "Het beste voor",
    "A fuller guide to this plan is on the way.": "Een uitgebreidere gids voor dit plan is onderweg.",
    "Pace zones derived from VO₂max. Rigorous and well-documented.":
        "Tempozones afgeleid van VO₂max. Rigoureus en goed gedocumenteerd.",
    "Daniels' Running Formula builds every workout around five pace zones — Easy, Marathon, Threshold, Interval, and Repetition — that scale precisely with your VDOT (a VO₂max-equivalent score). Quality work is concentrated in two sessions a week, with the rest at a strict easy pace to drive aerobic adaptation.":
        "Daniels' Running Formula bouwt elke training op rond vijf tempozones — Easy, Marathon, Threshold, Interval en Repetition — die precies meeschalen met je VDOT (een VO₂max-equivalente score). Het kwaliteitswerk zit in twee sessies per week, de rest op een strikt rustig tempo om aerobe aanpassing te sturen.",
    "All distances, all levels. Especially good when you have a recent VO₂max number.":
        "Alle afstanden, alle niveaus. Vooral goed als je een recent VO₂max-getal hebt.",
    "Race-specific 11-week plan for the NN Zevenheuvelenloop. Effort-based, hill-aware.":
        "Wedstrijdspecifiek 11-weeks plan voor de NN Zevenheuvelenloop. Op inspanning gebaseerd, met oog voor heuvels.",
    "Eleven-week plan authored by Mike Foppen (Olympic 5000 m athlete) for the NN Zevenheuvelenloop in Nijmegen. Three sessions per week — easy jog (RD), tempo run (DT), and intervals (INT) — all prescribed by duration and effort cues rather than pace zones. Fixed schedule: requires only a Sunday race date. Days-per-week and long-run-day selectors are ignored.":
        "Elf weken durend plan van Mike Foppen (olympisch 5000 m-atleet) voor de NN Zevenheuvelenloop in Nijmegen. Drie sessies per week — rustige duurloop (RD), tempoloop (DT) en intervallen (INT) — allemaal voorgeschreven op duur en inspanning in plaats van tempozones. Vast schema: vereist alleen een wedstrijddatum op zondag. De keuzes voor dagen-per-week en dag van de lange duurloop worden genegeerd.",
    "Runners targeting the NN Zevenheuvelenloop (15 km hilly race, Nijmegen).":
        "Lopers die de NN Zevenheuvelenloop willen lopen (heuvelachtige 15 km-wedstrijd, Nijmegen).",
    "18-week marathon build, ~55 mi (88 km) peak. Medium-long runs + lactate threshold.":
        "18-weeks marathonopbouw, piek van ~55 mi (88 km). Middellange duurlopen + lactaatdrempel.",
    "Pete Pfitzinger's marathon methodology (Advanced Marathoning): four mesocycles over 18 weeks — endurance, lactate-threshold, race preparation, taper. The signature is the mid-week medium-long run stacked alongside a weekend long run, threshold tempos, VO₂max intervals, marathon-pace long runs, and 2 tune-up races. Paces are calibrated to your VDOT; volume ramps from your base toward the ~88 km peak. Owns its 5-day/week schedule (days-per-week selector is ignored).":
        "De marathonmethodologie van Pete Pfitzinger (Advanced Marathoning): vier mesocycli over 18 weken — uithoudingsvermogen, lactaatdrempel, wedstrijdvoorbereiding en taper. Kenmerkend is de middellange duurloop doordeweeks naast een lange duurloop in het weekend, drempeltempo's, VO₂max-intervallen, marathontempo-duurlopen en 2 test-wedstrijden. Tempo's worden gekalibreerd op je VDOT; het volume loopt op vanaf je basis naar de piek van ~88 km. Heeft een vast 5-dagen/week-schema (de dagen-per-week-keuze wordt genegeerd).",
    "Marathoners who can build toward higher mileage and want a proven, structured 18-week plan.":
        "Marathoners die naar meer kilometers kunnen opbouwen en een bewezen, gestructureerd 18-weeks plan willen.",
    "Step-up plans by experience tier. Beginner-friendly.":
        "Opbouwende plannen per ervaringsniveau. Beginnersvriendelijk.",
    "Higdon's plans (Novice 1/2, Intermediate 1/2, Advanced 1/2) are simple, battle-tested, and use minimal quality work — mostly steady mileage with one long run. A solid choice if you don't want to think about VDOT zones. Pick your experience tier; the marathon build runs 18 weeks, the half 12. Owns its weekly schedule (day pickers are ignored).":
        "Higdons plannen (Novice 1/2, Intermediate 1/2, Advanced 1/2) zijn eenvoudig, beproefd en gebruiken minimaal kwaliteitswerk — vooral gestage kilometers met één lange duurloop. Een prima keuze als je niet met VDOT-zones bezig wilt zijn. Kies je ervaringsniveau; de marathonopbouw duurt 18 weken, de halve 12. Heeft een eigen weekschema (de dagkeuzes worden genegeerd).",
    "First-timers and runners who prefer a low-complexity schedule.":
        "Debutanten en lopers die een eenvoudig schema verkiezen.",
    "The classic 9-week run/walk on-ramp — from zero to 30 minutes of running.":
        "De klassieke 9-weekse ren/wandel-opbouw — van nul naar 30 minuten hardlopen.",
    "Three time-based sessions a week alternating running and walking, ramping from 8×1-minute runs to a continuous 30-minute (~5 km) graduation run. No paces, no zones — effort cues only. The gold-standard start for absolute beginners: every session opens and closes with a 5-minute brisk walk, and the walk breaks do the injury-proofing that a new runner's tendons need.":
        "Drie tijdgebaseerde sessies per week, afwisselend hardlopen en wandelen, oplopend van 8×1 minuut hardlopen naar een aaneengesloten afstudeer-run van 30 minuten (~5 km). Geen tempo's, geen zones — alleen inspanningscues. Dé gouden standaard voor absolute beginners: elke sessie begint en eindigt met 5 minuten stevig wandelen, en de wandelpauzes beschermen precies de pezen die een nieuwe loper moet opbouwen.",
    "Absolute beginners and returners after a long layoff.":
        "Absolute beginners en herstarters na een lange pauze.",
    # Higdon experience-tier picker (tier labels stay English by design; the
    # sub-descriptions get translated like the methodology-card copy).
    "Experience level": "Ervaringsniveau",
    "New to the distance. Easy runs + one long run. No speedwork.":
        "Nieuw op deze afstand. Rustige duurlopen + één lange duurloop. Geen snelheidswerk.",
    "A step up: adds mid-week goal-pace running.":
        "Een stap hoger: doeltempo doordeweeks erbij.",
    "Five days a week; back-to-back weekend runs, two 20-milers.":
        "Vijf dagen per week; weekendlopen op opeenvolgende dagen, twee duurlopen tot 32 km.",
    "More volume + a weekly tempo. Three 20-milers.":
        "Meer volume + een wekelijkse tempoloop. Drie duurlopen tot 32 km.",
    "Six days: hills, goal-pace, and tempo work.":
        "Zes dagen: heuvels, doeltempo en tempowerk.",
    "Highest volume: 800 m speed, tempo, goal-pace.":
        "Hoogste volume: 800 m snelheid, tempo, doeltempo.",
    "Daniels paces, Hansons-style cumulative fatigue.":
        "Daniels-tempo's, cumulatieve vermoeidheid in Hansons-stijl.",
    "Borrow Daniels' pace zones for precision, but follow Hansons' philosophy: cap the long run around 30% of weekly volume and move more of that volume to mid-week medium-long runs. Trains marathon-specific fatigue resistance without an oversized weekend long run.":
        "Leen Daniels' tempozones voor precisie, maar volg de filosofie van Hansons: houd de lange duurloop rond 30% van het weekvolume en verschuif meer volume naar middellange duurlopen doordeweeks. Traint marathonspecifieke vermoeidheidsweerstand zonder een overdreven lange duurloop in het weekend.",
    "Marathoners who want long-run fatigue training without the 32 km weekly grind.":
        "Marathoners die vermoeidheidstraining uit lange duurlopen willen zonder de wekelijkse sleur van 32 km.",
    # ── Plan settings modal: schedule & race-date reshape ───────────
    "Schedule & race date": "Schema & wedstrijddatum",
    "This methodology owns its weekly schedule — only the race date can move. Changing it rebuilds every upcoming workout around the new date;":
        "Deze methodologie bepaalt zijn eigen weekschema — alleen de wedstrijddatum kan verschuiven. Een wijziging bouwt elke komende training opnieuw op rond de nieuwe datum;",
    "Rebuilds every upcoming workout on the new days;":
        "Bouwt elke komende training opnieuw op op de nieuwe dagen;",
    "past weeks and completed runs stay exactly as they are. Upcoming workouts already on your watch are removed from Garmin — re-push the weeks you want.":
        "afgelopen weken en voltooide trainingen blijven precies zoals ze zijn. Komende trainingen die al op je horloge staan worden uit Garmin verwijderd — push de gewenste weken opnieuw.",
    "Reshape all upcoming workouts? Past weeks and completed runs are kept; upcoming pushed workouts are removed from Garmin.":
        "Alle komende trainingen hervormen? Afgelopen weken en voltooide trainingen blijven behouden; komende gepushte trainingen worden uit Garmin verwijderd.",
    "Race date": "Wedstrijddatum",
    "Pick exactly {want} training days (currently {n}).":
        "Kies precies {want} trainingsdagen (nu {n}).",
    "Reshape future weeks": "Komende weken hervormen",
    "Yes, reshape": "Ja, hervormen",
    "Plan reshaped:": "Plan hervormd:",
    "upcoming workout rebuilt on the new schedule.":
        "komende training opnieuw opgebouwd volgens het nieuwe schema.",
    "upcoming workouts rebuilt on the new schedule.":
        "komende trainingen opnieuw opgebouwd volgens het nieuwe schema.",
    "Past weeks and completed runs were kept.":
        "Afgelopen weken en voltooide trainingen zijn behouden.",
    "{n} pushed workouts removed from Garmin — re-push the weeks you want on the watch.":
        "{n} gepushte trainingen uit Garmin verwijderd — push de gewenste weken opnieuw naar het horloge.",
    "Couldn't reshape the plan:": "Kon het plan niet hervormen:",
    "{n} strength session(s) are still on your watch and were kept — remove them from the session first, or reconnect Garmin and try again.":
        "{n} krachttraining(en) staan nog op je horloge en zijn bewaard — verwijder ze eerst via de sessie, of verbind Garmin opnieuw en probeer het nog eens.",
    "Garmin isn't connected, so nothing was removed from your watch.":
        "Garmin is niet verbonden, dus er is niets van je horloge verwijderd.",
    "Couldn't remove it from Garmin: {error}": "Kon het niet uit Garmin verwijderen: {error}",
    "Couldn't remove it from Garmin — it's still on your watch. Try again.":
        "Kon het niet uit Garmin verwijderen — het staat nog op je horloge. Probeer het opnieuw.",
    "Removed from your watch.": "Van je horloge verwijderd.",
    "That session wasn't on your watch.": "Die sessie stond niet op je horloge.",
    "{n} could not be removed from Garmin — delete them by hand in Garmin Connect.":
        "{n} konden niet uit Garmin worden verwijderd — verwijder ze handmatig in Garmin Connect.",
    "{n} could not be updated on Garmin — the old pace is still on your watch. Try again once Garmin is reachable.":
        "{n} konden niet in Garmin worden bijgewerkt — het oude tempo staat nog op je horloge. Probeer het opnieuw zodra Garmin bereikbaar is.",
    "Pushed to your watch.": "Naar je horloge gestuurd.",
    "Uploaded to Garmin, but scheduling it on {date} failed — it won't reach your watch for that day. Try pushing again.":
        "Geüpload naar Garmin, maar inplannen op {date} is mislukt — hij komt die dag niet op je horloge. Probeer opnieuw te pushen.",
    "Couldn't remove {n} workout(s) from Garmin — they're still on your watch. Deactivate again to retry.":
        "Kon {n} training(en) niet uit Garmin verwijderen — ze staan nog op je horloge. Deactiveer opnieuw om het nog eens te proberen.",
    "Couldn't remove {n} workout(s) from Garmin before deleting the plan. Remove them by hand in Garmin Connect.":
        "Kon {n} training(en) niet uit Garmin verwijderen vóór het plan werd gewist. Verwijder ze handmatig in Garmin Connect.",

    # Schedule fields
    "Schedule": "Schema",
    "This methodology follows its own fixed schedule — shown below for reference, anchored to your race day.":
        "Deze methodologie volgt een eigen vast schema — hieronder ter referentie, verankerd aan je wedstrijddag.",
    "Race date (skip for Stay fit)": "Wedstrijddatum (overslaan bij Fit blijven)",
    "Target time (optional)": "Doeltijd (optioneel)",
    "h": "u",
    "Days per week": "Dagen per week",
    "Training days": "Trainingsdagen",
    "long run": "lange duurloop",
    "Plan name (optional)": "Plannaam (optioneel)",
    "e.g. Amsterdam Marathon 2026": "bijv. Amsterdam Marathon 2026",
    "Extras": "Extra's",
    "Add optional core / strength sessions on rest days":
        "Voeg optionele core-/krachtsessies toe op rustdagen",
    "Bodyweight only. Rotates 4 sessions across rest days; the day after any tempo / intervals / long run gets a recovery & mobility session instead. You can toggle this off later from plan settings.":
        "Alleen met lichaamsgewicht. Rouleert 4 sessies over de rustdagen; de dag na een tempo / interval / lange duurloop krijgt in plaats daarvan een herstel- & mobiliteitssessie. Je kunt dit later uitzetten bij de planinstellingen.",
    "Generate plan": "Plan genereren",
    # Training-day picker hints (rendered client-side)
    "of": "van",
    "Pick 1 more day.": "Kies nog 1 dag.",
    "Pick {n} more days.": "Kies nog {n} dagen.",
    "Uncheck {n}.": "Vink er {n} uit.",

    # ── Plans — list / detail page (hero, stats, phase bar, archive) ─
    # Post-action status banners (query-param driven).
    "future workout re-paced from your current VDOT.": "toekomstige training opnieuw ingedeeld op basis van je huidige VDOT.",
    "future workouts re-paced from your current VDOT.": "toekomstige trainingen opnieuw ingedeeld op basis van je huidige VDOT.",
    "Refreshed stale pace numbers in": "Verouderde tempowaarden ververst in",
    "workout description.": "trainingsbeschrijving.",
    "workout descriptions.": "trainingsbeschrijvingen.",
    "Nothing to recalibrate — already in sync.": "Niets te herkalibreren — al gelijk.",
    "{n} re-pushed to Garmin.": "{n} opnieuw naar Garmin gestuurd.",
    "VDOT updated to": "VDOT bijgewerkt naar",
    "was {old}": "was {old}",
    "Recalibrate paces to apply the new prescriptions across future workouts.":
        "Herkalibreer de tempo's om de nieuwe voorschriften op toekomstige trainingen toe te passen.",
    "Open plan settings →": "Planinstellingen openen →",
    # Hero + actions
    "Deactivate this plan? It will move to the archive and you can start a new one.":
        "Dit plan deactiveren? Het verhuist naar het archief en je kunt een nieuw plan starten.",
    "PLAN · {n} WEEKS": "PLAN · {n} WEKEN",
    "← Back to plans": "← Terug naar plannen",
    "Created {date}.": "Aangemaakt {date}.",
    "Created {date}, ended {end}.": "Aangemaakt {date}, beëindigd {end}.",
    "VDOT {vdot} at start.": "VDOT {vdot} bij start.",
    # Race stat cell (plan detail)
    "in {n} d": "over {n} d",
    "{n} d ago": "{n} d geleden",
    "no date": "geen datum",
    # Plan status (active exists already → "actief")
    "archived": "gearchiveerd",
    # Phase-bar legend + tooltips
    "base": "basis",
    "build": "opbouw",
    "taper": "taper",
    "race": "wedstrijd",
    "maintain": "onderhoud",
    # Archive rows
    "created {date}": "aangemaakt {date}",
    "ended {date}": "beëindigd {date}",
    "Delete this plan permanently? This removes the plan and all its workouts.":
        "Dit plan definitief verwijderen? Dit verwijdert het plan en al zijn trainingen.",
    "Delete this plan permanently": "Dit plan definitief verwijderen",

    # ── Week cards ──────────────────────────────────────────────────
    "THIS WEEK": "DEZE WEEK",
    "km · {n} sess": "km · {n} sess",
    "Push this week →": "Deze week pushen →",
    "Push every pushable workout in this week to Garmin":
        "Elke pushbare training van deze week naar Garmin sturen",
    "skipped": "overgeslagen",
    "failed": "mislukt",
    "Cross": "Cross",
    # Previous-weeks toggle
    "Show {n} previous week": "{n} vorige week tonen",
    "Show {n} previous weeks": "{n} vorige weken tonen",
    "Hide previous weeks": "Vorige weken verbergen",
    "↓ Weeks": "↓ Weken",

    # ── Plan-workout modal (day popup) ──────────────────────────────
    "✓ done": "✓ gedaan",
    "✓ on watch": "✓ op horloge",
    "Steps": "Stappen",
    "jog": "jog",
    "pace": "tempo",
    "Actual": "Werkelijk",
    "Coach suggests": "Coach adviseert",
    "Apply swap →": "Wissel toepassen →",
    "Send to Garmin": "Naar Garmin sturen",
    "Uploads this workout to Garmin Connect and schedules it on {date} so it appears on your watch.":
        "Uploadt deze training naar Garmin Connect en plant hem op {date} zodat hij op je horloge verschijnt.",
    "Send to watch →": "Naar horloge sturen →",
    "On watch": "Op horloge",
    "Pushed {date}. The session is on your Garmin device.":
        "Gepusht op {date}. De sessie staat op je Garmin-apparaat.",
    "Manual edit": "Handmatig aanpassen",
    "This workout is on your watch. Saving will delete the Garmin copy and re-upload the new shape.":
        "Deze training staat op je horloge. Bij opslaan wordt de Garmin-kopie verwijderd en de nieuwe vorm opnieuw geüpload.",
    "Warm-up": "Warming-up",
    "Cool-down": "Cooling-down",
    "Distance (km)": "Afstand (km)",
    "Pace (mm:ss/km)": "Tempo (mm:ss/km)",
    "Work": "Werk",
    "Reps": "Herhalingen",
    "Per rep (mm:ss)": "Per herhaling (mm:ss)",
    # Time-based (run/walk) edit form
    "recovery": "herstel",
    "Warm-up walk": "Warming-up wandelen",
    "Cool-down walk": "Cooling-down wandelen",
    "Recovery walk": "Herstelwandeling",
    "Run": "Hardlopen",
    "Time (mm:ss)": "Tijd (mm:ss)",
    "This session is a hand-crafted run/walk ladder — field-by-field editing can't represent it. Move it to another day, or simply adjust the blocks by feel on the run.":
        "Deze sessie is een handgemaakte ren/wandel-ladder — veld-voor-veld aanpassen kan die vorm niet weergeven. Verplaats hem naar een andere dag, of pas de blokken op gevoel aan tijdens het lopen.",
    "Pacing": "Tempo",
    "by effort": "op inspanning",
    "Save & re-push →": "Opslaan & opnieuw pushen →",
    "Save changes": "Wijzigingen opslaan",
    "Move to a different day": "Naar een andere dag verplaatsen",
    "If the target day already has a workout, the two will swap. Stays within the plan window.":
        "Als de doeldag al een training heeft, wisselen de twee. Blijft binnen de planperiode.",
    "New date": "Nieuwe datum",
    "Move →": "Verplaatsen →",
    "This workout is already completed — edits are locked. The matched activity is the source of truth.":
        "Deze training is al voltooid — aanpassen is vergrendeld. De gekoppelde activiteit is de bron van waarheid.",

    # ── Workout narrative (docs/workout-narrative.md) ───────────────
    # The coach-voice walkthrough at the top of the plan-workout modal,
    # assembled sentence-by-sentence by runsphera/plans/narrative.py.
    # Keep the {placeholders} — they carry distances, paces and rep counts,
    # and they're formatted *after* the lookup so word order is free to move.
    # Zone names (easy (E), interval (I), …) and pace strings stay English by
    # convention — same as the methodology explainers.
    # Durations
    "{n} seconds": "{n} seconden",
    "1 minute": "1 minuut",
    "{n} minutes": "{n} minuten",
    "{m}:{s} min": "{m}:{s} min",
    # Warm-up / cool-down
    "You'll start with an easy {amount} warm-up to gradually bring your body up to speed for the work ahead.":
        "Je begint met een rustige warming-up van {amount} om je lichaam geleidelijk op gang te brengen voor het werk dat komt.",
    "You'll start with {amount} of easy warm-up to gradually bring your body up to speed for the work ahead.":
        "Je begint met {amount} rustig inlopen om je lichaam geleidelijk op gang te brengen voor het werk dat komt.",
    "You'll start with {amount} of easy warm-up — a brisk walk or gentle jog — to loosen your legs before the work starts.":
        "Je begint met {amount} rustige warming-up — stevig wandelen of licht dribbelen — om je benen los te maken voordat het werk begint.",
    "You'll finish with a relaxed {amount} cool-down to ease your body back down and start the recovery.":
        "Je sluit af met een ontspannen cooling-down van {amount} om je lichaam rustig terug te brengen en het herstel op gang te helpen.",
    "You'll finish with {amount} of relaxed cool-down to ease your body back down and start the recovery.":
        "Je sluit af met {amount} rustig uitlopen om je lichaam terug te brengen en het herstel op gang te helpen.",
    # Repeats
    "After warming up, you'll run {reps} repetitions of {amount} at your {zone} pace of {pace}.":
        "Na de warming-up loop je {reps} herhalingen van {amount} op je {zone}-tempo van {pace}.",
    "The main set is {reps} repetitions of {amount} at your {zone} pace of {pace}.":
        "Het hoofdwerk bestaat uit {reps} herhalingen van {amount} op je {zone}-tempo van {pace}.",
    "After warming up, you'll run {reps} repetitions of {amount}, at an effort you can hold just as well on the last one as on the first.":
        "Na de warming-up loop je {reps} herhalingen van {amount}, op een inspanning die je bij de laatste net zo goed volhoudt als bij de eerste.",
    "The main set is {reps} repetitions of {amount}, at an effort you can hold just as well on the last one as on the first.":
        "Het hoofdwerk bestaat uit {reps} herhalingen van {amount}, op een inspanning die je bij de laatste net zo goed volhoudt als bij de eerste.",
    "Between each effort, take {rec} of easy jogging to recover and get ready for the next one.":
        "Tussen elke inspanning door dribbel je {rec} rustig uit om te herstellen en klaar te zijn voor de volgende.",
    "Between each effort, walk or jog gently for {rec} until your breathing settles.":
        "Tussen elke inspanning door wandel of dribbel je {rec} rustig tot je ademhaling weer tot rust komt.",
    # Continuous work
    "After warming up, you'll run {amount} at your {zone} pace of {pace} — one continuous block, holding the effort steady all the way through.":
        "Na de warming-up loop je {amount} op je {zone}-tempo van {pace} — één aaneengesloten blok, waarbij je de inspanning de hele tijd gelijk houdt.",
    "The session is {amount} at your {zone} pace of {pace}, held steady all the way through.":
        "De sessie is {amount} op je {zone}-tempo van {pace}, van begin tot eind gelijkmatig gelopen.",
    "After warming up, you'll run {amount} at a controlled, steady effort.":
        "Na de warming-up loop je {amount} op een beheerste, gelijkmatige inspanning.",
    "The session is {amount} of running at a controlled, steady effort.":
        "De sessie is {amount} lopen op een beheerste, gelijkmatige inspanning.",
    "You'll run the first {first} at your {zone1} pace of {pace1}, then pick it up for the final {last} at your {zone2} pace of {pace2}.":
        "De eerste {first} loop je op je {zone1}-tempo van {pace1}, daarna trek je aan voor de laatste {last} op je {zone2}-tempo van {pace2}.",
    # Ladders (hand-built run/walk weeks)
    "The main set runs as a ladder of {n} blocks: {blocks}, with an easy walk or jog between them.":
        "Het hoofdwerk is een ladder van {n} blokken: {blocks}, met daartussen rustig wandelen of dribbelen.",
    "run {amount}": "{amount} lopen",
    "walk {amount}": "{amount} wandelen",
    "The main set alternates in this order: {blocks}. Follow the sequence as written — the walk breaks are what let the running blocks grow.":
        "Het hoofdwerk wisselt af in deze volgorde: {blocks}. Volg de reeks zoals hij staat — juist de wandelpauzes maken dat de loopblokken kunnen groeien.",
    # Structureless easy running
    "Today is {amount} at your easy (E) pace of {pace}. Keep it conversational — if you couldn't hold a chat, you're going too fast.":
        "Vandaag loop je {amount} op je easy (E)-tempo van {pace}. Houd het op gesprekstempo — kun je geen gesprek voeren, dan ga je te hard.",
    "Today is {amount} at an easy, conversational effort.":
        "Vandaag loop je {amount} op een rustige inspanning, op gesprekstempo.",
    "Today is {amount} of running at an easy, conversational effort.":
        "Vandaag loop je {amount} op een rustige inspanning, op gesprekstempo.",
    # Why you're doing this — the closing paragraph
    "This session is built to raise your VO₂max — the ceiling on your aerobic capacity. Repeats at this intensity train your body to take in and use oxygen faster, which makes every slower pace feel easier.":
        "Deze sessie is bedoeld om je VO₂max te verhogen — het plafond van je aerobe capaciteit. Herhalingen op deze intensiteit trainen je lichaam om sneller zuurstof op te nemen en te gebruiken, waardoor elk rustiger tempo lichter gaat voelen.",
    "Short and fast, this one sharpens your speed, running economy and form. The goal is to move quickly and smoothly — not to get tired.":
        "Kort en snel: deze sessie scherpt je snelheid, loopeconomie en techniek aan. Het doel is soepel en vlot bewegen — niet moe worden.",
    "Threshold work lifts the pace you can hold before lactate starts to pile up. It's the single biggest lever on how fast you can race anything from 10 km upward.":
        "Drempelwerk verhoogt het tempo dat je kunt volhouden voordat het lactaat zich begint op te stapelen. Het is de grootste knop waar je aan kunt draaien voor elke wedstrijd vanaf 10 km.",
    "Running at goal marathon pace is a rehearsal for race day: it teaches your body to burn fuel efficiently at exactly the effort you'll be holding for hours.":
        "Lopen op je marathondoeltempo is een generale repetitie voor de wedstrijddag: het leert je lichaam brandstof efficiënt te verbranden op precies de inspanning die je uren gaat volhouden.",
    "The long run is the backbone of your endurance. It grows capillaries, toughens connective tissue and trains your body to burn fat for fuel — adaptations that only come from time on your feet.":
        "De lange duurloop is de ruggengraat van je uithoudingsvermogen. Hij laat haarvaten groeien, maakt bindweefsel sterker en leert je lichaam vet als brandstof te verbranden — aanpassingen die alleen komen van tijd op de benen.",
    "Finishing a long run at marathon pace is the closest thing to race day in the whole plan: it rehearses goal effort on legs that are already tired, which is exactly what the last 10 km will ask of you.":
        "Een lange duurloop afsluiten op marathontempo komt het dichtst bij de wedstrijddag van het hele plan: je oefent je doelinspanning op benen die al moe zijn — precies wat de laatste 10 km van je gaat vragen.",
    "Easy running is where most of your aerobic engine actually gets built. It looks unremarkable, but this is the volume that lets the hard sessions land.":
        "Rustig lopen is waar je aerobe motor grotendeels wordt gebouwd. Het oogt onopvallend, maar juist dit volume zorgt dat de zware sessies aankomen.",
    "This is active recovery — gentle movement to clear out the fatigue from your last hard session. Running it faster than easy only delays the adaptation you're waiting on.":
        "Dit is actief herstel — rustig bewegen om de vermoeidheid van je vorige zware sessie eruit te werken. Harder lopen dan rustig stelt de aanpassing waar je op wacht alleen maar uit.",
    "Race day. Everything in the plan has been pointing at this — run your own effort, start conservatively, and trust the work you've put in.":
        "Wedstrijddag. Alles in het plan wees hiernaartoe — loop je eigen inspanning, begin behoudend en vertrouw op het werk dat je hebt verzet.",
    "Rest is when training turns into fitness. Take the day fully off, or keep it gentle — a walk, a swim, an easy bike ride.":
        "Rust is het moment waarop training in vorm verandert. Neem de dag helemaal vrij, of houd het licht — een wandeling, een baantje zwemmen, rustig fietsen.",
    "Breaking the work into repeats with recovery in between lets you spend time at a harder effort than you could hold continuously — that's what builds both speed and aerobic fitness. Run every rep at the same effort: the last one should look like the first.":
        "Het werk opdelen in herhalingen met herstel ertussen laat je tijd doorbrengen op een zwaardere inspanning dan je aaneengesloten zou volhouden — en juist dat bouwt zowel snelheid als aerobe fitheid op. Loop elke herhaling op dezelfde inspanning: de laatste hoort eruit te zien als de eerste.",

    # ── Plan-settings modal ─────────────────────────────────────────
    "PLAN · ID {id}": "PLAN · ID {id}",
    "RACE {date}": "WEDSTRIJD {date}",
    "Plan settings": "Planinstellingen",
    "{n} days/wk": "{n} dagen/wk",
    "Name & notes": "Naam & notities",
    "Title": "Titel",
    "Optional. Anything you want to remember about why this plan exists, what to focus on, gotchas.":
        "Optioneel. Alles wat je wilt onthouden over waarom dit plan bestaat, waar je op moet letten, valkuilen.",
    "Include optional core / strength sessions on rest days":
        "Optionele core-/krachtsessies op rustdagen opnemen",
    "Bodyweight only. Rotates 4 sessions (core+hamstrings, full body, hip stability, plyometric power); the day after any tempo / intervals / long run gets a recovery & mobility session instead. Toggle off to clear future sessions.":
        "Alleen met lichaamsgewicht. Rouleert 4 sessies (core+hamstrings, hele lichaam, heupstabiliteit, plyometrische kracht); de dag na een tempo / interval / lange duurloop krijgt in plaats daarvan een herstel- & mobiliteitssessie. Zet uit om toekomstige sessies te wissen.",
    "Recalibrate paces": "Tempo's herkalibreren",
    "Rewrites every future workout's pace target from your current VDOT":
        "Herschrijft het tempodoel van elke toekomstige training op basis van je huidige VDOT",
    "against the canonical Daniels chart. Past workouts and completed runs stay locked.":
        "tegen de canonieke Daniels-tabel. Voltooide en verstreken trainingen blijven vergrendeld.",
    "Preview changes": "Wijzigingen bekijken",
    "Set VDOT": "VDOT instellen",
    "Garmin's VO₂max estimate is the default. If it doesn't match your race performance — Garmin tends to skew high — set the value here. Recalibrate paces afterwards.":
        "De VO₂max-schatting van Garmin is de standaard. Klopt die niet met je wedstrijdprestatie — Garmin schat vaak te hoog in — stel de waarde dan hier in. Herkalibreer daarna de tempo's.",
    "Set plan VDOT to {value}? Recalibrate paces afterwards to apply the new prescriptions.":
        "Plan-VDOT instellen op {value}? Herkalibreer daarna de tempowaarden om de nieuwe voorschriften toe te passen.",
    "Yes, set VDOT": "Ja, VDOT instellen",
    "Current VDOT": "Huidige VDOT",
    "Save VDOT": "VDOT opslaan",
    "Estimate from a race time": "Schat op basis van een wedstrijdtijd",
    "Punch in any all-out race result and we'll compute the matching VDOT via Daniels' formula.":
        "Voer een all-out wedstrijdresultaat in en we berekenen de bijbehorende VDOT via Daniels' formule.",
    "Hours": "Uren",
    "Minutes": "Minuten",
    "Seconds": "Seconden",
    "Calculate": "Berekenen",
    "Use this VDOT": "Gebruik deze VDOT",
    "(needs a valid time)": "(geldige tijd nodig)",
    "Schedule & race date": "Schema & wedstrijddatum",
    "Change training days, long-run day, or race date — those reshape future weeks. Coming next.":
        "Trainingsdagen, dag van de lange duurloop of wedstrijddatum wijzigen — die hervormen toekomstige weken. Komt binnenkort.",
    "Goal & methodology": "Doel & methodologie",
    "Switching the goal (marathon → half) or the methodology (Daniels → another) changes the entire plan shape — easier to":
        "Het doel (marathon → halve) of de methodologie (Daniels → een andere) wisselen verandert de hele planvorm — makkelijker om",
    "create a new plan": "een nieuw plan te maken",
    "than to refit this one.": "dan om dit plan om te bouwen.",

    # ── Recalibrate-paces preview ───────────────────────────────────
    "Every future workout already matches the current pace table — nothing to recalibrate.":
        "Elke toekomstige training komt al overeen met de huidige tempotabel — niets te herkalibreren.",
    "future workout would be re-paced.": "toekomstige training zou opnieuw worden ingedeeld.",
    "future workouts would be re-paced.": "toekomstige trainingen zouden opnieuw worden ingedeeld.",
    "has stale pace numbers in its notes that will be refreshed.":
        "heeft verouderde tempowaarden in de notities die worden ververst.",
    "have stale pace numbers in their notes that will be refreshed.":
        "hebben verouderde tempowaarden in hun notities die worden ververst.",
    "Past sessions ({past}) and already-completed runs ({done}) stay locked. Rest / cross days ({rest}) have no pace target.":
        "Verstreken sessies ({past}) en al voltooide runs ({done}) blijven vergrendeld. Rust-/crossdagen ({rest}) hebben geen tempodoel.",
    "Zone": "Zone",
    "New pace": "Nieuw tempo",
    "Interval": "Interval",
    "Repetition": "Herhaling",
    "Examples:": "Voorbeelden:",
    "Recalibrate {n} future workouts? Any manual pace tweaks you made will be overwritten.":
        "{n} toekomstige trainingen herkalibreren? Handmatige tempo-aanpassingen die je hebt gemaakt worden overschreven.",
    "Confirm & recalibrate": "Bevestig & herkalibreer",
    "workout": "training",
    "workouts": "trainingen",

    # ── Plan-strength modal ─────────────────────────────────────────
    "Bodyweight": "Lichaamsgewicht",
    "prescribed {lo}–{hi} min": "voorgeschreven {lo}–{hi} min",
    "max {n}": "max {n}",
    "training": "training",
    "Logged {when} · matched via Garmin workout id {id}":
        "Gelogd {when} · gekoppeld via Garmin workout-id {id}",
    "round": "ronde",
    "rounds": "rondes",
    "Superset": "Superset",
    "/side": "/kant",
    "reps": "herh.",
    "↺ Mark not done": "↺ Markeer als niet gedaan",
    "Completed {date}": "Voltooid {date}",
    "✓ Mark complete": "✓ Markeer als voltooid",
    "Remove this strength session from your Garmin Connect calendar":
        "Deze krachtsessie uit je Garmin Connect-kalender verwijderen",
    "↺ Unpush": "↺ Terugtrekken",
    "Push to Garmin so the watch can guide you through the session":
        "Naar Garmin pushen zodat het horloge je door de sessie kan leiden",
    "↗ Push to watch": "↗ Naar horloge pushen",

    # ── Week / workout cards ────────────────────────────────────────
    "Week {n}": "Week {n}",
    "Push to Garmin": "Naar Garmin pushen",
    "Pushed": "Gepusht",
    "Push": "Push",
    "Rest": "Rust",
    "Easy": "Rustig",
    "Long": "Lang",
    "Tempo": "Tempo",
    "Intervals": "Intervallen",
    "Recovery": "Herstel",
    "Race": "Wedstrijd",
    "Cross-training": "Crosstraining",
    "Strides": "Strides",
    # Pace-zone labels for per-segment editing of multi-pace long runs.
    "Marathon pace": "Marathontempo",
    "Threshold": "Drempel",
    "Half-marathon pace": "Halve-marathontempo",
    "Interval": "Interval",
    "Repetition": "Repetitie",
    "Segment": "Segment",
    "future": "toekomstig",
    "today": "vandaag",
    "done": "gedaan",
    "missed": "gemist",
    "rest": "rust",

    # ── Calendar ────────────────────────────────────────────────────
    "Calendar.": "Kalender.",
    "Save event": "Evenement opslaan",
    "Saved": "Opgeslagen",
    "Saved races": "Opgeslagen wedstrijden",
    "Your races": "Jouw wedstrijden",
    "Your races · in order": "Jouw wedstrijden · op volgorde",
    "saved · upcoming only": "opgeslagen · alleen aankomende",
    "Target": "Doel",
    "A-race": "A-wedstrijd",
    "Remove": "Verwijderen",
    "remove": "verwijderen",
    "Remove from your calendar": "Uit je kalender halen",
    "Delete “{name}” permanently? Cannot be undone.":
        "“{name}” permanent verwijderen? Kan niet worden teruggedraaid.",
    "All distances": "Alle afstanden",
    "Past": "Verleden",
    "Upcoming": "Aankomend",

    # ── Calendar → plan event swap ──────────────────────────────────
    "In your plan": "In je plan",
    "View in plan →": "Bekijk in plan →",
    'Run this event as part of "{title}" — it takes the place of a training day.':
        'Loop dit evenement als onderdeel van "{title}" — het komt in de plaats van een trainingsdag.',
    "Swap into plan": "Wissel in plan",
    'Add "{name}" ({label}) to your plan? It replaces "{title}" on {date}.':
        'Voeg "{name}" ({label}) toe aan je plan? Het vervangt "{title}" op {date}.',
    'Add "{name}" ({label}) to your plan? It lands on {date} — currently a rest day.':
        'Voeg "{name}" ({label}) toe aan je plan? Het valt op {date} — nu een rustdag.',
    "Also swap out a session that week": "Laat ook een training die week vervallen",
    "Nothing else — keep the rest of the week": "Niets anders — houd de rest van de week",
    "The session you swap out becomes a rest day. You can undo the whole swap later from the plan.":
        "De training die je laat vervallen wordt een rustdag. Je kunt de hele wissel later ongedaan maken vanuit het plan.",
    "Yes, add to plan": "Ja, voeg toe aan plan",
    "This event can't be added to your plan right now — reload the page and try again.":
        "Dit evenement kan nu niet aan je plan worden toegevoegd — ververs de pagina en probeer het opnieuw.",
    "Race event": "Wedstrijd",
    'Swapped in from your race calendar. It replaced "{title}".':
        'Ingewisseld vanuit je wedstrijdkalender. Het verving "{title}".',
    '"{title}" was turned into a rest day for it.':
        '"{title}" werd hiervoor een rustdag.',
    "Remove race & restore training": "Verwijder wedstrijd & herstel training",
    "Remove this race from the plan and restore the original workout(s)?":
        "Deze wedstrijd uit het plan verwijderen en de oorspronkelijke training(en) herstellen?",
    "Yes, restore": "Ja, herstel",
    "This day was freed up for {name}. Removing that race from the plan restores it.":
        "Deze dag is vrijgemaakt voor {name}. Als je die wedstrijd uit het plan verwijdert, komt deze training terug.",

    # ── Diary ───────────────────────────────────────────────────────
    "Diary.": "Dagboek.",
    "How did it go?": "Hoe ging het?",
    "How did it go? What did you notice? What's worth remembering?": "Hoe ging het? Wat viel je op? Wat is het waard om te onthouden?",
    "For date": "Voor datum",
    "Save entry": "Opslaan",
    "Coach is reading the file…": "De coach leest het dossier…",
    "Coach voice is unavailable right now. Check Settings → Coach voice.": "De coachstem is op dit moment niet beschikbaar. Kijk bij Instellingen → Stem van de coach.",
    "Try again": "Opnieuw proberen",
    "↻ Try again": "↻ Opnieuw proberen",
    "Manage key & usage on console.anthropic.com": "Beheer sleutel & verbruik op console.anthropic.com",
    "Manage key & usage on platform.openai.com": "Beheer sleutel & verbruik op platform.openai.com",
    "Manage key & usage on aistudio.google.com": "Beheer sleutel & verbruik op aistudio.google.com",
    "How did it feel?": "Hoe voelde het?",
    "What you made of it.": "Wat jij ervan vond.",
    "What happened out there? The wind, the legs, the head…": "Wat gebeurde er daar? De wind, de benen, het hoofd…",
    "A few words about how this run felt — weather, mental state, anything worth remembering.": "Een paar woorden over hoe deze run voelde — weer, mentale toestand, iets om te onthouden.",
    "Save to diary": "Opslaan in dagboek",
    "LAST SAVED · {time}": "LAATST OPGESLAGEN · {time}",
    "NOT SAVED YET": "NOG NIET OPGESLAGEN",
    "Mood": "Stemming",

    # Mood labels (mirror diary.MOOD_LABEL)
    "exhausted": "uitgeput",
    "tough": "zwaar",
    "okay": "oké",
    "good": "goed",
    "great": "geweldig",

    # ── Settings ───────────────────────────────────────────────────
    "Settings.": "Instellingen.",
    "Language": "Taal",
    "Choose the language for the UI and the coach voice.": "Kies de taal voor de UI en de stem van de coach.",
    "English": "Engels",
    "Nederlands": "Nederlands",
    "● Language saved.": "● Taal opgeslagen.",
    "Mode": "Modus",
    "Light": "Licht",
    "Dark": "Donker",
    "Auto": "Automatisch",
    "Account": "Account",
    "About you": "Over jou",
    "Home location": "Thuislocatie",
    "Location": "Locatie",
    "Resolved: {place}": "Herkend: {place}",
    "Clear": "Wissen",
    "City, country": "Stad, land",
    "API key": "API-sleutel",
    "Claude API key": "Claude API-sleutel",
    "Coach voice": "Stem van de coach",
    "The line under the dashboard, the weekly recap, the run reaction — all spoken by your chosen LLM. Switch any time; past generations stay.": "De zin onder je dashboard, het weekoverzicht, de loopreactie — uitgesproken door de LLM van jouw keuze. Wisselen kan altijd; eerdere berichten blijven bestaan.",
    "Active": "Actief",
    "free": "gratis",
    "paid": "betaald",
    "Save key": "Sleutel opslaan",
    "Source": "Bron",
    "Replace key": "Sleutel vervangen",
    "Paste your key": "Plak je sleutel",
    "via .env / environment": "via .env / omgeving",
    "Claude Opus 4.7 — the sharpest voice. Pay-as-you-go after a one-time $5 starter credit.": "Claude Opus 4.7 — de scherpste stem. Pay-as-you-go na een eenmalig $5 startkrediet.",
    "gpt-4o-mini — cheap and capable. Pay-as-you-go after the $5 starter credit (≈ €0.10/year at one call/day).": "gpt-4o-mini — goedkoop en goed. Pay-as-you-go na het $5 startkrediet (≈ €0,10/jaar bij één call per dag).",
    "Gemini 2.5 Flash — truly free on AI Studio (1500 req/day). Get a key at aistudio.google.com.": "Gemini 2.5 Flash — echt gratis via AI Studio (1500 req/dag). Haal een sleutel op aistudio.google.com.",
    "Use Anthropic for coach voice": "Gebruik Anthropic als coachstem",
    "Use OpenAI for coach voice": "Gebruik OpenAI als coachstem",
    "Use Gemini for coach voice": "Gebruik Gemini als coachstem",
    "Clear the saved Anthropic API key?": "Opgeslagen Anthropic API-sleutel verwijderen?",
    "Clear the saved OpenAI API key?": "Opgeslagen OpenAI API-sleutel verwijderen?",
    "Clear the saved Gemini API key?": "Opgeslagen Gemini API-sleutel verwijderen?",
    "Previous race": "Vorige wedstrijd",
    "Next race": "Volgende wedstrijd",
    "Go to race": "Ga naar wedstrijd",
    "RACE DAY": "WEDSTRIJDDAG",
    "RACE TOMORROW": "MORGEN RACE",
    "RACE RECAP": "RACE TERUGBLIK",
    "RACE WEEK": "RACEWEEK",
    "COUNTDOWN": "AFTELLEN",
    "On pace for": "Op koers voor",
    "via Garmin": "via Garmin",
    "Race readiness": "Wedstrijd-gereedheid",
    "ON TRACK": "OP SCHEMA",
    "BUILDING": "AAN HET OPBOUWEN",
    "BEHIND": "ACHTER",
    # Race-readiness breakdown popup — click the bar to see where the score
    # comes from. One row per component, plus the band-threshold footnote.
    "How is this score built up?": "Hoe is deze score opgebouwd?",
    "why?": "waarom?",
    "Plan adherence": "Plan-opvolging",
    "Recent quality": "Recente kwaliteit",
    "VDOT trend": "VDOT-trend",
    "Load balance (ACWR)": "Belastingsbalans (ACWR)",
    "Long-run base": "Lange-duurbasis",
    "{done} of {due} quality sessions done in {weeks} weeks":
        "{done} van {due} kwaliteitstrainingen afgerond in {weeks} weken",
    "no quality work was scheduled — neutral score":
        "geen kwaliteitswerk ingepland — neutrale score",
    "{n} sessions done in {weeks} weeks ({target} = full marks)":
        "{n} sessies afgerond in {weeks} weken ({target} = volle punten)",
    "{delta} VDOT vs {weeks} weeks ago": "{delta} VDOT t.o.v. {weeks} weken terug",
    "no VDOT history yet — half marks": "nog geen VDOT-historie — halve punten",
    # Decimal dots throughout: the rest of the app prints stats with a dot
    # in both languages, and a mixed "1.1 / 0,8-1,5" in one line reads wrong.
    "ratio {ratio} — sweet spot is 0.8-1.5": "ratio {ratio} — ideale zone is 0.8-1.5",
    "no load data yet — half marks": "nog geen belastingsdata — halve punten",
    "last {weeks} wks: longest {longest} km · plan asked {asked} km · race needs {target} km":
        "laatste {weeks} wk: langste {longest} km · plan vroeg {asked} km · race vraagt {target} km",
    "longest {longest} km in {weeks} wks · race needs {target} km, under {floor} km scores zero":
        "langste {longest} km in {weeks} wk · race vraagt {target} km, onder {floor} km is 0 punten",
    "no race distance set — neutral score":
        "geen wedstrijdafstand ingesteld — neutrale score",
    "{on_track}+ on track · {building}-{on_track_max} building · under {building} behind":
        "{on_track}+ op schema · {building}-{on_track_max} opbouwen · onder {building} achter",
    "Greyed rows score half marks — no data for them yet.":
        "Grijze regels krijgen halve punten — daar is nog geen data voor.",
    "FITNESS SIGNAL": "FITHEIDSSIGNAAL",
    "Your": "Je",
    "on": "op",
    "avg HR": "gem HR",
    "implies": "duidt op",
    "a": "een",
    "bump from your plan's": "stijging vanaf de",
    "Apply to recalibrate your plan paces?": "Toepassen om je tempo's bij te stellen?",
    "Apply to plan": "Toepassen op plan",
    "Dismiss": "Negeren",
    "today's the day": "vandaag is het zover",
    "day to go": "dag te gaan",
    "days until": "dagen tot",
    "yesterday": "gisteren",
    "{n} days ago": "{n} dagen geleden",
    "Saved ✓": "Opgeslagen ✓",
    "last updated": "laatst bijgewerkt",
    "What's on your mind today? How are the legs feeling? Sleep, stress, weather, anything.": "Hoe voel je je vandaag? Hoe voelen je benen? Slaap, stress, weer, alles is welkom.",
    "no rating": "geen waardering",
    "Save": "Opslaan",
    "Database": "Database",
    "● Set": "● Ingesteld",
    "● Not set": "● Niet ingesteld",

    # ── Settings page — banners + hero + status strip ─────────────
    "Claude API key saved.": "Claude API-sleutel opgeslagen.",
    "Claude API key cleared.": "Claude API-sleutel gewist.",
    "Your note was saved. Today's coach line will refresh on the next dashboard view.": "Je notitie is opgeslagen. De coachregel van vandaag wordt bij de volgende weergave van het dashboard ververst.",
    "Location saved.": "Locatie opgeslagen.",
    "Location cleared.": "Locatie gewist.",
    "Mode set to": "Modus gezet op",
    "Please enter a city or place name.": "Voer een stad of plaatsnaam in.",
    "Couldn't find that place. Try a more specific query — e.g. \"Wassenaar, Netherlands\".": "Plaats niet gevonden. Probeer een specifiekere zoekopdracht — bijv. \"Wassenaar, Nederland\".",
    "// Config · Local-first · Your machine only": "// Instellingen · Lokaal · Alleen op jouw apparaat",
    "The bits that make it yours. All of it lives in a SQLite file on this laptop — nothing leaves unless you copy it.": "De stukjes die het van jou maken. Alles staat in een SQLite-bestand op deze laptop — niets verlaat het apparaat tenzij je het zelf kopieert.",
    "System status": "Systeemstatus",
    "CONNECTED": "VERBONDEN",
    "OFFLINE": "OFFLINE",
    "ACTIVE": "ACTIEF",
    "IDLE": "INACTIEF",
    "NOT SET": "NIET INGESTELD",
    "sync": "sync",
    "not synced yet": "nog niet gesynchroniseerd",
    "Data": "Data",
    "runs": "runs",
    "entries": "items",

    # ── Settings page — section eyebrows + cards ─────────────────
    "Integrations": "Integraties",
    "Linked": "Gekoppeld",
    "Offline": "Offline",
    "Pulls activities, body battery, HRV, sleep. Pushes planned workouts back to your watch.": "Haalt activiteiten, body battery, HRV en slaap op. Stuurt geplande trainingen terug naar je horloge.",
    "Name": "Naam",
    "Last sync": "Laatste sync",
    "never": "nooit",
    "Activities": "Activiteiten",
    "imported": "geïmporteerd",
    "Sync now": "Synchroniseer nu",
    "Disconnect": "Verbinding verbreken",
    "Connect Garmin": "Verbind Garmin",
    "Disconnect Garmin? You will need to sign in again before the next sync. Cached data stays.": "Verbinding met Garmin verbreken? Je moet opnieuw inloggen voor de volgende sync. Opgeslagen gegevens blijven behouden.",
    "Idle": "Inactief",
    "The runner": "De loper",
    "First run": "Eerste run",
    "About you · ground truth for the coach": "Over jou · achtergrond voor de coach",
    "e.g. Managing a mild left-knee niggle. Morning runner, no time for doubles.": "bijv. Last van een lichte linkerknie. Ochtendloper, geen tijd voor dubbele trainingen.",
    "Save note": "Notitie opslaan",
    "Where you run": "Waar je loopt",
    "Drives the weather chip, the \"best window today\" line, and which race calendars get pulled.": "Stuurt het weerblokje, de regel \"beste moment vandaag\" en welke wedstrijdkalenders worden geladen.",
    "Primary": "Primair",
    "Not set": "Niet ingesteld",
    "Save a city to enable weather + race calendar filtering": "Sla een stad op voor weer en wedstrijdkalenderfiltering",
    "e.g. Wassenaar, Netherlands": "bijv. Wassenaar, Nederland",
    "Change": "Wijzigen",
    "Set": "Instellen",
    "Appearance": "Weergave",
    "Auto follows your OS; Light and Dark force the variant.": "Auto volgt je OS; Licht en Donker forceren de variant.",
    "Data · danger zone": "Data · gevarenzone",
    "Your data lives here": "Hier staat je data",
    "activities": "activiteiten",
    "diary entries": "dagboeknotities",
    "Export JSON": "Exporteer JSON",
    "Reset all": "Alles resetten",
    "JSON export — not yet wired": "JSON-export — nog niet gekoppeld",
    "Reset — not yet wired": "Reset — nog niet gekoppeld",

    # ── Body / wellbeing check-in (nav + tab + entry panel + cards) ──
    "Body": "Lichaam",
    "Body · structured wellbeing log · ground truth": "Lichaam · gestructureerd welzijnslogboek · achtergrond",
    "How's the body?": "Hoe voelt je lichaam?",
    "Tap any area you'd like to track. The coach will use this to keep your training honest with how your body actually feels.": "Tik op een gebied dat je wilt bijhouden. De coach gebruikt dit om je training eerlijk te houden met hoe je lichaam echt voelt.",
    "Quick log": "Snel loggen",
    "Region": "Regio",
    "Side": "Zijde",
    "Left": "Links",
    "Right": "Rechts",
    "Midline": "Middenlijn",
    "Type": "Type",
    "Severity": "Ernst",
    "Structure (optional)": "Structuur (optioneel)",
    "Note (optional)": "Notitie (optioneel)",
    "Log issue": "Logboekitem toevoegen",
    "Phase 2 stub. Phase 3 swaps this in for an interactive front+back body diagram.": "Fase 2 voorlopig. Fase 3 vervangt dit door een interactief lichaamsdiagram (voor + achter).",
    "Active issues": "Actieve klachten",
    "Recently resolved": "Recent opgelost",
    "peak": "piek",
    "resolved {n} days ago": "{n} dagen geleden opgelost",
    "Reopen": "Heropenen",
    "Trouble zones (last {n} days)": "Zorggebieden (laatste {n} dagen)",
    "flare-ups": "opflakkeringen",
    "All clear ✓": "Alles oké ✓",
    "No active issues. Log something above if anything's bothering you.": "Geen actieve klachten. Log hierboven iets als er iets dwarszit.",
    "{n} days open": "{n} dagen open",
    "improving": "verbeterend",
    "worsening": "verslechterend",
    "steady": "stabiel",
    "new": "nieuw",
    "Looks like this cleared up — close it?": "Lijkt opgelost — sluiten?",
    "Still bothering you?": "Heeft het nog steeds last?",
    "Update severity (0-10)": "Ernst bijwerken (0-10)",
    "Mark resolved": "Markeer als opgelost",
    "Update existing": "Bestaande bijwerken",
    "Active issue": "Actieve klacht",
    "Log new issue": "Nieuwe klacht loggen",
    "Update": "Bijwerken",
    # Phase: Claude Design's body-page port
    "BODY · STRUCTURED WELLBEING LOG": "LICHAAM · GESTRUCTUREERD WELZIJNSLOGBOEK",
    "Tap a region you want to keep an eye on. The coach uses this to keep your training": "Tik op een regio die je in de gaten wilt houden. De coach gebruikt dit om je training",
    "honest": "eerlijk",
    "about how your body actually feels.": "te houden over hoe je lichaam echt voelt.",
    "Tap any region on the body to log how it feels or update an existing note.": "Tik op een lichaamsregio om te loggen hoe het voelt of een bestaande notitie bij te werken.",
    "Body views": "Lichaamsweergaven",
    "Body view": "Lichaamsweergave",
    "body diagram": "lichaamsdiagram",
    "Diagram style": "Diagramstijl",
    "Silhouette": "Silhouet",
    "Anatomy": "Anatomie",
    "TAP A REGION — HOVER TO PREVIEW": "TIK EEN REGIO — BEWEEG VOOR PREVIEW",
    "Pick a spot.": "Kies een plek.",
    "Issue type": "Klachttype",
    "Log how it feels": "Log hoe het voelt",
    "Update issue": "Klacht bijwerken",
    "New entry for this region": "Nieuwe melding voor deze regio",
    "Add a note (optional)": "Voeg een notitie toe (optioneel)",
    "e.g. sharp on the long run, fine on easy days": "bijv. scherp op de lange duurloop, prima op rustige dagen",
    "Save update": "Update opslaan",
    "MONITOR": "MONITOR",
    "MANAGE": "BIJSTUREN",
    "REST + PHYSIO": "RUST + FYSIO",
    "clear": "geen",
    "Active issues": "Actieve klachten",
    "✓ {n} days without a flag · streak going": "✓ {n} dagen zonder klacht · reeks loopt",
    "All clear.": "Alles oké.",
    "Nothing flagged right now. Log something the moment it starts whispering — early beats sorry.": "Op dit moment niets te melden. Log iets zodra het begint te fluisteren — vroeg is beter dan sorry.",
    "improving": "verbeterend",
    "worsening": "verslechterend",
    "steady": "stabiel",
    "new": "nieuw",
    "Looks like this cleared up.": "Lijkt opgelost.",
    "CLOSE IT →": "SLUITEN →",
    "Still bothering you? No update in {n} days.": "Heeft het nog steeds last? Geen update in {n} dagen.",
    "UPDATE →": "BIJWERKEN →",
    "OPEN {n} DAYS": "OPEN {n} DAGEN",
    "MARK RESOLVED": "OPGELOST MARKEREN",
    "Resolved": "Opgelost",
    "RESOLVED": "OPGELOST",
    "PEAK": "PIEK",
    "REOPEN": "HEROPENEN",
    "When an issue clears, it lands here so you can spot patterns.": "Als een klacht is opgelost komt hij hier zodat je patronen kunt zien.",
    "Heatmap": "Heatmap",
    "LAST {n} DAYS": "LAATSTE {n} DAGEN",
    "AGGREGATE SEVERITY · HOVER FOR COUNTS": "AGGREGAAT-ERNST · BEWEEG VOOR AANTALLEN",
    "Window": "Venster",
    "Heatmap window": "Heatmap-venster",
    "Intensity": "Intensiteit",
    "LOW": "LAAG",
    "MODERATE": "MATIG",
    "HIGH": "HOOG",
    "Top zones": "Topgebieden",
    "No data in this window.": "Geen data in dit venster.",
    # Dashboard widget + daily prompt + run-detail auto-suggest
    "active": "actief",
    "BODY CHECK-IN": "LICHAAMSCHECK",
    "Anything new today?": "Iets nieuws vandaag?",
    "All good": "Alles oké",
    "Log something": "Log iets",
    "That felt harder than expected — anything bothering you?": "Dat voelde zwaarder dan verwacht — heeft iets last?",
    "Log it →": "Log het →",
    # Settings — body-in-LLM opt-out toggle
    "Body check-in shared with coach": "Lichaamscheck gedeeld met coach",
    "When on, your active body issues feed the coach's prompt so it can adjust prescriptions to how you actually feel. Off keeps the Body tab working but hides it from the coach.": "Aan: je actieve lichaamsklachten gaan mee in de prompt van de coach, zodat hij voorschriften kan aanpassen aan hoe je je echt voelt. Uit: het Lichaam-tabblad blijft werken maar de coach ziet het niet.",
    "Coach context updated.": "Coachcontext bijgewerkt.",
    "e.g. IT band, plantar fascia": "bijv. IT-band, plantar fascia",
    "e.g. after hill repeats Thursday": "bijv. na heuvelinterval donderdag",
    "e.g. {first}": "bijv. {first}",
    "No trouble zones in this window.": "Geen zorggebieden in dit venster.",
    # Issue type labels
    "Soreness": "Stijfheid",
    "Tight / stiff": "Strak / stug",
    "Sharp pain": "Scherpe pijn",
    "Dull ache": "Doffe pijn",
    "Numb / tingling": "Doof / tintelend",
    "Known injury": "Bekende blessure",
    # Phase 3: diagram + view toggle + entry panel
    "Front": "Voor",
    "Back": "Achter",
    "Front view of the body": "Vooraanzicht van het lichaam",
    "Back view of the body": "Achteraanzicht van het lichaam",
    "Body view": "Lichaamsweergave",
    "Active": "Actief",
    "History": "Historie",
    "Heatmap": "Heatmap",
    "Tap any region on the body to log or update an issue.": "Tik op een lichaamsregio om een klacht te loggen of bij te werken.",
    "Resolved (last 180 days)": "Opgelost (laatste 180 dagen)",
    "Nothing resolved yet.": "Nog niets opgelost.",
    "Window": "Venster",
    "Heatmap window": "Heatmap-venster",
    "days": "dagen",
    "Top zones": "Topgebieden",
    "No active issues. Tap a region above when something needs tracking.": "Geen actieve klachten. Tik op een regio hierboven als er iets bijgehouden moet worden.",
    "({n} days since last update)": "({n} dagen sinds laatste update)",
    "Update this issue": "Klacht bijwerken",
    "Severity (0-10)": "Ernst (0-10)",
    "Add note (optional)": "Notitie toevoegen (optioneel)",
    "e.g. felt sharp again on the long run": "bijv. weer scherp op de lange duurloop",
    "Cancel": "Annuleren",
    "Log a new issue": "Nieuwe klacht loggen",
    # Region labels (15) — used by slug_label() output
    "Foot": "Voet",
    "Heel": "Hiel",
    "Ankle": "Enkel",
    "Achilles": "Achillespees",
    "Shin": "Scheen",
    "Calf": "Kuit",
    "Knee": "Knie",
    "Quad": "Quadriceps",
    "Hamstring": "Hamstring",
    "Hip flexor": "Heupbuiger",
    "Glute": "Bilspier",
    "Lower back": "Onderrug",
    "Upper back": "Bovenrug",
    "Neck": "Nek",
    "Shoulder": "Schouder",

    # ── Run-detail modal ──────────────────────────────────────────
    "RUN DEBRIEF": "RUN-DEBRIEF",
    "Workout": "Training",
    "Route": "Route",
    "Effort": "Inspanning",
    "Notes": "Notities",
    # Run-detail v2 tabs + Replay header
    "Replay": "Opnieuw",
    "The Run": "De loop",
    "Log": "Logboek",
    # Uplifting glow headlines (varied per run). {km} = whole km.
    "Great work on the {km} km!": "Sterk werk op die {km} km!",
    "Nice running — {km} km done!": "Lekker gelopen — {km} km binnen!",
    "Strong session!": "Sterke sessie!",
    "Another {km} km in the bank!": "Weer {km} km in de benen!",
    "Well run!": "Goed gelopen!",
    "That's a wrap — great effort!": "Klaar — sterke inspanning!",
    "Boom — {km} km ticked off!": "Boem — {km} km afgevinkt!",
    "Nailed the prescription — active block at {pace}/km against a {target}/km call.":
        "Precies volgens plan — actief blok op {pace}/km tegen een doel van {target}/km.",
    "Active block came in {n} s/km over the {target}/km call — still money in the bank.":
        "Actief blok kwam {n} s/km boven het doel van {target}/km — nog steeds winst in de tank.",
    "{km} km at {pace} — in the books.": "{km} km op {pace} — bijgeschreven.",
    "✓ Target hit": "✓ Doel gehaald",
    "▲ {n} s/km over": "▲ {n} s/km erover",
    "The line you drew": "De lijn die je trok",
    "climb": "klim",
    "Start": "Start",
    "Finish": "Finish",
    # Verdict chip
    "● on target": "● op doel",
    "▼ {n} s/km · inside window": "▼ {n} s/km · binnen marge",
    "▼ {n} s/km · under target": "▼ {n} s/km · onder doel",
    "▲ {n} s/km · inside window": "▲ {n} s/km · binnen marge",
    "▲ {n} s/km · over target": "▲ {n} s/km · boven doel",
    # The Run: deeper numbers
    "Deeper numbers": "Diepere cijfers",
    "MOVED THIS RUN": "VERANDERD DEZE LOOP",
    "HOLDING STEADY": "STABIEL",
    "No benefit": "Geen effect",
    "Minor benefit": "Klein effect",
    "Maintaining": "Onderhoudend",
    "Improving": "Verbeterend",
    "Highly improving": "Sterk verbeterend",
    "Overreaching": "Overbelasting",
    # Log tab
    "From your watch": "Van je horloge",
    "Logged RPE · 1–10": "Gelogde RPE · 1–10",
    "How did it feel to you?": "Hoe voelde het voor jou?",
    "HALF": "HALVE",
    "Active block · vs prescription": "Actief blok · vs voorschrift",
    "▼ {n}s/km · under target": "▼ {n}s/km · onder doeltempo",
    "▲ {n}s/km · over target": "▲ {n}s/km · boven doeltempo",
    "● on target": "● op doel",
    "Target was": "Doel was",
    "You ran it bang on the prescription.": "Je liep precies volgens voorschrift.",
    "You ran it {n}s/km quicker — {qualifier}.": "Je liep {n}s/km sneller — {qualifier}.",
    "You ran it {n}s/km slower than target — {qualifier}.": "Je liep {n}s/km langzamer dan doel — {qualifier}.",
    "inside the window": "binnen de marge",
    "ahead of target": "voor op doel",
    "behind target": "achter op doel",
    "Regenerate the coach's take on this run": "Coachreactie op deze run opnieuw genereren",
    "Regenerate coach message": "Coach-bericht opnieuw genereren",
    "Regenerate this week's recap": "Weekoverzicht opnieuw genereren",
    "Per-lap pace": "Tempo per ronde",
    "WARM-UP": "WARMING-UP",
    "ACTIVE": "ACTIEF",
    "COOL-DOWN": "COOLING-DOWN",
    "RECOVERY": "HERSTEL",
    "TARGET {pace}": "DOEL {pace}",
    "Per-lap data not recorded": "Rondegegevens niet vastgelegd",
    "This run was synced before <b>per-lap tracking was enabled</b>, so there's no split-by-split chart. Distance, time and pace below are still accurate.": "Deze run is gesynchroniseerd voordat <b>rondetracking actief was</b>, dus er is geen ronde-voor-ronde grafiek. Afstand, tijd en tempo hieronder kloppen wel.",
    "DISTANCE": "AFSTAND",
    "TIME": "TIJD",
    "AVG PACE": "GEM TEMPO",
    "LOAD": "BELASTING",
    "Distance": "Afstand",
    "Time": "Tijd",
    "Pace": "Tempo",
    "Avg pace": "Gem tempo",
    "Training load": "Trainingsbelasting",
    "Fastest splits": "Snelste splits",
    "BEST {label}": "BESTE {label}",
    "How hard the engine worked.": "Hoe hard de motor werkte.",
    "AVG HR": "GEM HR",
    "MAX HR": "MAX HR",
    "AEROBIC TE": "AEROBE TE",
    "VO₂ MAX": "VO₂ MAX",
    "Cadence": "Cadans",
    "Elev": "Hoogte",
    "Power": "Vermogen",
    "Anaerobic TE": "Anaerobe TE",
    "Perceived effort · RPE": "Ervaren inspanning · RPE",
    "(from Garmin)": "(van Garmin)",
    "From Garmin": "Van Garmin",
    "Garmin feel": "Garmin-gevoel",

    # Zone labels for the HR section (Z1–Z5).
    "Z1 Recovery": "Z1 Herstel",
    "Z2 Easy": "Z2 Rustig",
    "Z3 Aerobic": "Z3 Aeroob",
    "Z4 Threshold": "Z4 Drempel",
    "Z5 VO₂": "Z5 VO₂",
    "Recovery": "Herstel",
    "Aerobic": "Aeroob",
    "Threshold": "Drempel",

    # ── Tip categories / readiness ─────────────────────────────────
    "GO": "GA",
    "CAUTION": "VOORZICHTIG",
    "EASY": "RUSTIG",
    "REST": "RUST",

    # ── Getting-started wizard ─────────────────────────────────────
    # See docs/onboarding.md. "← Back" is a distinct key from "Back"
    # (which maps to "Achter" for the body diagram's rear view) so the
    # wizard nav button reads "Terug", not "Achter".
    "Setup progress": "Voortgang",
    "Step": "Stap",
    "← Back": "← Terug",
    "Skip": "Overslaan",
    "Continue": "Doorgaan",
    "I'll finish later": "Ik maak dit later af",
    "Not now": "Niet nu",
    # Welcome step
    "Welcome, {name}!": "Welkom, {name}!",
    "Welcome to your running coach": "Welkom bij je hardloopcoach",
    "Let's get you set up in a couple of minutes. You can skip anything and finish later.":
        "Laten we je in een paar minuten op weg helpen. Je kunt alles overslaan en later afmaken.",
    "Connect Garmin Connect": "Verbind Garmin Connect",
    "Connect Garmin — or skip it and go manual": "Verbind Garmin — of sla over en ga handmatig",
    "Tell the coach your current fitness": "Vertel de coach je huidige fitheid",
    "Sync your recent training": "Synchroniseer je recente trainingen",
    "Set your first goal": "Stel je eerste doel in",
    "Optional: coach voice & weather": "Optioneel: coachstem & weer",
    "Let's go": "Aan de slag",
    # Garmin step
    "Garmin connected": "Garmin verbonden",
    "Your Garmin Connect session is active. Next, pull in your training history.":
        "Je Garmin Connect-sessie is actief. Haal nu je trainingsgeschiedenis op.",
    "Enter verification code": "Voer verificatiecode in",
    "Verification code": "Verificatiecode",
    "Start over": "Opnieuw beginnen",
    "Verify & connect": "Verifieer & verbind",
    "Sign in once. Only a session token is stored — never your password.":
        "Log één keer in. Alleen een sessietoken wordt bewaard — nooit je wachtwoord.",
    "Email": "E-mail",
    "Password": "Wachtwoord",
    "Connect": "Verbinden",
    "Connecting…": "Verbinden…",
    "I don't use Garmin": "Ik gebruik geen Garmin",
    # Fitness-baseline step
    "Your fitness baseline": "Je fitheid als startpunt",
    "Garmin has you at VO₂max ~{v} — your plan paces will be built from that.":
        "Garmin meet je VO₂max op ~{v} — de tempo's van je plan worden daarop gebaseerd.",
    "Nothing to fill in here — your training history covers it.":
        "Hier hoef je niets in te vullen — je trainingsgeschiedenis dekt het al.",
    "No Garmin data — no problem. Tell the coach a little about yourself so your training paces fit you instead of a default. Everything here is optional.":
        "Geen Garmin-gegevens — geen probleem. Vertel de coach iets over jezelf zodat je trainingstempo's bij jou passen in plaats van bij een standaardwaarde. Alles hier is optioneel.",
    "Your first name (for the greeting)": "Je voornaam (voor de begroeting)",
    "A recent race or hard time-trial result": "Een recente wedstrijd of stevige tijdrit",
    "The single best predictor of your training paces.":
        "De beste voorspeller van je trainingstempo's.",
    "Distance…": "Afstand…",
    "5 km": "5 km",
    "10 km": "10 km",
    "15 km": "15 km",
    "sec": "sec",
    "Saved: VDOT {v}": "Opgeslagen: VDOT {v}",
    "How many km do you currently run per week?": "Hoeveel km loop je op dit moment per week?",
    "e.g. 20": "bijv. 20",
    "Save & continue": "Opslaan & doorgaan",
    # Sync step
    "Connect to Garmin first.": "Verbind eerst met Garmin.",
    "Pulled {n} runs.": "{n} runs opgehaald.",
    "Your history is in. You can re-sync anytime from the dashboard.":
        "Je geschiedenis staat erin. Je kunt altijd opnieuw synchroniseren vanaf het dashboard.",
    "Pull your recent runs and daily metrics so the coach has something to work with.":
        "Haal je recente runs en dagelijkse gegevens op zodat de coach iets heeft om mee te werken.",
    "Syncing… this can take a moment.": "Synchroniseren… dit kan even duren.",
    # Optional extras step
    "Optional extras": "Optionele extra's",
    "Both optional — you can add them later in Settings.":
        "Beide optioneel — je kunt ze later toevoegen in Instellingen.",
    "set": "ingesteld",
    "Add an Anthropic API key so the coach writes your daily briefing. Rules-based coaching works without it.":
        "Voeg een Anthropic API-sleutel toe zodat de coach je dagelijkse briefing schrijft. Regelgebaseerde coaching werkt ook zonder.",
    "Coach voice enabled.": "Coachstem ingeschakeld.",
    "Used for the weather chip and run-time context.":
        "Gebruikt voor het weerblokje en context tijdens het lopen.",
    "City, Country": "Stad, land",
    # Goal finale
    "You're almost there, {name}!": "Je bent er bijna, {name}!",
    "You're almost there!": "Je bent er bijna!",
    "Now the best part — let's find the training plan that fits your goal, whether that's your first 5K or a marathon PB.":
        "Nu het beste deel — laten we het trainingsplan vinden dat bij jouw doel past, of dat nu je eerste 5 km is of een marathon-PR.",

    # ── Plan recommendation (docs/plan-recommendation.md) ──
    "Can you currently run 10 minutes non-stop?":
        "Kun je op dit moment 10 minuten aan één stuk hardlopen?",
    "Helps us point you at the right kind of plan — there is a great one either way.":
        "Helpt ons je naar het juiste soort plan te wijzen — er is hoe dan ook een goed plan voor je.",
    "Quick question so we can point you at the right plan: can you currently run 10 minutes non-stop?":
        "Snelle vraag zodat we je naar het juiste plan kunnen wijzen: kun je op dit moment 10 minuten aan één stuk hardlopen?",
    "Yes": "Ja",
    "Not yet": "Nog niet",
    "Recommended for you": "Aanbevolen voor jou",
    "A gentle run/walk build to your first 5K.":
        "Een rustige ren/wandel-opbouw naar je eerste 5 km.",
    "Your current volume suits a run/walk 5K build.":
        "Je huidige volume past bij een ren/wandel-opbouw naar 5 km.",
    "Simple structure while we learn your fitness.":
        "Eenvoudige structuur terwijl we je fitheid leren kennen.",
    "Steady, low-complexity structure that matches your volume.":
        "Gestage, eenvoudige structuur die past bij je volume.",
    "Real fitness data + solid volume — precise pace zones pay off.":
        "Echte fitheidsdata + solide volume — precieze tempozones lonen.",
    "Solid volume — add a fitness number for pace-zone training.":
        "Solide volume — voeg een fitheidsgetal toe voor training op tempozones.",
    "We've read your training — your plan's paces will be built from this.":
        "We hebben je trainingen gelezen — de tempo's van je plan worden hierop gebaseerd.",
    "Based on what you told us": "Op basis van wat je ons vertelde",
    "your plan's paces will be built from this.":
        "de tempo's van je plan worden hierop gebaseerd.",
    "We don't know your fitness yet, so plans will start from a cautious default (VDOT 45). Add a recent race result for paces that actually fit you.":
        "We kennen je fitheid nog niet, dus plannen starten met een voorzichtige standaardwaarde (VDOT 45). Voeg een recente wedstrijduitslag toe voor tempo's die echt bij je passen.",
    "Set my fitness": "Mijn fitheid instellen",
    "You already have an active plan — the builder lets you adjust or replace it.":
        "Je hebt al een actief plan — in de builder kun je het aanpassen of vervangen.",
    "Find my plan": "Vind mijn plan",

    # ── Garmin-less onboarding: plan builder + dashboard + settings ──
    "Built from what you told us:": "Gebaseerd op wat je ons vertelde:",
    "No fitness data yet — using a cautious default:":
        "Nog geen fitheidsgegevens — we gebruiken een voorzichtige standaardwaarde:",
    "baseline (your estimate).": "basis (jouw schatting).",
    "baseline (default).": "basis (standaardwaarde).",
    "Set your fitness baseline": "Stel je fitheid in",
    "for paces that actually fit you.": "voor tempo's die echt bij je passen.",
    "This methodology follows its own fixed schedule — shown below for reference, anchored to your race day (or the long-run day until a race is set).":
        "Deze methodiek volgt een eigen vast schema — hieronder ter referentie, verankerd aan je wedstrijddag (of aan de dag van de lange duurloop zolang er geen wedstrijd is ingesteld).",
    "Start": "Start",
    "Next week": "Volgende week",
    "This week": "Deze week",
    "Race date": "Wedstrijddatum",
    "optional": "optioneel",
    "No race booked? Leave the date empty — the plan runs its full length from your start week, and you can link a real race later.":
        "Nog geen wedstrijd geboekt? Laat de datum leeg — het plan loopt zijn volledige lengte vanaf je startweek, en je kunt later een echte wedstrijd koppelen.",
    "No training plan yet.": "Nog geen trainingsplan.",
    "Pick a goal — a 10K, a marathon, or simply staying fit — and the coach builds a week-by-week schedule around your fitness.":
        "Kies een doel — een 10K, een marathon of gewoon fit blijven — en de coach bouwt een week-voor-week schema rond jouw fitheid.",
    "Fitness baseline": "Fitheid als startpunt",
    "Plans are currently built from your Garmin-measured VO₂max ({v}). The values below only take over when there's no Garmin data.":
        "Plannen worden nu gebouwd op je door Garmin gemeten VO₂max ({v}). De waarden hieronder nemen het pas over als er geen Garmin-gegevens zijn.",
    "Plans are currently built from your entered result: VDOT {v}":
        "Plannen worden nu gebouwd op jouw ingevoerde resultaat: VDOT {v}",
    "No fitness data yet — plans fall back to a cautious default (VDOT 45, 25 km/week). Enter a recent race result below for paces that actually fit you.":
        "Nog geen fitheidsgegevens — plannen vallen terug op een voorzichtige standaardwaarde (VDOT 45, 25 km/week). Voer hieronder een recente wedstrijduitslag in voor tempo's die echt bij je passen.",
    "Fitness baseline saved.": "Fitheid opgeslagen.",
    "Couldn't save that — double-check the values.":
        "Opslaan is niet gelukt — controleer de waarden.",
    "Weekly running volume (km)": "Wekelijkse omvang (km)",
    "Save baseline": "Opslaan",

    # ── Misc generic ──────────────────────────────────────────────
    "no data": "geen data",
    "—": "—",
}


_TRANSLATIONS: dict[str, dict[str, str]] = {
    "nl": _NL,
}


def t(source: str, locale: str = "en", **kwargs) -> str:
    """Translate `source` to `locale`. Falls back to the source string
    when the locale has no entry for it — so untranslated strings still
    render (in English) rather than throwing.

    Format-style kwargs are applied *after* lookup, so a single key
    like `"{n} days to race"` works in any language as long as the
    placeholder names match the target translation.
    """
    out = source
    if locale != "en":
        out = _TRANSLATIONS.get(locale, {}).get(source, source)
    if kwargs:
        try:
            return out.format(**kwargs)
        except (KeyError, IndexError):
            # Translation drift — placeholders don't match. Fall back to
            # the source string formatted; never raise from a template.
            return source.format(**kwargs)
    return out


def language_name(locale: str) -> str:
    """Display name for the locale code (used in the settings picker)."""
    return LANGUAGES.get(locale, locale)


def plural(n: int, singular: str, many: str, locale: str = "en", **kwargs) -> str:
    """Render `singular` when n == 1, `many` otherwise. Both strings are
    translated through `t()` first so EN and NL each get their own
    plurals (1 day / 2 days, 1 dag / 2 dagen)."""
    template = singular if n == 1 else many
    return t(template, locale, n=n, **kwargs)
