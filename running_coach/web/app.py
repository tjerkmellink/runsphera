"""FastAPI app for the running coach dashboard.

Run for development:
    .venv\\Scripts\\python.exe -m running_coach.web

Or directly with uvicorn (auto-reload):
    .venv\\Scripts\\uvicorn.exe running_coach.web.app:app --reload --port 8000

Then open http://localhost:8000
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import date as _date, datetime as _datetime, timedelta as _timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # populate os.environ from .env if present

import plotly.graph_objects as go
import plotly.io as pio
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from running_coach.web.security import SameOriginMiddleware

from running_coach import analytics
from running_coach import body as body_service
from running_coach import diary as diary_service
from running_coach import garmin as garmin_auth
from running_coach import gps_route
from running_coach import i18n
from running_coach import settings as app_settings
from running_coach import tips as tips_service
from running_coach import weather as weather_service
from running_coach import race_calendar as race_calendar_service
from running_coach.db import connect
from running_coach.garmin import _refuse_mfa, get_client
from running_coach.ingest import ingest_activities, ingest_recent_days
from running_coach.plans import GOAL_DISTANCES_KM, get_methodology_info, list_methodologies
from running_coach.plans.explainers import ILLUSTRATION_STYLE, get_explainer
from running_coach.plans.recommend import recommend_plan
from running_coach.plans.methodology import GOAL_LABELS
from running_coach.plans import narrative as plan_narrative
from running_coach.plans import service as plan_service
from running_coach.plans import matcher as plan_matcher
from running_coach.plans import coach as plan_coach
from running_coach.plans import event_swap as event_swap_service
from running_coach.plans.garmin_sync import is_pushable_row
from running_coach.strength import service as strength_service
from running_coach.nutrition import service as fuel_service
from running_coach.llm import commentary as llm_commentary

ROOT = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(ROOT / "templates"))

# Dashboard recent-runs pager: 10 per page, back to 5 pages (50 runs).
RECENT_RUNS_PER_PAGE = 10
RECENT_RUNS_MAX_PAGES = 5

app = FastAPI(title="Personal Running Coach")

# The app has no accounts, so loopback binding is the only thing standing
# between a malicious page and a hard-delete of a non-regenerable plan — and
# loopback does not stop a cross-origin form POST. See web/security.py.
app.add_middleware(SameOriginMiddleware)

# Locally-stored event hero images (downloaded once on enrichment, served here).
# Mount happens unconditionally; the dir is created lazily on first download.
race_calendar_service.EVENT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount(
    "/event-images",
    StaticFiles(directory=str(race_calendar_service.EVENT_IMAGE_DIR)),
    name="event-images",
)

# Self-hosted theme assets (fonts + per-theme CSS). Lives under
# running_coach/web/static/. Bundled with the repo, so the app stays
# fully local-first.
STATIC_DIR = ROOT / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "fonts").mkdir(parents=True, exist_ok=True)
(STATIC_DIR / "themes").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Root-path favicon. Browsers request /favicon.ico regardless of the <link>
# tags in <head>, so serve the multi-resolution brand .ico here to avoid a
# 404. Falls back to the 32px PNG if the .ico hasn't been built yet.
_FAVICON_ICO = ROOT.parent / "assets" / "RunSphera.ico"
_FAVICON_PNG = STATIC_DIR / "brand" / "icon-32.png"


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    if _FAVICON_ICO.exists():
        return FileResponse(_FAVICON_ICO, media_type="image/x-icon")
    if _FAVICON_PNG.exists():
        return FileResponse(_FAVICON_PNG, media_type="image/png")
    return Response(status_code=404)


@app.get("/healthz", include_in_schema=False)
def healthz() -> Response:
    """Liveness probe for the desktop launcher.

    Deliberately touches nothing — no DB, no template render. The dashboard at
    `/` takes seconds to build, which is far too slow to distinguish "still
    booting" from "never coming up".
    """
    return Response("ok", media_type="text/plain")


@app.on_event("startup")
def _load_settings_into_env() -> None:
    """Mirror DB-stored LLM provider keys into the env so each provider
    SDK can pick them up at call time. We only set env vars that aren't
    already populated, so a .env file or system env always wins."""
    with closing(connect()) as conn:
        keys = {
            "ANTHROPIC_API_KEY": app_settings.get_anthropic_key(conn),
            "OPENAI_API_KEY":    app_settings.get_openai_key(conn),
            "GEMINI_API_KEY":    app_settings.get_gemini_key(conn),
        }
    for env_name, val in keys.items():
        if val and not os.getenv(env_name):
            os.environ[env_name] = val


def _current_theme_mode() -> str:
    """Read the active theme mode (auto / light / dark) from the DB."""
    try:
        with closing(connect()) as conn:
            return app_settings.get_theme_mode(conn)
    except Exception:  # noqa: BLE001
        return "auto"


def _current_first_name() -> str | None:
    """Read the runner's Garmin first name from the DB for the header profile
    chip. Returns None when not authenticated or before the first sync sets
    full_name — template renders a gear glyph in that case."""
    if not garmin_auth.is_authenticated():
        return None
    try:
        with closing(connect()) as conn:
            return app_settings.garmin_first_name(conn)
    except Exception:  # noqa: BLE001
        return None


def _current_language() -> str:
    """Read the active UI language from the DB. Cheap (one row, indexed PK)."""
    try:
        with closing(connect()) as conn:
            return app_settings.get_language(conn)
    except Exception:  # noqa: BLE001 — fall back to English on DB issues
        return "en"


def _t(source: str, **kwargs) -> str:
    """Template-side translate. Reads the active locale per-call so a
    language switch is picked up on the next render (no server restart).
    """
    return i18n.t(source, locale=_current_language(), **kwargs)


def _plural(n: int, singular: str, many: str, **kwargs) -> str:
    """Template-side pluralize. See running_coach/i18n.py."""
    return i18n.plural(n, singular, many, locale=_current_language(), **kwargs)


# Locale-aware wrappers around the date/day helpers in `analytics`. Each
# reads the current language per-call so flipping the language setting
# is picked up on the next render — no server restart, no Jinja-cache
# tricks, same pattern as `_t()` above.
def _fmt_date_long(iso: str) -> str:
    return analytics.fmt_date_long(iso, locale=_current_language())


def _fmt_date_short(iso: str) -> str:
    return analytics.fmt_date_short(iso, locale=_current_language())


def _fmt_dow_short(iso: str) -> str:
    return analytics.fmt_dow_short(iso, locale=_current_language())


def _fmt_month_short(iso: str) -> str:
    return analytics.fmt_month_short(iso, locale=_current_language())


def _fmt_date_range(start_iso: str, end_iso: str) -> str:
    return analytics.fmt_date_range(start_iso, end_iso, locale=_current_language())


def _fmt_local_dt(iso: str | None, fmt: str | None = None) -> str:
    return analytics.fmt_local_dt(iso, fmt=fmt, locale=_current_language())


def _day_label(dow: int) -> str:
    return analytics.day_label(dow, locale=_current_language())


def _workout_narrative(workout) -> list[str]:
    """Coach-voice paragraphs for a planned workout. Derived from the row's
    structure on every render, so it never drifts from the paces/steps the
    watch will actually run. See running_coach/plans/narrative.py."""
    return plan_narrative.narrate(workout, locale=_current_language())


# Inject shared formatters into every template render
templates.env.globals.update({
    "fmt_duration": analytics.fmt_duration,
    "fmt_pace_s": analytics.fmt_pace_s,
    "fmt_date_long": _fmt_date_long,
    "fmt_date_short": _fmt_date_short,
    "fmt_dow_short": _fmt_dow_short,
    "fmt_month_short": _fmt_month_short,
    "fmt_date_range": _fmt_date_range,
    "day_label": _day_label,
    "fmt_pace": analytics.fmt_pace,
    "fmt_local_dt": _fmt_local_dt,
    "goal_labels": GOAL_LABELS,
    "is_pushable_row": is_pushable_row,
    "week_has_pushable": plan_service.week_has_pushable,
    "week_adherence": plan_service.week_adherence,
    "workout_status": plan_service.workout_status,
    "workout_narrative": _workout_narrative,
    "goal_type_for_distance": race_calendar_service.goal_type_for_distance,
    "province_name": race_calendar_service.province_name,
    "primary_category": race_calendar_service.primary_category,
    "current_theme_mode": _current_theme_mode,
    "current_language": _current_language,
    "current_first_name": _current_first_name,
    "t": _t,
    "plural": _plural,
    "is_authenticated": garmin_auth.is_authenticated,
    "mood_emoji": diary_service.mood_emoji,
    "mood_label": diary_service.mood_label,
    "MOOD_EMOJI": diary_service.MOOD_EMOJI,
    "split_headline": diary_service.split_headline,
    "garmin_feel_label": diary_service.garmin_feel_label,
    "garmin_rpe_label": diary_service.garmin_rpe_label,
    "slug_label": body_service.slug_label,
    "side_label": body_service.side_label,
    "severity_band_label": body_service.severity_band_label,
    "body_svg": __import__("running_coach.body_svg", fromlist=["body_svg"]),
})


def _weekly_mileage_chart(weeks: list[dict]) -> str:
    x = [w["week_start"] for w in weeks]
    y = [w["km"] for w in weeks]
    rolling: list[float] = []
    for i in range(len(y)):
        window = y[max(0, i - 3): i + 1]
        rolling.append(sum(window) / len(window) if window else 0.0)

    fig = go.Figure()
    fig.add_bar(x=x, y=y, name="Weekly km", marker_color="#3b82f6")
    fig.add_scatter(
        x=x, y=rolling, mode="lines+markers", name="4-week avg",
        line=dict(color="#f59e0b", width=3),
    )
    fig.update_layout(
        title=None,
        xaxis_title=None,
        yaxis_title="km",
        height=360,
        margin=dict(l=40, r=20, t=10, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    # Plotly is loaded once in base.html's <head>; `include_plotlyjs=False`
    # keeps the swap response light and avoids re-loading the library
    # when this card lands inside an HTMX `#dashboard-main` swap.
    # `displayModeBar: false` hides the toolbar that otherwise flashes
    # in as a grey strip on top of freshly-swapped charts.
    return pio.to_html(
        fig, include_plotlyjs=False, full_html=False,
        div_id="weekly-mileage",
        config={"responsive": True, "displayModeBar": False},
    )


def _acute_load_chart(series: list[dict]) -> str:
    """Garmin-style acute training load chart: daily 7-day-rolling load
    (black line + markers) over a green "Optimal Range" band that moves
    with the runner's chronic load.

    No bars — the dot-per-day with a moving optimal corridor matches the
    Garmin Connect UI directly. Empty / fresh DBs render an empty-state."""
    locale = _current_language()
    if not series:
        # "Sync to populate" only makes sense with a connected watch;
        # Garmin-less runners get a plain statement instead of a dead CTA.
        empty_text = (
            "No training-load data yet — sync to populate."
            if garmin_auth.is_authenticated()
            else "No training-load data — this chart fills from a connected Garmin watch."
        )
        fig = go.Figure()
        fig.add_annotation(
            text=i18n.t(empty_text, locale=locale),
            xref="paper", yref="paper", x=0.5, y=0.5, showarrow=False,
        )
    else:
        x = [s["date"] for s in series]
        acute = [s["acute"] for s in series]
        low = [s["low_band"] for s in series]
        high = [s["high_band"] for s in series]

        fig = go.Figure()
        # Optimal range — drawn as TWO traces with fill="tonexty" so the
        # band fills between low_band and high_band, not down to zero.
        fig.add_scatter(
            x=x, y=low, mode="lines", line=dict(width=0),
            showlegend=False, hoverinfo="skip",
        )
        fig.add_scatter(
            x=x, y=high, mode="lines", line=dict(width=0),
            fill="tonexty", fillcolor="rgba(134, 239, 172, 0.45)",
            name=i18n.t("Optimal Range", locale=locale),
            hoverinfo="skip",
        )
        # Acute load — black line + markers on top of the band.
        load_label = i18n.t("load", locale=locale)
        fig.add_scatter(
            x=x, y=acute, mode="lines+markers",
            line=dict(color="#1f2937", width=2),
            marker=dict(color="#1f2937", size=6),
            name=i18n.t("Acute load", locale=locale),
            hovertemplate="%{x}<br>" + load_label + ": %{y:.0f}<extra></extra>",
            showlegend=False,
        )

    fig.update_layout(
        title=None,
        xaxis_title=None,
        yaxis_title=None,
        height=320,
        margin=dict(l=20, r=20, t=10, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        autosize=True,
    )
    # `responsive: True` makes plotly track its container's width on
    # window-resize. `displayModeBar: false` hides the toolbar (would
    # otherwise flash in as a grey strip on every HTMX dashboard
    # swap, looking like the card title was "selected").
    return pio.to_html(
        fig, include_plotlyjs=False, full_html=False,
        div_id="acute-load",
        config={"responsive": True, "displayModeBar": False},
    )


# ── Getting-started wizard ─────────────────────────────────────────────
# Ordered step keys. The wizard walks these in order; each has a matching
# branch in templates/_onboarding.html. Every step is skippable and the
# flow is resumable — see docs/onboarding.md.
# Note the goal step is LAST — it's the motivational finale that hands off
# to the full /plans builder (the plan is a flagship feature, not a popup
# form). The optional "extras" sit before it.
# "fitness" is the Garmin-less baseline step: name + recent race result
# (→ manual VDOT) + weekly volume. When Garmin already measured a VDOT it
# renders as a confirmation instead of a form.
ONBOARDING_STEPS = ["welcome", "garmin", "sync", "fitness", "extras", "goal"]

# Race distances the fitness step's "recent result" picker offers, mapped
# to meters for estimate_vdot_from_race.
FITNESS_RACE_DISTANCES: dict[str, tuple[str, float]] = {
    "5k": ("5 km", 5000.0),
    "10k": ("10 km", 10000.0),
    "15k": ("15 km", 15000.0),
    "half_marathon": ("Half marathon", 21097.5),
    "marathon": ("Marathon", 42195.0),
}


def _render_onboarding(request: Request, conn, step: str, *, persist: bool = True, **extra):
    """Render one wizard step partial into `#onboarding-body`. Clamps the
    step to a known key, persists it as the resume point (unless persist=
    False), and bundles the progress metadata every step template needs."""
    if step not in ONBOARDING_STEPS:
        step = ONBOARDING_STEPS[0]
    if persist:
        app_settings.set_onboarding_step(conn, step)
    idx = ONBOARDING_STEPS.index(step)
    ctx = {
        "step": step,
        "step_number": idx + 1,
        "step_count": len(ONBOARDING_STEPS),
        "prev_step": ONBOARDING_STEPS[idx - 1] if idx > 0 else None,
        "next_step": ONBOARDING_STEPS[idx + 1] if idx < len(ONBOARDING_STEPS) - 1 else None,
        "onb_first_name": app_settings.garmin_first_name(conn),
        "garmin_connected": garmin_auth.is_authenticated(),
        "nav_active": None,
    }
    ctx.update(extra)
    return templates.TemplateResponse(request=request, name="_onboarding.html", context=ctx)


@app.get("/auth", response_class=HTMLResponse)
def auth_form(request: Request):
    """Render the Garmin login form, or the MFA-code form when a login is in progress."""
    pending_email = garmin_auth.pending_email()
    with closing(connect()) as conn:
        saved_email = app_settings.get_garmin_email(conn)
    # Fall back to .env so existing users don't have to retype their email.
    env_email = os.getenv("GARMIN_EMAIL", "") if os.getenv("GARMIN_EMAIL") else ""
    return templates.TemplateResponse(
        request=request,
        name="auth.html",
        context={
            "stage": "mfa" if pending_email else "login",
            "prefill_email": pending_email or saved_email or env_email or "",
            "already_connected": garmin_auth.is_authenticated(),
            "nav_active": None,
        },
    )


@app.post("/auth/login", response_class=HTMLResponse)
def auth_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    onboarding: str = Form(""),
):
    """Start the Garmin login. May complete immediately or transition to MFA.

    When called from the Getting-started wizard (`onboarding=1`) the branches
    return `_onboarding.html` step partials (swapped into the modal) instead
    of the standalone `auth.html` page / a redirect."""
    from_wizard = bool(onboarding.strip())
    result = garmin_auth.start_login(email.strip(), password)

    if result["status"] == "complete":
        with closing(connect()) as conn:
            app_settings.set_garmin_email(conn, email.strip())
            app_settings.set_garmin_full_name(conn, result.get("full_name"))
            app_settings.set_garmin_optout(conn, False)  # they use Garmin after all
            if from_wizard:
                # Connected — advance the wizard to the Sync step.
                return _render_onboarding(request, conn, "sync")
        return RedirectResponse(url="/", status_code=303)

    if result["status"] == "mfa_required":
        info = (
            "Garmin has emailed a one-time verification code to "
            f"{email}. Enter it below."
        )
        if from_wizard:
            with closing(connect()) as conn:
                return _render_onboarding(
                    request, conn, "garmin",
                    garmin_stage="mfa", prefill_email=email, info=info,
                )
        return templates.TemplateResponse(
            request=request,
            name="auth.html",
            context={"stage": "mfa", "prefill_email": email, "info": info, "nav_active": None},
        )

    # failed
    error = result.get("error") or "Login failed."
    if from_wizard:
        with closing(connect()) as conn:
            return _render_onboarding(
                request, conn, "garmin",
                garmin_stage="login", prefill_email=email, error=error,
            )
    return templates.TemplateResponse(
        request=request,
        name="auth.html",
        context={"stage": "login", "prefill_email": email, "error": error, "nav_active": None},
        status_code=200,
    )


@app.post("/auth/mfa", response_class=HTMLResponse)
def auth_mfa(request: Request, code: str = Form(...), onboarding: str = Form("")):
    """Submit the email verification code to complete login. Returns a wizard
    step partial when called from onboarding (`onboarding=1`)."""
    from_wizard = bool(onboarding.strip())
    result = garmin_auth.complete_mfa(code)
    if result["status"] == "complete":
        with closing(connect()) as conn:
            if result.get("email"):
                app_settings.set_garmin_email(conn, result["email"])
            app_settings.set_garmin_full_name(conn, result.get("full_name"))
            app_settings.set_garmin_optout(conn, False)  # they use Garmin after all
            if from_wizard:
                return _render_onboarding(request, conn, "sync")
        return RedirectResponse(url="/", status_code=303)

    error = result.get("error") or "MFA verification failed. Try again from the start."
    if from_wizard:
        with closing(connect()) as conn:
            return _render_onboarding(
                request, conn, "garmin",
                garmin_stage="login", prefill_email=result.get("email", ""), error=error,
            )
    return templates.TemplateResponse(
        request=request,
        name="auth.html",
        context={
            "stage": "login",  # fall back to credential form on failure
            "prefill_email": result.get("email", ""),
            "error": error,
            "nav_active": None,
        },
    )


@app.post("/auth/logout")
def auth_logout():
    """Clear cached Garmin session. Email setting is kept for next sign-in."""
    garmin_auth.clear_auth()
    garmin_auth.cancel_pending_login()
    return RedirectResponse(url="/settings", status_code=303)


# ── Getting-started wizard endpoints ───────────────────────────────────
# All return `_onboarding.html` step partials swapped into `#onboarding-body`
# inside the modal, except dismiss/complete which return 204 + let the
# client close the dialog. Garmin login/MFA lives in /auth/* (folded to
# return wizard partials when `onboarding=1`). See docs/onboarding.md.

def _onboarding_sync_summary(conn) -> dict:
    """Post-sync headline numbers for the Sync step: how much came in and
    the freshest VO₂max/VDOT Garmin reported (None when there's no real
    training-status row yet — we never show the 45.0 fallback here)."""
    stats = app_settings.db_stats(conn)
    row = conn.execute(
        "SELECT vo2max_precise FROM training_status "
        "WHERE vo2max_precise IS NOT NULL ORDER BY calendar_date DESC LIMIT 1"
    ).fetchone()
    return {
        "activity_count": stats["activity_count"],
        "last_sync_at": stats["last_sync_at"],
        "vdot": round(row["vo2max_precise"], 1) if row else None,
    }


def _onboarding_step_data(conn, step: str) -> dict:
    """Step-specific render context, shared by the GET view and the POST
    re-renders so a step always rebuilds from live state."""
    if step == "garmin":
        env_email = os.getenv("GARMIN_EMAIL", "") or ""
        return {
            "garmin_stage": "login",
            "prefill_email": app_settings.get_garmin_email(conn) or env_email or "",
        }
    if step == "sync":
        summary = _onboarding_sync_summary(conn)
        return {"sync_summary": summary, "sync_done": summary["activity_count"] > 0}
    if step == "fitness":
        return {
            "garmin_vdot": plan_service._garmin_vdot(conn),
            "baseline": app_settings.get_fitness_baseline(conn),
            "current_name": app_settings.get_garmin_full_name(conn),
            "fitness_distances": FITNESS_RACE_DISTANCES,
            "can_run_10min": app_settings.get_can_run_10min(conn),
        }
    if step == "goal":
        # Finale: read the runner's baseline so the copy can be personal
        # ("VO₂max ~48 · ~36 km/wk"). No form here — it hands off to /plans.
        return {
            "seed": plan_service.get_plan_seed(conn),
            "has_plan": plan_service.get_active_plan(conn) is not None,
        }
    if step == "extras":
        return {
            "coach_key_present": bool(app_settings.get_anthropic_key(conn))
            or bool(os.getenv("ANTHROPIC_API_KEY")),
            "home_location": app_settings.get_home_location(conn),
        }
    return {}


@app.get("/onboarding", response_class=HTMLResponse)
def onboarding_step(request: Request, step: str | None = None):
    """Render the current (or requested) wizard step. Used both to auto-open
    on the dashboard and to resume/navigate (Skip →, ← Back)."""
    with closing(connect()) as conn:
        target = step or app_settings.get_onboarding(conn)["step"]
        if target not in ONBOARDING_STEPS:
            target = ONBOARDING_STEPS[0]
        return _render_onboarding(request, conn, target, **_onboarding_step_data(conn, target))


@app.post("/onboarding/sync", response_class=HTMLResponse)
def onboarding_sync(request: Request):
    """Run the Garmin pull from inside the wizard, then re-render the Sync
    step in its done state (counts + VDOT). Bounces back to the Garmin step
    if the session is gone."""
    with closing(connect()) as conn:
        if not garmin_auth.is_authenticated():
            return _render_onboarding(
                request, conn, "garmin",
                **_onboarding_step_data(conn, "garmin"),
                error="Connect to Garmin first, then sync.",
            )
        try:
            client = get_client(prompt_mfa=_refuse_mfa)
            _run_sync(conn, client)
        except Exception as exc:  # noqa: BLE001
            return _render_onboarding(
                request, conn, "sync",
                **_onboarding_step_data(conn, "sync"),
                sync_error=f"Sync failed: {type(exc).__name__}: {exc}",
            )
        return _render_onboarding(request, conn, "sync", **_onboarding_step_data(conn, "sync"))


@app.post("/onboarding/skip-garmin", response_class=HTMLResponse)
def onboarding_skip_garmin(request: Request):
    """"I don't use Garmin" — remember the choice (so the dashboard stops
    redirecting signed-out visits to /auth) and jump straight to the manual
    fitness-baseline step, skipping Sync."""
    with closing(connect()) as conn:
        app_settings.set_garmin_optout(conn, True)
        return _render_onboarding(
            request, conn, "fitness", **_onboarding_step_data(conn, "fitness")
        )


@app.post("/onboarding/fitness", response_class=HTMLResponse)
def onboarding_fitness(
    request: Request,
    name: str = Form(""),
    race_distance: str = Form(""),
    race_hours: str = Form(""),
    race_minutes: str = Form(""),
    race_seconds: str = Form(""),
    weekly_km: str = Form(""),
    can_run_10min: str = Form(""),
):
    """Save the manual fitness baseline: optional name, optional recent race
    result (→ VDOT via Daniels' formula), optional weekly volume, optional
    10-minute self-assessment. Everything is optional — save what was given
    and re-render the step with the result."""
    def _int(raw: str) -> int:
        raw = (raw or "").strip()
        try:
            return max(0, int(raw)) if raw else 0
        except ValueError:
            return 0

    with closing(connect()) as conn:
        app_settings.set_garmin_full_name(conn, name.strip() or None)

        error = None
        time_s = _int(race_hours) * 3600 + _int(race_minutes) * 60 + _int(race_seconds)
        if race_distance and time_s > 0:
            dist = FITNESS_RACE_DISTANCES.get(race_distance)
            if dist is None:
                error = "Unknown race distance."
            else:
                label, meters = dist
                vdot = plan_service.estimate_vdot_from_race(meters, float(time_s))
                h, rem = divmod(time_s, 3600)
                m, s = divmod(rem, 60)
                time_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
                try:
                    app_settings.set_manual_vdot(conn, vdot, note=f"{label} in {time_str}")
                except ValueError:
                    error = (
                        "That result implies a VDOT outside the plausible range — "
                        "double-check the distance and time."
                    )
        elif race_distance and time_s == 0 and (race_hours or race_minutes or race_seconds):
            error = "Enter the race time as hours/minutes/seconds."

        km = (weekly_km or "").strip().replace(",", ".")
        if km and not error:
            try:
                app_settings.set_manual_weekly_km(conn, float(km))
            except ValueError:
                error = "Weekly volume must be between 0 and 300 km."

        # Tri-state self-assessment: blank stays NULL (never answered).
        if can_run_10min in ("yes", "no"):
            app_settings.set_can_run_10min(conn, can_run_10min == "yes")

        if error:
            return _render_onboarding(
                request, conn, "fitness",
                **_onboarding_step_data(conn, "fitness"),
                fitness_error=error,
            )
        # Saved (or nothing entered — same as a skip): move on. The finale's
        # seedcard is where the derived VDOT pays off.
        return _render_onboarding(
            request, conn, "extras", **_onboarding_step_data(conn, "extras")
        )


@app.post("/onboarding/goto-plans")
def onboarding_goto_plans():
    """Finale hand-off: mark onboarding complete and send the runner to the
    full plan builder. The plan is a flagship feature — it gets the real
    /plans/new page, not a cramped popup form."""
    with closing(connect()) as conn:
        app_settings.set_onboarding_status(conn, "completed")
    return Response(status_code=204, headers={"HX-Redirect": "/plans/new"})


@app.post("/onboarding/coach-key", response_class=HTMLResponse)
def onboarding_coach_key(request: Request, api_key: str = Form("")):
    """Optionally store an Anthropic API key so the coach voice works, then
    re-render the Extras step with a saved badge."""
    key = api_key.strip()
    with closing(connect()) as conn:
        if key:
            app_settings.set_anthropic_key(conn, key)
            os.environ["ANTHROPIC_API_KEY"] = key
            app_settings.set_llm_provider(conn, "anthropic")
            llm_commentary.invalidate_today(conn)
        return _render_onboarding(
            request, conn, "extras",
            **_onboarding_step_data(conn, "extras"),
            coach_saved=bool(key),
        )


@app.post("/onboarding/location", response_class=HTMLResponse)
def onboarding_location(request: Request, query: str = Form("")):
    """Optionally geocode + store a home location for weather, then re-render
    the Extras step."""
    q = query.strip()
    with closing(connect()) as conn:
        if not q:
            return _render_onboarding(request, conn, "extras", **_onboarding_step_data(conn, "extras"))
        resolved = weather_service.geocode(q)
        if not resolved:
            return _render_onboarding(
                request, conn, "extras",
                **_onboarding_step_data(conn, "extras"),
                location_error="Couldn't find that place — try \"City, Country\".",
            )
        app_settings.set_home_location(
            conn,
            lat=resolved["lat"],
            lon=resolved["lon"],
            display_name=resolved["display_name"],
            country_code=resolved.get("country_code"),
        )
        llm_commentary.invalidate_today(conn)
        return _render_onboarding(
            request, conn, "extras",
            **_onboarding_step_data(conn, "extras"),
            location_saved=True,
        )


@app.post("/onboarding/dismiss")
def onboarding_dismiss():
    """"I'll finish later" — stop the wizard auto-opening. Reopenable from the
    header's "Getting started" link (resumes at the saved step)."""
    with closing(connect()) as conn:
        app_settings.set_onboarding_status(conn, "dismissed")
    return Response(status_code=204)


@app.post("/onboarding/complete")
def onboarding_complete():
    """Finish the wizard. Refresh the dashboard behind the modal so any
    freshly synced data / new plan shows immediately."""
    with closing(connect()) as conn:
        app_settings.set_onboarding_status(conn, "completed")
    return Response(status_code=204, headers={"HX-Trigger": "dashboardRefresh"})


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, saved: str | None = None, error: str | None = None):
    with closing(connect()) as conn:
        claude_key = app_settings.get_anthropic_key(conn)
        openai_key = app_settings.get_openai_key(conn)
        gemini_key = app_settings.get_gemini_key(conn)
        llm_provider = app_settings.get_llm_provider(conn)
        garmin_email = app_settings.get_garmin_email(conn)
        garmin_full_name = app_settings.get_garmin_full_name(conn)
        about_you = app_settings.get_about_you(conn)
        home_location = app_settings.get_home_location(conn)
        active_language = app_settings.get_language(conn)
        db_snapshot = app_settings.db_stats(conn)
        include_body_in_llm = app_settings.get_include_body_in_llm(conn)
        body_profile = app_settings.get_body_profile(conn)
        current_vdot = plan_service._current_vdot(conn) if hasattr(plan_service, "_current_vdot") else None
        plan_seed = plan_service.get_plan_seed(conn)
        fitness_baseline = app_settings.get_fitness_baseline(conn)
        can_run_10min = app_settings.get_can_run_10min(conn)
    template_name = "settings.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "nav_active": "settings",
            "saved": saved,
            "error": error,
            "garmin_connected": garmin_auth.is_authenticated(),
            "garmin_email": garmin_email,
            "garmin_full_name": garmin_full_name,
            "claude_key_masked": app_settings.mask_anthropic_key(claude_key),
            "claude_key_present": bool(claude_key),
            "claude_key_from_env": bool(os.getenv("ANTHROPIC_API_KEY")) and not claude_key,
            "openai_key_masked": app_settings.mask_api_key(openai_key),
            "openai_key_present": bool(openai_key),
            "openai_key_from_env": bool(os.getenv("OPENAI_API_KEY")) and not openai_key,
            "gemini_key_masked": app_settings.mask_api_key(gemini_key),
            "gemini_key_present": bool(gemini_key),
            "gemini_key_from_env": bool(os.getenv("GEMINI_API_KEY")) and not gemini_key,
            "llm_provider": llm_provider,
            "about_you": about_you or "",
            "about_you_max": app_settings.ABOUT_YOU_MAX_CHARS,
            "include_body_in_llm": include_body_in_llm,
            "body_profile": body_profile,
            "body_profile_sexes": app_settings.ALLOWED_SEX,
            "body_profile_diets": app_settings.ALLOWED_DIET_PREFS,
            "home_location": home_location,
            "active_language": active_language,
            "available_languages": i18n.LANGUAGES,
            "db": db_snapshot,
            "current_vdot": current_vdot,
            "plan_seed": plan_seed,
            "fitness_baseline": fitness_baseline,
            "fitness_distances": FITNESS_RACE_DISTANCES,
            "can_run_10min": can_run_10min,
        },
    )


@app.post("/settings/about")
def settings_save_about(about_you: str = Form("")):
    """Persist the about-you free-text note. Invalidates today's coach cache."""
    with closing(connect()) as conn:
        app_settings.set_about_you(conn, about_you)
        llm_commentary.invalidate_today(conn)
    return RedirectResponse(url="/settings?saved=about", status_code=303)


@app.post("/settings/body-llm")
def settings_save_body_llm(enabled: str = Form("")):
    """Toggle whether body state is spliced into the coach's profile
    prompt. Invalidates today's coach cache so the next render rebuilds
    the prompt with or without the body block."""
    flag = enabled.strip().lower() in ("1", "on", "true", "yes")
    with closing(connect()) as conn:
        app_settings.set_include_body_in_llm(conn, flag)
        llm_commentary.invalidate_today(conn)
    return RedirectResponse(url="/settings?saved=body_llm", status_code=303)


@app.post("/settings/location")
def settings_save_location(query: str = Form(...)):
    """Geocode the typed location (City, country) and persist lat/lon + display.
    Invalidates today's coach cache so the next dashboard view reflects new weather context."""
    query = (query or "").strip()
    if not query:
        return RedirectResponse(url="/settings?error=location_empty", status_code=303)
    resolved = weather_service.geocode(query)
    if not resolved:
        return RedirectResponse(url="/settings?error=location_unresolved", status_code=303)
    with closing(connect()) as conn:
        app_settings.set_home_location(
            conn,
            lat=resolved["lat"],
            lon=resolved["lon"],
            display_name=resolved["display_name"],
            country_code=resolved.get("country_code"),
        )
        llm_commentary.invalidate_today(conn)
    return RedirectResponse(url="/settings?saved=location", status_code=303)


@app.post("/settings/location/delete")
def settings_clear_location():
    """Clear the home location. Today's weather cache stays — it's keyed by
    lat/lon so it won't be hit again until a new location is saved."""
    with closing(connect()) as conn:
        app_settings.clear_home_location(conn)
        llm_commentary.invalidate_today(conn)
    return RedirectResponse(url="/settings?saved=location_cleared", status_code=303)


@app.post("/settings/body-profile")
def settings_save_body_profile(
    weight_kg: str = Form(""),
    height_cm: str = Form(""),
    birth_year: str = Form(""),
    sex: str = Form(""),
    diet_pref: str = Form(""),
):
    """Persist the body profile that powers the Fuel feature. Weight is
    required; the rest are optional. Invalidates today's coach cache so
    any body-aware prompt picks up the change."""
    def _num(raw, cast):
        raw = (raw or "").strip()
        if not raw:
            return None
        try:
            return cast(raw)
        except ValueError:
            return None

    try:
        with closing(connect()) as conn:
            app_settings.set_body_profile(
                conn,
                weight_kg=_num(weight_kg, float),
                height_cm=_num(height_cm, float),
                birth_year=_num(birth_year, int),
                sex=(sex.strip().lower() or None),
                diet_pref=(diet_pref.strip().lower() or None),
            )
            llm_commentary.invalidate_today(conn)
    except ValueError:
        return RedirectResponse(url="/settings?error=body_profile", status_code=303)
    return RedirectResponse(url="/settings?saved=body_profile#fuel", status_code=303)


@app.post("/settings/fitness")
def settings_save_fitness(
    race_distance: str = Form(""),
    race_hours: str = Form(""),
    race_minutes: str = Form(""),
    race_seconds: str = Form(""),
    weekly_km: str = Form(""),
    can_run_10min: str = Form(""),
):
    """Persist the manual fitness baseline from Settings — same semantics as
    the wizard's fitness step: a recent race result becomes a VDOT via
    Daniels' formula, weekly volume is stored as given. Garmin-measured data
    still outranks these when it exists (see plans/service.get_plan_seed)."""
    def _int(raw: str) -> int:
        raw = (raw or "").strip()
        try:
            return max(0, int(raw)) if raw else 0
        except ValueError:
            return 0

    time_s = _int(race_hours) * 3600 + _int(race_minutes) * 60 + _int(race_seconds)
    with closing(connect()) as conn:
        if race_distance and time_s > 0:
            dist = FITNESS_RACE_DISTANCES.get(race_distance)
            if dist is None:
                return RedirectResponse(url="/settings?error=fitness#fitness", status_code=303)
            label, meters = dist
            vdot = plan_service.estimate_vdot_from_race(meters, float(time_s))
            h, rem = divmod(time_s, 3600)
            m, s = divmod(rem, 60)
            time_str = f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
            try:
                app_settings.set_manual_vdot(conn, vdot, note=f"{label} in {time_str}")
            except ValueError:
                return RedirectResponse(url="/settings?error=fitness#fitness", status_code=303)
        km = (weekly_km or "").strip().replace(",", ".")
        if km:
            try:
                app_settings.set_manual_weekly_km(conn, float(km))
            except ValueError:
                return RedirectResponse(url="/settings?error=fitness#fitness", status_code=303)
        if can_run_10min in ("yes", "no"):
            app_settings.set_can_run_10min(conn, can_run_10min == "yes")
    return RedirectResponse(url="/settings?saved=fitness#fitness", status_code=303)


@app.post("/settings/body-profile/import-garmin")
def settings_import_body_profile():
    """Optional pre-fill from Garmin's user profile + latest weigh-in.
    Merges with any existing values (Garmin fills the blanks); the runner
    can still edit afterwards. No-op with a friendly error if Garmin has
    nothing usable or the session isn't available."""
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
        fetched = garmin_auth.fetch_profile(client)
    except Exception:  # noqa: BLE001 — never crash the settings page on a sync miss
        fetched = {}
    if not fetched.get("weight_kg"):
        return RedirectResponse(url="/settings?error=garmin_profile#fuel", status_code=303)
    with closing(connect()) as conn:
        existing = app_settings.get_body_profile(conn) or {}
        merged = {**existing, **fetched}
        try:
            app_settings.set_body_profile(
                conn,
                weight_kg=merged.get("weight_kg"),
                height_cm=merged.get("height_cm"),
                birth_year=merged.get("birth_year"),
                sex=merged.get("sex"),
                diet_pref=merged.get("diet_pref"),
            )
        except ValueError:
            return RedirectResponse(url="/settings?error=garmin_profile#fuel", status_code=303)
        llm_commentary.invalidate_today(conn)
    return RedirectResponse(url="/settings?saved=body_profile_garmin#fuel", status_code=303)


@app.post("/settings/theme-mode")
def settings_save_theme_mode(mode: str = Form(...)):
    """Switch theme mode (auto / light / dark). Light/dark force the variant;
    auto follows the OS `prefers-color-scheme`."""
    mode = mode.strip().lower()
    if mode not in app_settings.ALLOWED_THEME_MODES:
        return RedirectResponse(url="/settings?error=mode_unknown", status_code=303)
    with closing(connect()) as conn:
        app_settings.set_theme_mode(conn, mode)
    return RedirectResponse(url=f"/settings?saved=mode&mode={mode}", status_code=303)


@app.post("/settings/language")
def settings_save_language(language: str = Form(...)):
    """Switch UI + coach language (en / nl). Drops every cached LLM message
    on the way out so the next dashboard render produces output in the new
    locale instead of serving stale text in the old language."""
    language = language.strip().lower()
    if language not in app_settings.ALLOWED_LANGUAGES:
        return RedirectResponse(url="/settings?error=language_unknown", status_code=303)
    with closing(connect()) as conn:
        app_settings.set_language(conn, language)
        llm_commentary.invalidate_all_coach(conn)
    return RedirectResponse(url=f"/settings?saved=language&language={language}", status_code=303)


@app.post("/settings/claude")
def settings_save_claude(api_key: str = Form(...)):
    """Persist a Claude API key and make it visible to the SDK."""
    api_key = api_key.strip()
    if not api_key:
        return RedirectResponse(url="/settings", status_code=303)
    with closing(connect()) as conn:
        app_settings.set_anthropic_key(conn, api_key)
    os.environ["ANTHROPIC_API_KEY"] = api_key
    return RedirectResponse(url="/settings?saved=claude", status_code=303)


@app.post("/settings/claude/delete")
def settings_clear_claude():
    """Remove the stored Claude key. A .env-provided key is left untouched."""
    with closing(connect()) as conn:
        app_settings.clear_anthropic_key(conn)
    # Only drop the runtime env var if it wasn't sourced from .env originally.
    load_dotenv(override=False)
    env_key = os.getenv("ANTHROPIC_API_KEY")
    dotenv_path = Path.cwd() / ".env"
    dotenv_key: str | None = None
    if dotenv_path.exists():
        for line in dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("ANTHROPIC_API_KEY="):
                dotenv_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if env_key and env_key != dotenv_key:
        os.environ.pop("ANTHROPIC_API_KEY", None)
    return RedirectResponse(url="/settings?saved=cleared", status_code=303)


# ── Multi-provider LLM coach: switcher + per-provider key save/clear ───
# Switching provider never touches `llm_cache` — past coach lines stay
# readable; only the next regeneration uses the new provider.

@app.post("/settings/llm/provider")
def settings_save_llm_provider(provider: str = Form(...)):
    """Change which provider the coach voice uses for new generations."""
    if provider not in ("anthropic", "openai", "gemini"):
        return RedirectResponse(url="/settings?error=provider_unknown", status_code=303)
    with closing(connect()) as conn:
        app_settings.set_llm_provider(conn, provider)
    return RedirectResponse(url=f"/settings?saved=provider&provider={provider}", status_code=303)


def _clear_env_unless_from_dotenv(env_name: str) -> None:
    """Pop `env_name` from os.environ — unless the value matches what's
    in .env (in which case `.env` is the source of truth and we leave
    the env alone). Used by per-provider "Clear" endpoints."""
    load_dotenv(override=False)
    env_val = os.getenv(env_name)
    dotenv_val: str | None = None
    dotenv_path = Path.cwd() / ".env"
    if dotenv_path.exists():
        for line in dotenv_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith(f"{env_name}="):
                dotenv_val = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    if env_val and env_val != dotenv_val:
        os.environ.pop(env_name, None)


@app.post("/settings/openai")
def settings_save_openai(api_key: str = Form(...)):
    """Persist an OpenAI key + make it visible to the SDK."""
    api_key = api_key.strip()
    if not api_key:
        return RedirectResponse(url="/settings", status_code=303)
    with closing(connect()) as conn:
        app_settings.set_openai_key(conn, api_key)
    os.environ["OPENAI_API_KEY"] = api_key
    return RedirectResponse(url="/settings?saved=openai", status_code=303)


@app.post("/settings/openai/delete")
def settings_clear_openai():
    """Remove the stored OpenAI key. A .env-provided key is left untouched."""
    with closing(connect()) as conn:
        app_settings.clear_openai_key(conn)
    _clear_env_unless_from_dotenv("OPENAI_API_KEY")
    return RedirectResponse(url="/settings?saved=cleared_openai", status_code=303)


@app.post("/settings/gemini")
def settings_save_gemini(api_key: str = Form(...)):
    """Persist a Gemini key + make it visible to the SDK."""
    api_key = api_key.strip()
    if not api_key:
        return RedirectResponse(url="/settings", status_code=303)
    with closing(connect()) as conn:
        app_settings.set_gemini_key(conn, api_key)
    os.environ["GEMINI_API_KEY"] = api_key
    return RedirectResponse(url="/settings?saved=gemini", status_code=303)


@app.post("/settings/gemini/delete")
def settings_clear_gemini():
    """Remove the stored Gemini key. A .env-provided key is left untouched."""
    with closing(connect()) as conn:
        app_settings.clear_gemini_key(conn)
    _clear_env_unless_from_dotenv("GEMINI_API_KEY")
    return RedirectResponse(url="/settings?saved=cleared_gemini", status_code=303)


def _build_week_wrapped(conn, active_plan: dict | None, today_iso: str) -> dict | None:
    """Assemble the "This week, wrapped" context for the dashboard, or None to
    hide the block. Shared by the index route and the ↻-refresh route.

    The stats are always built for the active plan's current training week; the
    LLM celebration line is only fetched once the week is fully complete (and
    only from cache unless force=True) — mid-week the template renders an
    instant rules-based line, so a normal page load never blocks on the LLM.
    """
    if not active_plan:
        return None
    plan_weeks = plan_service.get_plan_weeks(conn, active_plan["id"])
    cur_week = plan_service.current_plan_week(plan_weeks, today_iso)
    if not cur_week:
        return None
    stats = plan_service.week_stats(conn, active_plan["id"], plan_weeks, cur_week, today_iso)
    if stats["sessions_planned"] == 0:
        return None  # an all-rest week — nothing to celebrate or track
    celebration = celebration_at = None
    if stats["complete"]:
        celebration = llm_commentary.week_wrapped(conn, active_plan["id"], stats)
        celebration_at = (
            llm_commentary.week_wrapped_generated_at(conn, active_plan["id"], stats)
            if celebration else None
        )
    return {
        "stats": stats,
        "celebration": celebration,
        "celebration_generated_at": celebration_at,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    # First-run funnel. A brand-new user (onboarding still 'pending') lands
    # on the dashboard even without a Garmin session — the Getting-started
    # wizard opens on top and walks them through connecting. A returning
    # user who has logged out (onboarding done/dismissed) is sent to /auth —
    # UNLESS they explicitly chose the Garmin-less mode in the wizard, in
    # which case the dashboard is theirs; /auth stays reachable via Settings.
    if not garmin_auth.is_authenticated():
        with closing(connect()) as conn:
            pending = app_settings.get_onboarding(conn)["status"] == "pending"
            optout = app_settings.get_garmin_optout(conn)
        if not pending and not optout:
            return RedirectResponse(url="/auth", status_code=303)

    with closing(connect()) as conn:
        state = analytics.current_state(conn)
        weeks = analytics.weekly_mileage(conn, weeks=12)
        zones = analytics.hr_zone_totals(conn, days=7)
        acute_load = analytics.acute_load_series(conn, days=28)
        runs = analytics.recent_runs(conn, n=RECENT_RUNS_PER_PAGE)
        runs_total = analytics.count_runs(conn)
        todays = plan_service.todays_workout(conn)
        todays_strength = strength_service.todays_strength_session(conn)
        todays_fuel = fuel_service.fuel_for_date(conn, _date.today())
        active_plan = plan_service.get_active_plan(conn)
        recommendation = plan_coach.daily_recommendation(conn)
        first_name = app_settings.garmin_first_name(conn)
        onboarding = app_settings.get_onboarding(conn)
        home_location = app_settings.get_home_location(conn)
        today_iso = _date.today().isoformat()
        today_diary = diary_service.get_entry_for_date(conn, today_iso)
        weather = weather_service.current_weather(conn)
        weather_hours = weather_service.hourly_breakdown(weather) if weather else []
        coach_message = llm_commentary.daily_coach_message(conn, recommendation, todays)
        coach_generated_at = llm_commentary.daily_coach_generated_at(conn)
        weekly_recap = llm_commentary.weekly_recap(conn)
        weekly_recap_generated_at = llm_commentary.weekly_recap_generated_at(conn)
        # "This week, wrapped" — a stats block for the active plan's current
        # training week. Renders all week and updates as sessions complete; the
        # LLM celebration line fires only once the week is fully done (cached,
        # like weekly_recap), with an instant rules-based line the rest of the
        # time. None → the block is hidden (no plan, or between weeks).
        week_wrapped = _build_week_wrapped(conn, active_plan, today_iso)
        daily_tip = tips_service.daily_tip(conn)
        upcoming_races = race_calendar_service.list_favorites(conn, today_iso=today_iso)
        # Race-day countdown: when the active plan has a linked race,
        # build a compact countdown card for the flagship aside. Replaces
        # the daily bonus tip while a real race is on the horizon, and
        # lingers for 48h after the race day for a "recap" phase before
        # falling back to the tip.
        countdown = None
        if active_plan and active_plan.get("race_date"):
            plan_race = race_calendar_service.race_for_active_plan(conn, active_plan["id"])
            if plan_race and plan_race.get("race_date"):
                try:
                    race_day = _date.fromisoformat(plan_race["race_date"])
                    days_until = (race_day - _date.today()).days
                except ValueError:
                    days_until = None
                if days_until is not None and days_until >= -2:
                    # Urgency phase:
                    #   future, > 7 days       → 'future'    (amber, calm)
                    #   future, 2–7 days       → 'final-week' (red, bold)
                    #   1 day out              → 'tomorrow'   (red, "RACE TOMORROW")
                    #   day of                 → 'today'     (red, "RACE DAY")
                    #   1–2 days after         → 'recap'     (grey, look-back)
                    if days_until > 7:
                        phase = "future"
                    elif days_until > 1:
                        phase = "final-week"
                    elif days_until == 1:
                        phase = "tomorrow"
                    elif days_until == 0:
                        phase = "today"
                    else:
                        phase = "recap"
                    countdown = {
                        "event": plan_race,
                        "days_until": days_until,
                        "phase": phase,
                    }
                    # Race-time prediction — two sources, in order of trust:
                    #   1. Garmin's race predictor (`training_status.race_pred_*`).
                    #      A regression model on actual runner outcomes —
                    #      calibrated against millions of finishers, including
                    #      amateurs who didn't do specific marathon prep. The
                    #      honest number for someone glancing at a countdown.
                    #      Only available at four canonical distances:
                    #      5k / 10k / half / marathon.
                    #   2. Daniels' formula via `plan.vdot_at_start` (or
                    #      Garmin's `vo2max_precise` as last resort). A
                    #      physiological extrapolation — good at short
                    #      distances, optimistic at the marathon. Used when
                    #      Garmin doesn't cover the race distance (e.g. 15k).
                    # In both branches we surface which VDOT/source the
                    # prediction came from so the runner sees the basis.

                    # Race-readiness score — 0-100 blend of adherence,
                    # quality recency, VDOT trend, ACWR band, long-run base.
                    # Returns None when there's not enough signal (plan
                    # too young, race too long past); template silently
                    # drops the readiness bar in that case.
                    from running_coach.plans import readiness as _readiness
                    try:
                        cd_readiness = _readiness.race_readiness(conn, active_plan, plan_race)
                        if cd_readiness:
                            countdown["readiness"] = cd_readiness
                    except Exception:  # noqa: BLE001 — dashboard still renders without it
                        pass

                    distance_km = plan_race.get("chosen_distance_km")
                    ts = state.get("training_status") or {}
                    if distance_km:
                        garmin_pred_s = plan_service.garmin_race_prediction(
                            float(distance_km), ts,
                        )
                        if garmin_pred_s:
                            countdown["predicted_time_s"] = garmin_pred_s
                            countdown["predicted_source"] = "garmin"
                        else:
                            plan_vdot = (active_plan or {}).get("vdot_at_start")
                            garmin_vdot = ts.get("vo2max_precise")
                            vdot = plan_vdot if (plan_vdot and plan_vdot > 0) else garmin_vdot
                            if vdot and vdot > 0:
                                try:
                                    pred_s = plan_service.predict_race_time(
                                        distance_m=float(distance_km) * 1000.0,
                                        vdot=float(vdot),
                                    )
                                    countdown["predicted_time_s"] = int(round(pred_s))
                                    countdown["predicted_vdot"] = round(float(vdot), 1)
                                    countdown["predicted_source"] = "daniels"
                                except (ValueError, Exception):  # noqa: BLE001
                                    pass
        # Carousel excludes the countdown's event so it doesn't render twice.
        if countdown:
            cd_event_id = countdown["event"]["id"]
            upcoming_races = [r for r in upcoming_races if r.get("id") != cd_event_id]

        # Auto-detect a recent race-pace effort that implies a meaningful
        # VDOT bump. Surfaced as a small banner at the top of the
        # dashboard. Silent (None) most days; appears when the runner
        # has actually raced or run a hard time-trial.
        try:
            from running_coach.plans import vdot_detection as _vdot_det
            vdot_suggestion = _vdot_det.detect_vdot_suggestion(conn)
        except Exception:  # noqa: BLE001 — dashboard still renders without it
            vdot_suggestion = None
        # Body / wellbeing — top-2 active issues + daily check-in prompt
        # state. Swallows errors so the dashboard still renders if body
        # tables are missing or locked.
        try:
            body_summary = body_service.dashboard_summary(conn)
        except Exception:  # noqa: BLE001
            body_summary = {
                "top_issues": [], "active_count": 0, "all_clear": True,
                "show_daily_prompt": False, "last_clear_at": None,
                "any_body_data": False,
            }
        # Offer the swap action only when the coach says caution/easy and a rule applies.
        swap_available = bool(
            recommendation
            and todays
            and recommendation["status"] in ("caution", "easy")
            and not todays.get("actual_activity_id")
        )
    is_fresh_user = not active_plan and not runs

    # Auto-sync if the last ingest is stale (>4h) and the user has data.
    # First-run users see the welcome card with its own sync CTA; don't
    # double-fire there. The template renders a small <script> that
    # clicks the visible sync button after a short delay, so the spinner
    # appears in the button itself + the in-place refresh fires the
    # same way a manual click does.
    auto_sync_due = False
    last_ingest = state.get("last_ingest")
    if last_ingest and not is_fresh_user:
        try:
            last_at = _datetime.fromisoformat(last_ingest["completed_at"])
            auto_sync_due = (_datetime.now() - last_at).total_seconds() > 4 * 3600
        except (ValueError, TypeError, KeyError):
            auto_sync_due = False
    template_name = "index.html"

    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "state": state,
            "runs": runs,
            "page": 1,
            "has_prev": False,
            "has_next": runs_total > RECENT_RUNS_PER_PAGE,
            "weekly_chart": _weekly_mileage_chart(weeks),
            "acute_load_chart": _acute_load_chart(acute_load),
            "zones": zones,
            "todays_workout": todays,
            "todays_strength": todays_strength,
            "todays_fuel": todays_fuel,
            "active_plan": active_plan,
            "recommendation": recommendation,
            "coach_message": coach_message,
            "coach_generated_at": coach_generated_at,
            "weekly_recap": weekly_recap,
            "weekly_recap_generated_at": weekly_recap_generated_at,
            "week_wrapped": week_wrapped,
            "llm_available": llm_commentary.connector.is_available(),
            "daily_tip": daily_tip,
            "tip_category_labels": tips_service.CATEGORY_LABELS,
            "weather": weather,
            "weather_hours": weather_hours,
            "upcoming_races": upcoming_races,
            "countdown": countdown,
            "vdot_suggestion": vdot_suggestion,
            "body_summary": body_summary,
            "swap_available": swap_available,
            "first_name": first_name,
            "home_location": home_location,
            "is_fresh_user": is_fresh_user,
            # Auto-open the Getting-started wizard while onboarding is
            # unfinished. base.html reads this to fire the opener script.
            "show_onboarding": onboarding["status"] == "pending",
            "today_diary": today_diary,
            "today_iso": today_iso,
            "auto_sync_due": auto_sync_due,
            "nav_active": "dashboard",
        },
    )


def _latest_run_id(conn) -> int | None:
    """activity_id of the most recent running activity, or None if there
    are no runs yet. Used to detect whether a sync pulled in a brand-new
    run (the newest run changed) so the dashboard can auto-open it."""
    row = conn.execute(
        "SELECT activity_id FROM activities WHERE activity_type = 'running' "
        "ORDER BY start_time_gmt DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _run_sync(conn, client) -> int | None:
    """Core Garmin pull shared by the dashboard Sync button and the
    Getting-started wizard: fetch activities + recent daily metrics,
    capture the runner's name on first login, run the plan/strength
    matchers (best-effort), and invalidate stale LLM caches.

    Returns the activity_id of a newly-arrived run when the sync changed
    the most-recent run (so the caller can auto-open its detail modal),
    otherwise None. Wizard callers can ignore the return value."""
    latest_before = _latest_run_id(conn)
    ingest_activities(conn, client, limit=30)
    ingest_recent_days(conn, client, days=14)
    # First-time-after-login: capture full name from the live client so
    # the dashboard can greet the user by first name.
    full_name = getattr(client, "full_name", "") or None
    if full_name and not app_settings.get_garmin_full_name(conn):
        app_settings.set_garmin_full_name(conn, full_name)
    try:
        plan_matcher.match_plan_workouts(conn)
    except Exception:  # noqa: BLE001 — matcher failure shouldn't fail the sync
        pass
    # Strength matcher: link strength_training / mobility activities
    # to their scheduled plan_strength_sessions via Garmin's
    # echoed workoutId (strict, no fuzzy fallback).
    try:
        from running_coach.strength import matcher as _strength_matcher
        _strength_matcher.match_strength_sessions(conn)
    except Exception:  # noqa: BLE001 — same posture as the running matcher
        pass
    # Fresh data → today's cached coach message + last week's recap are stale.
    llm_commentary.invalidate_today(conn)
    llm_commentary.invalidate_weekly_recap(conn)
    latest_after = _latest_run_id(conn)
    if latest_after is not None and latest_after != latest_before:
        return latest_after
    return None


@app.post("/ingest", response_class=HTMLResponse)
def trigger_ingest():
    """Run a sync from the UI. On success, signal HTMX to fire a
    `dashboardRefresh` event — the dashboard's `#dashboard-main`
    wrapper listens for it and swaps itself in place via hx-get +
    hx-select, so the user keeps their scroll / open modals.

    When the sync pulled in a brand-new run, additionally fire a
    `newRunDetected` event carrying its activity_id, so the dashboard
    can auto-open that run's detail modal — the just-finished run is the
    first thing the user sees."""
    if not garmin_auth.is_authenticated():
        return Response(status_code=204, headers={"HX-Redirect": "/auth"})
    new_run_id = None
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
        with closing(connect()) as conn:
            new_run_id = _run_sync(conn, client)
    except Exception as exc:  # noqa: BLE001
        # Token may have expired — let the user re-auth.
        message = (
            "Garmin session looks stale — sign in again to refresh."
            if "auth" in str(exc).lower() or "401" in str(exc)
            else f"Sync failed: {type(exc).__name__}: {exc}"
        )
        return HTMLResponse(content=f'<div class="error">{message}</div>', status_code=200)
    if new_run_id is not None:
        trigger = json.dumps(
            {"dashboardRefresh": None, "newRunDetected": {"activityId": new_run_id}}
        )
    else:
        trigger = "dashboardRefresh"
    return Response(status_code=204, headers={"HX-Trigger": trigger})


@app.post("/coach-message/refresh", response_class=HTMLResponse)
def coach_message_refresh(request: Request):
    """Regenerate today's LLM coach message, bypassing the daily cache."""
    with closing(connect()) as conn:
        todays = plan_service.todays_workout(conn)
        recommendation = plan_coach.daily_recommendation(conn)
        coach_message = llm_commentary.daily_coach_message(
            conn, recommendation, todays, force_refresh=True
        )
        coach_generated_at = llm_commentary.daily_coach_generated_at(conn)
    # Tempo's hero pull-quote has its own swap target (#coach-head wraps quote
    # + attribution row) so it gets a dedicated partial. Base uses the default.
    partial = "_coach_message.html"
    return templates.TemplateResponse(
        request=request,
        name=partial,
        context={
            "recommendation": recommendation,
            "coach_message": coach_message,
            "coach_generated_at": coach_generated_at,
            "llm_available": llm_commentary.connector.is_available(),
        },
    )


@app.post("/weekly-recap/refresh", response_class=HTMLResponse)
def weekly_recap_refresh(request: Request):
    """Regenerate the weekly recap, bypassing the cache. Returns a per-theme
    partial which the ↻ button swaps in via HTMX."""
    with closing(connect()) as conn:
        weekly_recap = llm_commentary.weekly_recap(conn, force_refresh=True)
        weekly_recap_generated_at = llm_commentary.weekly_recap_generated_at(conn)
    partial = "_weekly_recap.html"
    return templates.TemplateResponse(
        request=request,
        name=partial,
        context={
            "weekly_recap": weekly_recap,
            "weekly_recap_generated_at": weekly_recap_generated_at,
            "llm_available": llm_commentary.connector.is_available(),
        },
    )


@app.post("/week-wrapped/refresh", response_class=HTMLResponse)
def week_wrapped_refresh(request: Request):
    """Regenerate the completed-week celebration line, bypassing the cache.
    Returns the _week_wrapped.html partial for the ↻ button to swap in. Only
    meaningful when the current week is complete + the LLM is available."""
    today_iso = _date.today().isoformat()
    with closing(connect()) as conn:
        active_plan = plan_service.get_active_plan(conn)
        plan_weeks = plan_service.get_plan_weeks(conn, active_plan["id"]) if active_plan else []
        cur_week = plan_service.current_plan_week(plan_weeks, today_iso) if plan_weeks else None
        week_wrapped = None
        if active_plan and cur_week:
            stats = plan_service.week_stats(
                conn, active_plan["id"], plan_weeks, cur_week, today_iso
            )
            celebration = celebration_at = None
            if stats["complete"]:
                celebration = llm_commentary.week_wrapped(
                    conn, active_plan["id"], stats, force_refresh=True
                )
                celebration_at = (
                    llm_commentary.week_wrapped_generated_at(conn, active_plan["id"], stats)
                    if celebration else None
                )
            week_wrapped = {
                "stats": stats,
                "celebration": celebration,
                "celebration_generated_at": celebration_at,
            }
    return templates.TemplateResponse(
        request=request,
        name="_week_wrapped.html",
        context={
            "week_wrapped": week_wrapped,
            "llm_available": llm_commentary.connector.is_available(),
        },
    )


def _hydrate_garmin_feel(conn, activity_id: int, run: dict) -> dict:
    """Refresh Garmin's directWorkoutFeel/Rpe on every modal open (single API call,
    ~500 ms). Cached value in the DB serves as a fallback when Garmin is
    unreachable. This lets the user's edits in Garmin Connect show up
    immediately the next time they open the run.

    If the values actually changed, also drops the cached LLM reaction so it
    regenerates with the updated feel/RPE context."""
    if not garmin_auth.is_authenticated():
        return run
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
        data = client.get_activity(activity_id)
        summary = data.get("summaryDTO", {}) or {}
        feel = summary.get("directWorkoutFeel")
        rpe = summary.get("directWorkoutRpe")
        feel_v = int(feel) if isinstance(feel, (int, float)) else None
        rpe_v = int(rpe) if isinstance(rpe, (int, float)) else None
        prior_feel = run.get("garmin_feel")
        prior_rpe = run.get("garmin_rpe")
        conn.execute(
            "UPDATE activities SET garmin_feel = ?, garmin_rpe = ? WHERE activity_id = ?",
            (feel_v, rpe_v, activity_id),
        )
        conn.commit()
        run["garmin_feel"] = feel_v
        run["garmin_rpe"] = rpe_v
        if feel_v != prior_feel or rpe_v != prior_rpe:
            llm_commentary.invalidate_run_reaction(conn, activity_id)
    except Exception:  # noqa: BLE001 — best-effort; cache value (if any) still renders
        pass
    return run


@app.get("/runs/recent", response_class=HTMLResponse)
def recent_runs_page(request: Request, page: int = 1):
    """Dashboard recent-runs pager. Swaps just the table + pager into
    #recent-runs-panel. page 1 is the newest RECENT_RUNS_PER_PAGE runs;
    higher pages walk back in time, capped at RECENT_RUNS_MAX_PAGES.
    Declared before /runs/{activity_id} so "recent" isn't parsed as an id."""
    page = max(1, min(page, RECENT_RUNS_MAX_PAGES))
    offset = (page - 1) * RECENT_RUNS_PER_PAGE
    with closing(connect()) as conn:
        runs = analytics.recent_runs(conn, n=RECENT_RUNS_PER_PAGE, offset=offset)
        total = analytics.count_runs(conn)
    has_next = page < RECENT_RUNS_MAX_PAGES and total > page * RECENT_RUNS_PER_PAGE
    return templates.TemplateResponse(
        request=request,
        name="_recent_runs.html",
        context={
            "runs": runs,
            "page": page,
            "has_prev": page > 1,
            "has_next": has_next,
        },
    )


@app.get("/runs/{activity_id}", response_class=HTMLResponse)
def run_detail(request: Request, activity_id: int):
    with closing(connect()) as conn:
        run = analytics.run_detail(conn, activity_id)
        if not run:
            raise HTTPException(status_code=404, detail="run not found")
        run = _hydrate_garmin_feel(conn, activity_id, run)
        # GPS track for the Route tab — lazy-fetched from Garmin on first
        # open, cached forever after. None hides the tab (treadmill/indoor,
        # not signed in, or the details call failed). See gps_route.py.
        route = gps_route.hydrate_route(conn, activity_id)
        diary_entry = diary_service.get_entry_for_activity(conn, activity_id)
        # Cache-only peek so the modal renders fast. When there's no cache hit,
        # the partial renders a spinner placeholder that triggers /reaction on
        # load via HTMX — this keeps the modal open responsive on first view.
        reaction = llm_commentary.peek_run_reaction(conn, activity_id)
        reaction_generated_at = (
            llm_commentary.run_reaction_generated_at(conn, activity_id) if reaction else None
        )
    # Body-map auto-suggest: high-RPE on an easy run or 'very strong'
    # feel against slow actual pace — prompt the runner to log a niggle.
    body_suggest_after_run = body_service.should_suggest_after_run(run)
    template_name = "_run_detail.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "run": run,
            "route": route,
            "diary_entry": diary_entry,
            "reaction": reaction,
            "reaction_pending": reaction is None,
            "reaction_generated_at": reaction_generated_at,
            "llm_available": llm_commentary.connector.is_available(),
            "body_suggest_after_run": body_suggest_after_run,
        },
    )


@app.get("/runs/{activity_id}/reaction", response_class=HTMLResponse)
def run_reaction_lazy(request: Request, activity_id: int):
    """Lazy-load entry point for the coach reaction. Triggered by the modal's
    spinner placeholder via HTMX `hx-trigger=\"load\"` on first view."""
    with closing(connect()) as conn:
        reaction = llm_commentary.run_reaction(conn, activity_id)
        reaction_generated_at = (
            llm_commentary.run_reaction_generated_at(conn, activity_id) if reaction else None
        )
        verdict = analytics.run_verdict(conn, activity_id)
    return templates.TemplateResponse(
        request=request,
        name="_run_reaction.html",
        context={
            "activity_id": activity_id,
            "reaction": reaction,
            "reaction_pending": False,
            "reaction_generated_at": reaction_generated_at,
            "llm_available": llm_commentary.connector.is_available(),
            "verdict": verdict,
        },
    )


@app.post("/runs/{activity_id}/reaction/refresh", response_class=HTMLResponse)
def run_reaction_refresh(request: Request, activity_id: int):
    """Regenerate the coach's debrief for one activity. Returns the partial
    `_run_reaction.html` which the ↻ button swaps in via HTMX."""
    with closing(connect()) as conn:
        reaction = llm_commentary.run_reaction(conn, activity_id, force_refresh=True)
        reaction_generated_at = (
            llm_commentary.run_reaction_generated_at(conn, activity_id) if reaction else None
        )
        verdict = analytics.run_verdict(conn, activity_id)
    return templates.TemplateResponse(
        request=request,
        name="_run_reaction.html",
        context={
            "activity_id": activity_id,
            "reaction": reaction,
            "reaction_pending": False,
            "reaction_generated_at": reaction_generated_at,
            "llm_available": llm_commentary.connector.is_available(),
            "verdict": verdict,
        },
    )


@app.post("/diary/today", response_class=HTMLResponse)
def diary_today_save(
    request: Request,
    body: str = Form(""),
    mood: str = Form(""),
):
    """Save (or update / delete) today's freestanding diary entry."""
    today = _date.today().isoformat()
    mood_i: int | None = None
    if mood.strip():
        try:
            mood_i = int(mood)
            if mood_i not in diary_service.MOOD_EMOJI:
                mood_i = None
        except ValueError:
            mood_i = None
    with closing(connect()) as conn:
        diary_service.upsert_for_date(conn, today, body, mood_i)
        entry = diary_service.get_entry_for_date(conn, today)
    # Per-theme partial: Tempo uses a variant styled to match `tp-diary-form`
    # so the dashboard editor and the `/diary` form look like one component.
    template_name = "_today_note_editor.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={"today_diary": entry, "today_iso": today, "saved": True},
    )


@app.post("/runs/{activity_id}/diary", response_class=HTMLResponse)
def run_diary_save(
    request: Request,
    activity_id: int,
    body: str = Form(""),
    mood: str = Form(""),  # string so empty submits cleanly
):
    """Inline save from the run-detail modal. Returns just the diary partial."""
    mood_i: int | None = None
    if mood.strip():
        try:
            mood_i = int(mood)
            if mood_i not in diary_service.MOOD_EMOJI:
                mood_i = None
        except ValueError:
            mood_i = None
    with closing(connect()) as conn:
        diary_service.upsert_for_activity(conn, activity_id, body, mood_i)
        diary_entry = diary_service.get_entry_for_activity(conn, activity_id)
        # Diary changed — coach's take on this run is now stale. If the run is
        # in last week's window, the weekly recap is too — invalidate both.
        llm_commentary.invalidate_run_reaction(conn, activity_id)
        llm_commentary.invalidate_weekly_recap(conn)
        # Need run context (so the partial can re-render with feel/rpe etc.) — refetch lightly.
        run = analytics.run_detail(conn, activity_id)
    return templates.TemplateResponse(
        request=request,
        name="_run_diary_editor.html",
        context={"run": run, "diary_entry": diary_entry, "saved": True},
    )


# ---- Training plans -----------------------------------------------------

def _days_to_race(plan: dict | None) -> int | None:
    if not plan or not plan.get("race_date"):
        return None
    try:
        return (_date.fromisoformat(plan["race_date"]) - _date.today()).days
    except ValueError:
        return None


@app.get("/calendar", response_class=HTMLResponse)
def calendar_index(
    request: Request,
    saved: str | None = None,
    error: str | None = None,
    distance: str | None = None,  # 'any' | '10k' | '15k' | 'half' | 'marathon'
    view: str | None = None,      # 'list' (default) | 'agenda'
):
    """Browse upcoming Dutch road races from `race_events` (the curated set
    seeded on first run, plus any user-added). The 'distance' query param
    filters to events with at least one matching distance; 'view' switches
    between the flat list and a monthly calendar grid."""
    today_iso = _date.today().isoformat()
    dist_min: float | None = None
    dist_max: float | None = None
    distance = (distance or "any").lower()
    if distance == "10k":
        dist_min, dist_max = 9.0, 11.0
    elif distance == "15k":
        dist_min, dist_max = 14.0, 17.0
    elif distance == "half":
        dist_min, dist_max = 20.0, 23.0
    elif distance == "marathon":
        dist_min, dist_max = 40.0, 50.0

    view = view if view in ("list", "agenda") else "list"

    with closing(connect()) as conn:
        events = race_calendar_service.list_events(
            conn,
            today_iso=today_iso,
            distance_min=dist_min,
            distance_max=dist_max,
        )
        favorites = race_calendar_service.list_favorites(conn, today_iso=today_iso)
        favorited_ids = {f["id"] for f in favorites}
    months = race_calendar_service.group_by_month(events) if view == "list" else []
    month_grids = race_calendar_service.build_month_grids(events) if view == "agenda" else []
    template_name = "calendar.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "nav_active": "calendar",
            "today_iso": today_iso,
            "saved": saved,
            "error": error,
            "distance_filter": distance,
            "view_mode": view,
            "months": months,
            "month_grids": month_grids,
            "n_events": len(events),
            "favorites": favorites,
            "favorited_ids": favorited_ids,
        },
    )


@app.post("/calendar/events")
def calendar_add_event(
    name: str = Form(...),
    race_date: str = Form(...),
    distance_km: str = Form(...),
    distance_label: str = Form(""),
    city: str = Form(""),
    country_code: str = Form("NL"),
    organizer_url: str = Form(""),
):
    """Add a manual event the aggregator doesn't list."""
    name = (name or "").strip()
    try:
        d = _date.fromisoformat(race_date)
        km = float((distance_km or "").replace(",", "."))
    except (ValueError, TypeError):
        return RedirectResponse(url="/calendar?error=add_bad_data", status_code=303)
    if not name or km <= 0:
        return RedirectResponse(url="/calendar?error=add_bad_data", status_code=303)
    with closing(connect()) as conn:
        race_calendar_service.add_user_event(
            conn,
            name=name,
            race_date=d,
            distance_km=km,
            distance_label=distance_label.strip() or None,
            city=city.strip() or None,
            country_code=country_code.strip() or "NL",
            organizer_url=organizer_url.strip() or None,
        )
    return RedirectResponse(url="/calendar?saved=added", status_code=303)


@app.post("/calendar/events/{event_id}/favorite")
def calendar_favorite(
    request: Request,
    event_id: int,
    distance_km: str = Form(""),
    distance_label: str = Form(""),
):
    """Save an event to the runner's calendar. When called from inside the
    event detail modal (HX-Request header set), returns the re-rendered modal
    body; otherwise (list-view Save button), redirects back to /calendar."""
    km: float | None = None
    if distance_km.strip():
        try:
            km = float(distance_km.replace(",", "."))
        except ValueError:
            km = None
    with closing(connect()) as conn:
        race_calendar_service.favorite(
            conn,
            event_id,
            chosen_distance_km=km,
            chosen_distance_label=distance_label.strip() or None,
        )
        llm_commentary.invalidate_today(conn)
        if request.headers.get("HX-Request"):
            return _render_event_modal(
                request, conn, event_id,
                saved_msg="favorited",
                include_saved_races_oob=True,
            )
    return RedirectResponse(url="/calendar?saved=favorited", status_code=303)


@app.post("/calendar/events/{event_id}/delete")
def calendar_delete_event(event_id: int):
    """Permanently delete an event. Refuses when the event is favorited — the
    user should unfavorite first so they don't silently lose the saved race."""
    with closing(connect()) as conn:
        result = race_calendar_service.delete_event(conn, event_id)
    if not result["deleted"]:
        return RedirectResponse(
            url=f"/calendar?error=delete_blocked&detail={result['reason']}",
            status_code=303,
        )
    return RedirectResponse(url="/calendar?saved=deleted", status_code=303)


@app.post("/runner-races/{rr_id}/delete")
def calendar_unfavorite(rr_id: int):
    with closing(connect()) as conn:
        race_calendar_service.unfavorite(conn, rr_id)
        llm_commentary.invalidate_today(conn)
    return RedirectResponse(url="/calendar?saved=removed", status_code=303)


def _saved_races_oob_partial_name(conn: sqlite3.Connection) -> str:
    """Pick the right Your-Races partial for the active theme. Used both
    by /calendar's first render and by the favorite/unfavorite POSTs
    that need to OOB-swap the saved list."""
    return (
        "_calendar_saved_races.html"
        if theme in ("tempo",)
        else "_calendar_saved_races.html"
    )


def _render_event_modal(
    request: Request,
    conn: sqlite3.Connection,
    event_id: int,
    *,
    enrich_error: str | None = None,
    saved_msg: str | None = None,
    include_saved_races_oob: bool = False,
) -> HTMLResponse:
    """Render the event detail modal body.

    When `include_saved_races_oob=True`, the response also contains the
    "Your races" section marked with `hx-swap-oob="true"` so a
    modal-driven favorite/unfavorite propagates to the list at the
    bottom of /calendar without a full page refresh. Caller decides
    when to opt in — typically the favorite POST handler.
    """
    event = race_calendar_service.get_event(conn, event_id)
    if not event:
        return HTMLResponse(
            '<div class="error" style="padding: 1rem;">Event not found.</div>',
            status_code=404,
        )
    favorites = race_calendar_service.list_favorites(conn)
    favorited_ids = {f["id"] for f in favorites}
    # Swap-into-plan affordance: only meaningful when an active plan covers
    # the event's date. swap_ctx is None without an active plan.
    active_plan = plan_service.get_active_plan(conn)
    swap_ctx = event_swap_service.swap_context(conn, active_plan, event)
    modal_html = templates.get_template("_event_detail_modal.html").render(
        {
            "request": request,
            "event": event,
            "favorited_ids": favorited_ids,
            "enrich_error": enrich_error,
            "saved_msg": saved_msg,
            "active_plan": active_plan,
            "swap_ctx": swap_ctx,
        }
    )
    if not include_saved_races_oob:
        return HTMLResponse(modal_html)

    oob_html = templates.get_template(_saved_races_oob_partial_name(conn)).render(
        {
            "request": request,
            "favorites": favorites,
            "oob": True,
        }
    )
    return HTMLResponse(modal_html + oob_html)


@app.get("/calendar/events/{event_id}/detail", response_class=HTMLResponse)
def event_detail(request: Request, event_id: int):
    """Render the event detail modal body. Loaded via HTMX into #event-detail-body."""
    with closing(connect()) as conn:
        return _render_event_modal(request, conn, event_id)


@app.post("/calendar/events/{event_id}/enrich", response_class=HTMLResponse)
def event_enrich(request: Request, event_id: int, url: str = Form(...)):
    """Scrape the organiser URL, download hero image, save fields. Returns the
    re-rendered modal body for HTMX to swap in."""
    with closing(connect()) as conn:
        if not (url or "").strip():
            return _render_event_modal(request, conn, event_id, enrich_error="no_url")
        updated, err = race_calendar_service.enrich_from_url(conn, event_id, url)
        if err:
            return _render_event_modal(request, conn, event_id, enrich_error=err)
        return _render_event_modal(request, conn, event_id, saved_msg="enriched")


@app.post("/calendar/events/{event_id}/manual", response_class=HTMLResponse)
def event_enrich_manual(
    request: Request,
    event_id: int,
    organizer_url: str = Form(""),
    hero_image_url: str = Form(""),
    description: str = Form(""),
):
    """Save manual-edit fields. Doesn't download images — `hero_image_url` is
    used as-is (external link). Returns the re-rendered modal body."""
    with closing(connect()) as conn:
        race_calendar_service.save_enrichment(
            conn,
            event_id,
            organizer_url=organizer_url,
            description=description,
            hero_image_url=hero_image_url,
        )
        return _render_event_modal(request, conn, event_id, saved_msg="manual")


@app.get("/calendar/events/{event_id}/swap-preview", response_class=HTMLResponse)
def event_swap_preview(
    request: Request,
    event_id: int,
    distance_km: float,
    distance_label: str = "",
):
    """Inline confirm strip for swapping this event into the active plan.
    Loaded via HTMX into #event-swap-zone inside the event detail modal after
    the user picks a distance."""
    with closing(connect()) as conn:
        event = race_calendar_service.get_event(conn, event_id)
        if not event:
            raise HTTPException(status_code=404, detail="event not found")
        plan = plan_service.get_active_plan(conn)
        swap_ctx = event_swap_service.swap_context(conn, plan, event)
    if not swap_ctx or not swap_ctx["eligible"]:
        return HTMLResponse(
            '<div class="error" style="margin-top: 0.6rem;">'
            + _t("This event can't be added to your plan right now — reload the page and try again.")
            + "</div>"
        )
    return templates.TemplateResponse(
        request=request,
        name="_event_swap_confirm.html",
        context={
            "event": event,
            "plan": plan,
            "swap_ctx": swap_ctx,
            "distance_km": distance_km,
            "distance_label": distance_label,
        },
    )


@app.post("/calendar/events/{event_id}/swap-into-plan")
def event_swap_into_plan(
    request: Request,
    event_id: int,
    distance_km: str = Form(...),
    distance_label: str = Form(""),
    displaced_workout_id: str = Form(""),
):
    """Place the event on the active plan as a race workout, optionally
    converting one other session that week into a rest day. Fully reversible
    from the plan-workout modal (see /plan-workouts/{id}/revert-event-swap)."""
    try:
        km = float((distance_km or "").replace(",", "."))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid distance")
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
    except Exception:  # noqa: BLE001 — Garmin cleanup is best-effort
        client = None
    try:
        with closing(connect()) as conn:
            event_swap_service.apply_swap(
                conn,
                client,
                event_id=event_id,
                distance_km=km,
                distance_label=distance_label.strip() or None,
                displaced_workout_id=_parse_optional_int(displaced_workout_id),
            )
            llm_commentary.invalidate_today(conn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    # Land on the plan so the runner sees the race day in place. HTMX posts
    # get an HX-Redirect (full navigation); plain form posts a 303.
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": "/plans"})
    return RedirectResponse(url="/plans", status_code=303)


@app.post("/plan-workouts/{pw_id}/revert-event-swap")
def revert_event_swap(pw_id: int):
    """Undo an event swap from the plan-workout modal: restores the original
    workout(s) and removes the race from the plan."""
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
    except Exception:  # noqa: BLE001
        client = None
    try:
        with closing(connect()) as conn:
            swap = event_swap_service.get_swap_for_workout(conn, pw_id)
            if not swap:
                raise ValueError("no event swap on this workout")
            event_swap_service.revert_swap(conn, client, swap["id"])
            llm_commentary.invalidate_today(conn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(url="/plans", status_code=303)


@app.get("/diary", response_class=HTMLResponse)
def diary_index(request: Request, error: str | None = None, prefill_date: str | None = None):
    today_iso = _date.today().isoformat()
    with closing(connect()) as conn:
        entries = diary_service.list_entries(conn)
        weeks = diary_service.group_by_iso_week(entries)
        streak = diary_service.entry_streak(entries)
    template_name = "diary.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "weeks": weeks,
            "n_entries": len(entries),
            "streak": streak,
            "nav_active": "diary",
            "today_iso": today_iso,
            "prefill_date": prefill_date or today_iso,
            "error": error,
        },
    )


@app.get("/diary/entries/{entry_id}", response_class=HTMLResponse)
def diary_entry_show(request: Request, entry_id: int):
    """Display partial for one entry. Used by HTMX to cancel an edit."""
    with closing(connect()) as conn:
        e = diary_service.get_entry_with_links(conn, entry_id)
    if not e:
        return HTMLResponse("", status_code=200)
    return templates.TemplateResponse(
        request=request,
        name="_diary_entry_card.html",
        context={"e": e},
    )


@app.get("/diary/entries/{entry_id}/edit", response_class=HTMLResponse)
def diary_entry_edit_form(request: Request, entry_id: int):
    """Edit-form partial. Swapped in by HTMX when the user clicks ✎."""
    with closing(connect()) as conn:
        e = diary_service.get_entry(conn, entry_id)
    if not e:
        return HTMLResponse("", status_code=200)
    return templates.TemplateResponse(
        request=request,
        name="_diary_entry_edit.html",
        context={"e": e},
    )


@app.post("/diary/entries/{entry_id}", response_class=HTMLResponse)
def diary_entry_save(
    request: Request,
    entry_id: int,
    body: str = Form(""),
    mood: str = Form(""),
):
    """Save an in-place edit. Empty body + no mood deletes the row."""
    mood_i: int | None = None
    if mood.strip():
        try:
            mood_i = int(mood)
            if mood_i not in diary_service.MOOD_EMOJI:
                mood_i = None
        except ValueError:
            mood_i = None

    with closing(connect()) as conn:
        updated = diary_service.update_entry(conn, entry_id, body, mood_i)
        # Recent diary feeds today's coach line — drop the cache so it picks up.
        # Edits can target last week's entries too, so refresh the recap as well.
        llm_commentary.invalidate_today(conn)
        llm_commentary.invalidate_weekly_recap(conn)

    if not updated:
        # Deleted (empty body + no mood) — swap the card out of the timeline.
        return HTMLResponse("", status_code=200)
    return templates.TemplateResponse(
        request=request,
        name="_diary_entry_card.html",
        context={"e": updated},
    )


@app.post("/diary/new")
def diary_new(
    entry_date: str = Form(...),
    body: str = Form(""),
    mood: str = Form(""),
):
    """Backfill (or add for today) a freestanding diary entry on any date."""
    body = body.strip()
    try:
        # Validate the date — must be a real ISO date, not arbitrary text.
        _date.fromisoformat(entry_date)
    except ValueError:
        return RedirectResponse(
            url=f"/diary?error=bad_date&prefill_date={entry_date}",
            status_code=303,
        )

    if not body and not mood.strip():
        return RedirectResponse(
            url=f"/diary?error=empty&prefill_date={entry_date}",
            status_code=303,
        )

    mood_i: int | None = None
    if mood.strip():
        try:
            mood_i = int(mood)
            if mood_i not in diary_service.MOOD_EMOJI:
                mood_i = None
        except ValueError:
            mood_i = None

    with closing(connect()) as conn:
        diary_service.upsert_for_date(conn, entry_date, body, mood_i)
        # Recent diary feeds today's coach line — drop the cache so it picks up.
        # Backfilled entries can be in last week's window — refresh the recap too.
        llm_commentary.invalidate_today(conn)
        llm_commentary.invalidate_weekly_recap(conn)
    return RedirectResponse(url="/diary", status_code=303)


# ── Body / wellbeing check-in ────────────────────────────────────────
# Fuel tab — nutrition & hydration. Read-only view computed from the body
# profile + the day's workout (+ Garmin metrics when present). A date query
# param steps through days like the calendar. See docs/nutrition-fueling.md.

@app.get("/fuel", response_class=HTMLResponse)
def fuel_index(request: Request, day: str | None = None):
    """Fuel tab. `day` is an ISO date (defaults to today). Renders an
    empty state linking to Settings when no body profile is set yet."""
    try:
        ref_day = _date.fromisoformat(day) if day else _date.today()
    except ValueError:
        ref_day = _date.today()
    with closing(connect()) as conn:
        fuel = fuel_service.fuel_for_date(conn, ref_day)
        strip = (
            fuel_service.weekly_fuel_strip(conn, fuel["profile"], ref_day)
            if fuel else None
        )
        # Day selector: today + next 6, with the open day highlighted.
        day_strip = (
            fuel_service.fuel_day_strip(
                conn, fuel["profile"], _date.today(),
                selected_iso=ref_day.isoformat(),
            )
            if fuel else None
        )
    return templates.TemplateResponse(
        request=request,
        name="fuel.html",
        context={
            "nav_active": "fuel",
            "fuel": fuel,
            "strip": strip,
            "day_strip": day_strip,
            "ref_day": ref_day.isoformat(),
            "is_today": ref_day == _date.today(),
        },
    )


# Interactive body-map tab. Routes mirror the diary shape — full-page
# GET for the main tab, HTMX partials for in-place updates, every
# write invalidates the daily coach cache so the LLM picks up new
# body state on next render. See docs/body-wellbeing-checkin.md.

@app.get("/body", response_class=HTMLResponse)
def body_index(
    request: Request,
    view: str = "active",
    window: int = 90,
    prefill_region: str | None = None,
    prefill_side: str | None = None,
):
    """Body tab. `view` selects between active / history / heatmap;
    `window` is the heatmap aggregation window in days."""
    view = view if view in ("active", "history", "heatmap") else "active"
    window = window if window in (90, 180, 365) else 90
    with closing(connect()) as conn:
        active = body_service.active_issues(conn)
        history = body_service.recent_resolved(conn, days=180)
        heatmap = body_service.heatmap_aggregates(conn, window_days=window)
        heatmap_by_dk = (
            body_service.heatmap_by_design_key(conn, window_days=window)
            if view == "heatmap" else {}
        )
        latest_clear = body_service.latest_clear_log(conn)
        streak = body_service.streak_days(conn)
    # active_map: design_key → severity_band_num (1/2/3). Drives the
    # diagram's glow ellipses. Keeps the worst band when multiple
    # issues touch the same region+side.
    active_map: dict[str, int] = {}
    for issue in active:
        dk = issue["design_key"]
        b = issue["severity_band_num"]
        if b > 0 and (dk not in active_map or b > active_map[dk]):
            active_map[dk] = b
    return templates.TemplateResponse(
        request=request,
        name="body.html",
        context={
            "nav_active": "body",
            "view": view,
            "window": window,
            "active_issues": active,
            "history": history,
            "heatmap": heatmap,
            "heatmap_by_design_key": heatmap_by_dk,
            "latest_clear": latest_clear,
            "regions": body_service.REGIONS,
            "midline_regions": body_service.MIDLINE_REGIONS,
            "issue_types": body_service.ISSUE_TYPES,
            "structure_library": body_service.STRUCTURE_LIBRARY,
            "active_map": active_map,
            "streak": streak,
            "selected_key": None,
            "prefill_region": prefill_region,
            "prefill_side": prefill_side,
            "has_any_data": bool(active) or bool(history) or bool(latest_clear),
        },
    )




@app.get("/body/region/{region}/{side}", response_class=HTMLResponse)
def body_region_panel(request: Request, region: str, side: str):
    """Entry-panel partial for one region+side. Returns the new-issue
    form, or the update-existing sheet when an active issue already
    exists for this region+side."""
    if region not in body_service.REGIONS:
        return HTMLResponse("", status_code=200)
    if region in body_service.MIDLINE_REGIONS:
        if side != "midline":
            return HTMLResponse("", status_code=200)
    else:
        if side not in ("left", "right"):
            return HTMLResponse("", status_code=200)
    with closing(connect()) as conn:
        existing = body_service.latest_severity_log_for_issue(conn, region, side)
    return templates.TemplateResponse(
        request=request,
        name="_body_entry_panel.html",
        context={
            "region": region,
            "side": side,
            "region_label": body_service.slug_label(region),
            "issue_types": body_service.ISSUE_TYPES,
            "structures": body_service.STRUCTURE_LIBRARY.get(region, ()),
            "structure_library": body_service.STRUCTURE_LIBRARY,
            "existing": existing,
        },
    )


@app.post("/body/issues", response_class=HTMLResponse)
def body_issue_create(
    request: Request,
    region: str = Form(...),
    side: str = Form(...),
    issue_type: str = Form(...),
    severity: int = Form(...),
    structure_name: str = Form(""),
    note: str = Form(""),
):
    """Create a new active issue. Returns the refreshed active list partial."""
    with closing(connect()) as conn:
        try:
            body_service.record_issue(
                conn,
                region=region,
                side=side,
                issue_type=issue_type,
                severity=severity,
                structure_name=structure_name.strip() or None,
                note=note.strip() or None,
            )
        except ValueError:
            # Bad enum / range — swallow + return current list. Defence
            # in depth; the form constrains inputs.
            pass
        active = body_service.active_issues(conn)
        # Invalidate today's coach voice — body state just changed.
        llm_commentary.invalidate_today(conn)
    return templates.TemplateResponse(
        request=request,
        name="_body_active_issues.html",
        context={"active_issues": active},
    )


@app.post("/body/issues/{issue_id}/update", response_class=HTMLResponse)
def body_issue_update(
    request: Request,
    issue_id: int,
    severity: str = Form(""),
    issue_type: str = Form(""),
    structure_name: str = Form(""),
    note: str = Form(""),
):
    """Update an existing issue. All fields optional — empty values
    are no-ops. Returns the refreshed single card partial."""
    with closing(connect()) as conn:
        if severity.strip():
            try:
                body_service.update_severity(conn, issue_id, int(severity))
            except (ValueError, TypeError):
                pass
        # Field updates — only pass values the form actually carried.
        fields: dict[str, str | None] = {}
        if issue_type.strip():
            fields["issue_type"] = issue_type.strip()
        if structure_name != "":  # explicit empty allowed → clear
            fields["structure_name"] = structure_name.strip() or None
        if note != "":
            fields["note"] = note.strip() or None
        if fields:
            try:
                body_service.update_issue_fields(conn, issue_id, **fields)
            except ValueError:
                pass
        llm_commentary.invalidate_today(conn)
        # Return the refreshed active list — simplest UI flow; the
        # single card is embedded in it. Phase 3 may swap to a
        # single-card response if perf matters.
        active = body_service.active_issues(conn)
    return templates.TemplateResponse(
        request=request,
        name="_body_active_issues.html",
        context={"active_issues": active},
    )


@app.post("/body/issues/{issue_id}/resolve", response_class=HTMLResponse)
def body_issue_resolve(request: Request, issue_id: int, reason: str = Form("manual")):
    """Mark an issue resolved. Returns the refreshed active list."""
    with closing(connect()) as conn:
        try:
            body_service.resolve_issue(conn, issue_id, reason=reason)
        except ValueError:
            pass
        llm_commentary.invalidate_today(conn)
        active = body_service.active_issues(conn)
    return templates.TemplateResponse(
        request=request,
        name="_body_active_issues.html",
        context={"active_issues": active},
    )


@app.post("/body/issues/{issue_id}/unresolve", response_class=HTMLResponse)
def body_issue_unresolve(request: Request, issue_id: int):
    """Reopen a previously resolved issue. Returns the refreshed active list."""
    with closing(connect()) as conn:
        body_service.unresolve_issue(conn, issue_id)
        llm_commentary.invalidate_today(conn)
        active = body_service.active_issues(conn)
    return templates.TemplateResponse(
        request=request,
        name="_body_active_issues.html",
        context={"active_issues": active},
    )


@app.post("/body/clear", response_class=HTMLResponse)
def body_clear(request: Request):
    """Log an 'I'm all good right now' check-in from the dashboard
    daily prompt. Returns an empty body — the calling banner closes
    itself via the empty HTMX response."""
    with closing(connect()) as conn:
        body_service.record_clear(conn)
        llm_commentary.invalidate_today(conn)
    return HTMLResponse("", status_code=200)


@app.get("/body/heatmap", response_class=HTMLResponse)
def body_heatmap(request: Request, window: int = 90):
    """Heatmap partial — full heat-grid card (diagram + window picker +
    legend + top-zones aside). Returned both inline by GET /body?view=
    heatmap and standalone for the HTMX window-picker swap."""
    window = window if window in (90, 180, 365) else 90
    with closing(connect()) as conn:
        heatmap = body_service.heatmap_aggregates(conn, window_days=window)
        heatmap_by_dk = body_service.heatmap_by_design_key(conn, window_days=window)
    return templates.TemplateResponse(
        request=request,
        name="_body_heatmap.html",
        context={
            "heatmap": heatmap,
            "heatmap_by_design_key": heatmap_by_dk,
            "window": window,
        },
    )


@app.get("/plans", response_class=HTMLResponse)
def plans_index(request: Request):
    today_iso = _date.today().isoformat()
    with closing(connect()) as conn:
        active = plan_service.get_active_plan(conn)
        archive = plan_service.list_plans(conn, status="inactive")
        active_weeks = plan_service.get_plan_weeks(conn, active["id"]) if active else []
        adherence = plan_service.plan_adherence(conn, active["id"], today_iso) if active else None
        # Optional strength sessions, keyed by ISO date so the week-card
        # template can render the chip alongside the rest-day cell.
        from running_coach.strength import service as _strength_service
        strength_by_date = (
            _strength_service.sessions_by_date_for_plan(conn, active["id"])
            if active and active.get("include_optional_strength")
            else {}
        )
    methodology_lookup = {m.id: m for m in list_methodologies()}
    template_name = "plans.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "active": active,
            "active_weeks": active_weeks,
            "archive": archive,
            "methodology_lookup": methodology_lookup,
            "days_to_race": _days_to_race(active),
            "adherence": adherence,
            "strength_by_date": strength_by_date,
            "nav_active": "plans",
            "today_iso": today_iso,
        },
    )


@app.get("/plans/new", response_class=HTMLResponse)
def plans_new_form(
    request: Request,
    from_event: int | None = None,
    distance_km: str | None = None,
    distance_label: str | None = None,
):
    with closing(connect()) as conn:
        seed = plan_service.get_plan_seed(conn)
        rec = recommend_plan(
            seed,
            app_settings.get_can_run_10min(conn),
            frozenset(m.id for m in list_methodologies() if m.available),
        )
        # If launched from a calendar event, pre-fill race date + goal + title.
        prefill_event: dict | None = None
        form_values: dict = {}
        if from_event:
            prefill_event = race_calendar_service.get_event(conn, from_event)
        if prefill_event:
            km_value: float | None = None
            if distance_km:
                try:
                    km_value = float(distance_km.replace(",", "."))
                except (ValueError, TypeError):
                    km_value = None
            if km_value is None and prefill_event["distances"]:
                # Default to the longest supported distance.
                supported = [
                    d for d in prefill_event["distances"]
                    if race_calendar_service.goal_type_for_distance(d.get("km") or 0)
                ]
                if supported:
                    km_value = max(d["km"] for d in supported)
            goal = race_calendar_service.goal_type_for_distance(km_value) if km_value else None
            form_values = {
                "race_date": prefill_event["race_date"],
                "goal_type": goal or "",
                "title": f"{prefill_event['name']} · {distance_label or ''}".strip(" ·"),
                "from_event_id": prefill_event["id"],
                "chosen_distance_km": km_value,
                "chosen_distance_label": distance_label or "",
            }
    return templates.TemplateResponse(
        request=request,
        name="plans_new.html",
        context={
            "methodologies": list_methodologies(),
            "seed": seed,
            "goal_distances": GOAL_DISTANCES_KM,
            "nav_active": "plans",
            "form_values": form_values,
            "prefill_event": prefill_event,
            "start_options": _plan_start_options(),
            "rec": rec,
            "ask_can_run_10min": rec.methodology_id is None,
        },
    )


@app.get("/plans/methodology/{methodology_id}/detail", response_class=HTMLResponse)
def methodology_detail(request: Request, methodology_id: str):
    """Long-form "Read more" content for a methodology tile. Loaded via HTMX
    into #method-detail-content on /plans/new, then shown as a modal. Falls back
    to the tile description when no explainer has been authored yet."""
    try:
        info = get_methodology_info(methodology_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Unknown methodology")
    ex = get_explainer(methodology_id, _current_language())
    # Which illustrations have a rendered PNG pair on disk — the template shows
    # the image for those and the placeholder+prompt box for the rest.
    illus_dir = STATIC_DIR / "method-detail"
    illus_ready: set[str] = set()
    if ex:
        for section in ex.sections:
            ill = section.illustration
            if ill is None:
                continue
            key = f"{info.id}-{ill.slug}"
            if (illus_dir / f"{key}-light.png").exists() and (illus_dir / f"{key}-dark.png").exists():
                illus_ready.add(key)
    return templates.TemplateResponse(
        request=request,
        name="_method_detail.html",
        context={
            "m": info,
            "ex": ex,
            "illustration_style": ILLUSTRATION_STYLE,
            "illus_ready": illus_ready,
        },
    )


def _pending_push_count(conn, plan_id: int) -> int:
    """How many of this plan's workouts still carry a Garmin id."""
    row = conn.execute(
        "SELECT COUNT(*) FROM plan_workouts "
        "WHERE plan_id = ? AND garmin_workout_id IS NOT NULL",
        (plan_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def _try_cleanup_garmin_workouts(conn, plan_id: int) -> dict[str, int]:
    """Best-effort: remove this plan's pushed workouts from Garmin Connect.

    Returns {"cleaned": n, "failed": n}. The plan state change goes ahead
    either way — cleanup is a nice-to-have — but the result is *returned*
    rather than swallowed, because a workout we failed to delete is still
    sitting on the runner's watch and they can only act on that if told.

    An auth/network failure means nothing was deleted, so every workout that
    still has an id counts as failed.
    """
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
        return plan_service.cleanup_pushed_workouts(conn, client, plan_id)
    except Exception:  # noqa: BLE001 — Garmin unreachable; report, don't raise
        return {"cleaned": 0, "failed": _pending_push_count(conn, plan_id)}


def _plan_start_options() -> dict[str, str]:
    """ISO dates for the form's start-week picker: the Monday of the current
    week ("this") and the next Monday ("next", the default)."""
    today = _date.today()
    this_monday = today - _timedelta(days=today.weekday())
    return {
        "this": this_monday.isoformat(),
        "next": (this_monday + _timedelta(days=7)).isoformat(),
    }


def _render_new_form_with_error(request: Request, error: str, form_values: dict):
    """Re-render the create form with an error banner and the user's previous inputs."""
    with closing(connect()) as conn:
        seed = plan_service.get_plan_seed(conn)
        rec = recommend_plan(
            seed,
            app_settings.get_can_run_10min(conn),
            frozenset(m.id for m in list_methodologies() if m.available),
        )
    return templates.TemplateResponse(
        request=request,
        name="plans_new.html",
        context={
            "methodologies": list_methodologies(),
            "seed": seed,
            "goal_distances": GOAL_DISTANCES_KM,
            "nav_active": "plans",
            "form_error": error,
            "form_values": form_values,
            "start_options": _plan_start_options(),
            "rec": rec,
            "ask_can_run_10min": rec.methodology_id is None,
        },
    )


@app.post("/plans/new/self-assessment")
def plans_new_self_assessment(answer: str = Form(...)):
    """The /plans/new question strip ("Can you currently run 10 minutes
    non-stop?"). Persist and re-render — the strip only shows when the form
    is still at its blank-slate defaults, so a full reload loses nothing."""
    with closing(connect()) as conn:
        if answer in ("yes", "no"):
            app_settings.set_can_run_10min(conn, answer == "yes")
    return RedirectResponse(url="/plans/new", status_code=303)


@app.post("/plans/new")
def plans_new_submit(
    request: Request,
    goal_type: str = Form(...),
    methodology_id: str = Form(...),
    variant: str = Form(""),
    days_per_week: int = Form(...),
    long_run_day: int = Form(...),
    workout_days: list[int] = Form(default=[]),
    race_date: str = Form(""),
    start_when: str = Form("next"),
    target_hours: str = Form(""),
    target_minutes: str = Form(""),
    title: str = Form(""),
    from_event_id: str = Form(""),
    chosen_distance_km: str = Form(""),
    chosen_distance_label: str = Form(""),
    include_optional_strength: str = Form(""),
):
    form_values = {
        "goal_type": goal_type, "methodology_id": methodology_id,
        "variant": variant,
        "days_per_week": days_per_week, "long_run_day": long_run_day,
        "workout_days_list": workout_days,
        "race_date": race_date, "start_when": start_when,
        "target_hours": target_hours,
        "target_minutes": target_minutes, "title": title,
        "from_event_id": from_event_id, "chosen_distance_km": chosen_distance_km,
        "chosen_distance_label": chosen_distance_label,
        "include_optional_strength": include_optional_strength,
    }

    # Fixed-schedule methodologies (Foppen, Pfitzinger) own their weekly
    # pattern — the pickers are neutralised client-side and their values
    # ignored here; create_plan persists the schedule the engine generates.
    try:
        fixed_schedule = get_methodology_info(methodology_id).fixed_schedule
    except ValueError:
        return _render_new_form_with_error(request, "Unknown methodology.", form_values)

    # Validate the workout-day selection up front so the user sees a friendly
    # message rather than a stack trace.
    if workout_days and not fixed_schedule:
        try:
            workout_days_clean = sorted({int(d) for d in workout_days})
        except (ValueError, TypeError):
            return _render_new_form_with_error(request, "Invalid workout-day value.", form_values)
        if any(d not in range(7) for d in workout_days_clean):
            return _render_new_form_with_error(request, "Workout days must be 0-6 (Mon-Sun).", form_values)
        if len(workout_days_clean) != days_per_week:
            return _render_new_form_with_error(
                request,
                f"Pick exactly {days_per_week} workout days (got {len(workout_days_clean)}).",
                form_values,
            )
        if long_run_day not in workout_days_clean:
            return _render_new_form_with_error(
                request, "Long run day must be one of the picked workout days.", form_values,
            )
    else:
        workout_days_clean = None

    race_d: _date | None = None
    if race_date:
        try:
            race_d = _date.fromisoformat(race_date)
        except ValueError:
            return _render_new_form_with_error(request, "Invalid race date.", form_values)
        if race_d <= _date.today():
            return _render_new_form_with_error(request, "Race date must be in the future.", form_values)

    # A race date is only mandatory for race-specific imported plans (e.g.
    # Foppen 7 Heuvelen). Every other methodology builds fine without one —
    # create_plan runs the full default length from the chosen start week
    # and synthesizes a goal date on the final week's long-run day.
    if race_d is None and get_methodology_info(methodology_id).requires_race_date:
        return _render_new_form_with_error(
            request, "This plan targets a specific race — pick its date.", form_values,
        )

    # Start week: default is next Monday; "this" starts the plan in the
    # current week (Monday-aligned, so earlier weekdays simply read as past).
    today = _date.today()
    this_monday = today - _timedelta(days=today.weekday())
    start_d = this_monday if start_when == "this" else this_monday + _timedelta(days=7)

    target_time_s: int | None = None
    h = int(target_hours) if target_hours.strip() else 0
    m = int(target_minutes) if target_minutes.strip() else 0
    if h or m:
        target_time_s = h * 3600 + m * 60

    with closing(connect()) as conn:
        prior = plan_service.get_active_plan(conn)
        try:
            new_plan_id = plan_service.create_plan(
                conn,
                goal_type=goal_type,
                methodology_id=methodology_id,
                race_date=race_d,
                target_time_s=target_time_s,
                days_per_week=days_per_week,
                long_run_day=long_run_day,
                workout_days=workout_days_clean,
                title=title.strip() or None,
                variant=variant.strip() or None,
                start_date=start_d,
            )
        except ValueError as exc:
            # Methodology-specific validation (e.g. Foppen needs goal_type=15k and a Sunday race date).
            return _render_new_form_with_error(request, str(exc), form_values)
        if prior:
            _try_cleanup_garmin_workouts(conn, prior["id"])
        # Optional strength toggle: when checked, flip the plan column on
        # and seed the strength schedule across every future rest day.
        if include_optional_strength.strip():
            conn.execute(
                "UPDATE plans SET include_optional_strength = 1 WHERE id = ?",
                (new_plan_id,),
            )
            conn.commit()
            from running_coach.strength import scheduler as _strength_sched
            _strength_sched.assign_for_plan(conn, new_plan_id)
        # If launched from a calendar event, mark it as the A-race for this plan.
        if from_event_id.strip().isdigit():
            km_val: float | None = None
            if chosen_distance_km.strip():
                try:
                    km_val = float(chosen_distance_km.replace(",", "."))
                except ValueError:
                    km_val = None
            try:
                race_calendar_service.favorite(
                    conn,
                    int(from_event_id),
                    chosen_distance_km=km_val,
                    chosen_distance_label=chosen_distance_label.strip() or None,
                    plan_id=new_plan_id,
                    is_a_race=True,
                )
            except Exception:  # noqa: BLE001 — non-fatal
                pass
    return RedirectResponse(url="/plans", status_code=303)


@app.get("/plans/{plan_id}/edit", response_class=HTMLResponse)
def plan_edit_modal(request: Request, plan_id: int):
    """Plan-settings modal payload — Tier-1 metadata (title + notes). Loaded
    lazily into the plans-page dialog via HTMX when the user clicks "Edit"."""
    with closing(connect()) as conn:
        plan = plan_service.get_plan(conn, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="plan not found")
    try:
        m_info = get_methodology_info(plan["methodology"])
    except ValueError:
        m_info = None
    plan_workout_days = (
        [int(d) for d in str(plan["workout_days"]).split(",")]
        if plan.get("workout_days") else []
    )
    partial = "_plan_settings_modal.html"
    return templates.TemplateResponse(
        request=request,
        name=partial,
        context={
            "plan": plan,
            "methodology_info": m_info,
            "plan_workout_days": plan_workout_days,
        },
    )


@app.post("/plans/{plan_id}/edit")
def plan_edit_save(
    plan_id: int,
    title: str = Form(""),
    notes: str = Form(""),
    include_optional_strength: str = Form(""),
):
    """Tier-1 plan edit — saves title, notes, and the optional-strength
    toggle. Flipping the toggle ON seeds strength sessions across every
    future rest day; flipping it OFF clears upcoming sessions but keeps
    completed ones — including one completed today — and keeps any session
    still on the watch that Garmin would not release."""
    new_toggle = 1 if include_optional_strength.strip() else 0
    # Stays None when the toggle didn't change, so the check after the try
    # block is always safe.
    strength_cleared: dict | None = None
    try:
        with closing(connect()) as conn:
            plan_service.update_plan_metadata(
                conn,
                plan_id,
                title=title if title else None,
                notes=notes,  # empty string clears notes; None would skip
            )
            row = conn.execute(
                "SELECT include_optional_strength FROM plans WHERE id = ?",
                (plan_id,),
            ).fetchone()
            old_toggle = int(row["include_optional_strength"]) if row else 0
            if new_toggle != old_toggle:
                conn.execute(
                    "UPDATE plans SET include_optional_strength = ? WHERE id = ?",
                    (new_toggle, plan_id),
                )
                conn.commit()
                from running_coach.strength import (
                    scheduler as _strength_sched,
                    service as _strength_service,
                )
                today_iso = _date.today().isoformat()
                if new_toggle:
                    _strength_sched.assign_for_plan(conn, plan_id, today_iso=today_iso)
                else:
                    # Try for a client so pushed sessions come off the watch
                    # before their rows go. Not being connected is fine — the
                    # pushed rows are then kept, not silently stranded.
                    try:
                        _client = get_client(prompt_mfa=_refuse_mfa)
                    except Exception:  # noqa: BLE001
                        _client = None
                    strength_cleared = _strength_service.clear_future_sessions(
                        conn, plan_id, today_iso, client=_client
                    )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if strength_cleared and strength_cleared["kept_pushed"]:
        return RedirectResponse(
            url=f"/plans?error=strength_kept&kept={strength_cleared['kept_pushed']}",
            status_code=303,
        )
    return RedirectResponse(url="/plans", status_code=303)


@app.post("/plans/{plan_id}/vdot")
def plan_update_vdot(plan_id: int, vdot: float = Form(...)):
    """Manually override the plan's VDOT (Tier 2b). Garmin's VO2max
    estimate is the default, but runners can dial it down based on actual
    race performance — see estimate_vdot_from_race for the calculator.
    Does NOT auto-recalibrate; the banner on /plans prompts the runner
    to do that explicitly."""
    try:
        with closing(connect()) as conn:
            result = plan_service.update_plan_vdot(conn, plan_id, vdot)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(
        url=(
            f"/plans?saved=vdot_updated"
            f"&old_vdot={result['old']:.1f}&new_vdot={result['new']:.1f}"
        ),
        status_code=303,
    )


@app.post("/plans/{plan_id}/reshape")
def plan_reshape(
    plan_id: int,
    race_date: str = Form(""),
    days_per_week: int = Form(0),
    long_run_day: int = Form(-1),
    workout_days: list[int] = Form(default=[]),
):
    """Tier 2c/d — change training days, long-run day, and/or race date.
    Regenerates the plan with the new schedule and splices it in from today
    onward; history and completed workouts stay locked. Pushed future
    workouts are removed from Garmin best-effort (re-push per week)."""
    from urllib.parse import quote

    race_d: _date | None = None
    if race_date.strip():
        try:
            race_d = _date.fromisoformat(race_date.strip())
        except ValueError:
            return RedirectResponse(
                url=f"/plans?reshape_error={quote('Invalid race date.')}",
                status_code=303,
            )

    client = None
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
    except Exception:  # noqa: BLE001 — Garmin cleanup is best-effort
        client = None

    with closing(connect()) as conn:
        try:
            result = plan_service.reshape_plan(
                conn,
                client,
                plan_id,
                race_date=race_d,
                days_per_week=days_per_week or None,
                long_run_day=long_run_day if long_run_day >= 0 else None,
                workout_days=[int(d) for d in workout_days] if workout_days else None,
            )
        except ValueError as exc:
            return RedirectResponse(
                url=f"/plans?reshape_error={quote(str(exc))}", status_code=303
            )
    return RedirectResponse(
        url=(
            f"/plans?saved=reshaped"
            f"&n_added={result['n_added']}&n_removed={result['n_removed']}"
            f"&garmin_cleaned={result['garmin_cleaned']}"
            # Reshape deletes the old rows outright, so a failed Garmin delete
            # leaves an orphan with no local id to retry — the runner has to
            # know, or stale sessions sit on the watch forever.
            f"&garmin_failed={result['garmin_failed']}"
        ),
        status_code=303,
    )


@app.get("/plans/{plan_id}/recalibrate-paces", response_class=HTMLResponse)
def plan_recalibrate_preview(request: Request, plan_id: int):
    """Preview partial: what `recalibrate_paces` would change without writing.
    HTMX-loaded into the plan-settings modal so the runner sees the deltas
    before committing."""
    today_iso = _date.today().isoformat()
    with closing(connect()) as conn:
        try:
            preview = plan_service.preview_recalibrate_paces(conn, plan_id, today_iso)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
    partial = "_recalibrate_preview.html"
    return templates.TemplateResponse(
        request=request,
        name=partial,
        context={"plan_id": plan_id, "preview": preview},
    )


@app.post("/plans/{plan_id}/recalibrate-paces")
def plan_recalibrate_apply(plan_id: int):
    """Apply the pace recalibration. Best-effort Garmin re-push on previously-
    pushed workouts (same pattern as the per-workout manual edit)."""
    today_iso = _date.today().isoformat()
    try:
        try:
            client = get_client(prompt_mfa=_refuse_mfa)
        except Exception:  # noqa: BLE001
            client = None
        with closing(connect()) as conn:
            result = plan_service.recalibrate_paces(conn, client, plan_id, today_iso)
            llm_commentary.invalidate_today(conn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(
        url=(
            f"/plans?saved=recalibrated&n_updated={result['n_updated']}"
            f"&n_desc_healed={result.get('n_desc_healed', 0)}"
            f"&n_re_pushed={len(result['re_pushed'])}"
            # Rows whose old Garmin copy survived: still on the watch at the
            # pre-recalibration pace, so the runner must know to re-push.
            f"&n_garmin_stale={result.get('n_garmin_stale', 0)}"
        ),
        status_code=303,
    )


# ── Auto-VDOT suggestion: Apply / Dismiss ──────────────────────────
# Triggered from the dashboard banner when the detector finds a recent
# race-pace effort that implies a meaningful VDOT bump. Apply re-runs
# `update_plan_vdot` + `recalibrate_paces` in the same txn so the
# runner gets the calibration AND pace rewrites in one click.

@app.post("/plan/vdot/apply/{activity_id}")
def vdot_suggestion_apply(activity_id: int):
    """Apply the implied VDOT to the active plan, recalibrate paces,
    mark the activity as applied so we don't re-suggest off it."""
    today_iso = _date.today().isoformat()
    from running_coach.plans import vdot_detection as _vdot_det
    # Re-derive the suggestion server-side instead of trusting the
    # banner's payload — avoids races (key already dismissed, plan
    # changed, etc.) and tamper risk.
    with closing(connect()) as conn:
        suggestion = _vdot_det.detect_vdot_suggestion(conn)
        if not suggestion or suggestion["activity_id"] != activity_id:
            return RedirectResponse(url="/?vdot=stale", status_code=303)
        try:
            client = get_client(prompt_mfa=_refuse_mfa)
        except Exception:  # noqa: BLE001 — pace updates still happen, just no Garmin push
            client = None
        try:
            plan_service.update_plan_vdot(
                conn, suggestion["plan_id"], suggestion["implied_vdot"],
            )
            result = plan_service.recalibrate_paces(
                conn, client, suggestion["plan_id"], today_iso,
            )
            _vdot_det.mark_applied(conn, activity_id)
            llm_commentary.invalidate_today(conn)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(
        url=(
            f"/?vdot=applied"
            f"&new_vdot={suggestion['implied_vdot']}"
            f"&n_updated={result['n_updated']}"
        ),
        status_code=303,
    )


@app.post("/plan/vdot/dismiss/{activity_id}")
def vdot_suggestion_dismiss(activity_id: int):
    """Dismiss the suggestion for this activity. We won't re-suggest
    off the same run on future renders."""
    from running_coach.plans import vdot_detection as _vdot_det
    with closing(connect()) as conn:
        _vdot_det.mark_dismissed(conn, activity_id)
    return RedirectResponse(url="/?vdot=dismissed", status_code=303)


@app.post("/plans/{plan_id}/deactivate")
def plans_deactivate(plan_id: int):
    with closing(connect()) as conn:
        result = _try_cleanup_garmin_workouts(conn, plan_id)
        plan_service.deactivate_plan(conn, plan_id)
    if result["failed"]:
        # Those workouts kept their Garmin id, so this is retryable.
        return RedirectResponse(
            url=f"/plans?error=garmin_cleanup&failed={result['failed']}",
            status_code=303,
        )
    return RedirectResponse(url="/plans", status_code=303)


@app.post("/plans/{plan_id}/reactivate")
def plans_reactivate(plan_id: int):
    """Re-activate an archived plan, swapping out any current active plan.

    Best-effort Garmin cleanup of the outgoing active plan first, matching the
    deactivate flow — the swapped-out plan's watch workouts are cleared; the
    re-activated plan can be re-pushed per week.
    """
    with closing(connect()) as conn:
        current = plan_service.get_active_plan(conn)
        if current and current["id"] != plan_id:
            _try_cleanup_garmin_workouts(conn, current["id"])
        plan_service.reactivate_plan(conn, plan_id)
    return RedirectResponse(url="/plans", status_code=303)


@app.post("/plans/{plan_id}/delete")
def plans_delete(plan_id: int):
    """Hard-delete an inactive plan. Best-effort Garmin cleanup first."""
    with closing(connect()) as conn:
        # In case any workouts still have garmin_workout_id (e.g. deactivate
        # cleanup partially failed), try once more before the row vanishes.
        result = _try_cleanup_garmin_workouts(conn, plan_id)
        try:
            plan_service.delete_plan(conn, plan_id)
        except ValueError:
            # Swallow — UI will simply refresh and the user can see the plan is still there.
            pass
    if result["failed"]:
        # Distinct from the deactivate case: the plan rows are gone, so the
        # ids went with them. These workouts are orphaned on Garmin and have
        # to be removed by hand in Connect.
        return RedirectResponse(
            url=f"/plans?error=garmin_orphaned&failed={result['failed']}",
            status_code=303,
        )
    return RedirectResponse(url="/plans", status_code=303)


@app.post("/plans/{plan_id}/weeks/{week_number}/push", response_class=HTMLResponse)
def push_week(request: Request, plan_id: int, week_number: int):
    """Push every pushable, not-yet-pushed workout in one week of one plan."""
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
        with closing(connect()) as conn:
            result = plan_service.push_week_to_garmin(conn, client, plan_id, week_number)
            week = plan_service.get_plan_week(conn, plan_id, week_number)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(
            content=f'<div class="card error" id="week-{week_number}">Week push failed: {type(exc).__name__}: {exc}</div>',
            status_code=200,
        )
    return templates.TemplateResponse(
        request=request,
        name="_week_card.html",
        context={
            "week": week,
            "today_iso": _date.today().isoformat(),
            "push_result": result,
            "plan_id": plan_id,
            "plan_status": "active",
        },
    )


@app.get("/plan-strength/{session_id}", response_class=HTMLResponse)
def plan_strength_modal(request: Request, session_id: int):
    """Modal content for one optional strength session. Triggered by
    clicking the strength chip on a rest-day cell. Tempo-only — the
    strength sessions are surfaced via the modal."""
    with closing(connect()) as conn:
        from running_coach.strength import service as _strength_service
        s = _strength_service.get_session(conn, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="strength session not found")
    return templates.TemplateResponse(
        request=request,
        name="_plan_strength_modal.html",
        context={"s": s},
    )


@app.post("/plan-strength/{session_id}/complete", response_class=HTMLResponse)
def plan_strength_complete(request: Request, session_id: int):
    """Mark a strength session done. Re-renders the modal body so the
    HTMX outerHTML swap updates the pill + button state in place."""
    with closing(connect()) as conn:
        from running_coach.strength import service as _strength_service
        _strength_service.mark_complete(conn, session_id)
        s = _strength_service.get_session(conn, session_id)
        # Today's coach banner may now want to acknowledge the session.
        llm_commentary.invalidate_today(conn)
    if not s:
        raise HTTPException(status_code=404, detail="strength session not found")
    return templates.TemplateResponse(
        request=request,
        name="_plan_strength_modal.html",
        context={"s": s},
    )


@app.get("/strength/explain", response_class=HTMLResponse)
def strength_exercise_explain(request: Request, name: str, id: str | None = None):
    """LLM-generated 'Explain more' breakdown for one exercise. Cached
    in `llm_cache` under `strength_explain:<id-or-name>` so repeat
    clicks across all sessions are free.

    The `id` param (the FIT exercise enum like ``body_weight_wall_squat``)
    is the stable cache key — using it keeps the cache valid even if we
    change a friendly display name. ``name`` is the runner-facing label
    the LLM uses inside the prompt; ``id`` falls back to ``name`` when
    the caller didn't supply it (older callers).
    """
    key_part = (id or name).lower()
    cache_key = f"strength_explain:{key_part}"
    with closing(connect()) as conn:
        cached = conn.execute(
            "SELECT content FROM llm_cache WHERE cache_key = ?", (cache_key,)
        ).fetchone()
        body: str | None = cached["content"] if cached else None
        if body is None:
            # Build a short, runner-coaching prompt. Asks for 3 bullets:
            # setup / cue / common mistake. Kept tight so the modal stays
            # scannable.
            from running_coach.llm import connector as _llm_connector, prompts as _llm_prompts
            locale = app_settings.get_language(conn)
            system = _llm_prompts.system_prompt_for(
                "You're a running-coach assistant explaining bodyweight exercises "
                "to a competitive amateur runner. Output exactly three short "
                "bullet points, no preamble, no markdown headers:\n"
                "  • Setup — starting position in one sentence.\n"
                "  • Cue — the one form cue that matters most.\n"
                "  • Mistake — the most common error to avoid.\n"
                "Bullets only, plain text. ~12-18 words per bullet.",
                locale,
            )
            result = _llm_connector.coach_message(
                system_prompt=system,
                profile_block="(no profile needed; explain the named exercise only)",
                request_block=f"Exercise to explain: {name}",
                max_tokens=400,
                effort="low",
            )
            if result is None:
                return HTMLResponse(
                    '<span class="muted" style="font-size: 0.78rem;">'
                    'Couldn\'t generate explanation right now. Try again later.</span>'
                )
            body = result.text
            try:
                conn.execute(
                    """INSERT OR REPLACE INTO llm_cache (cache_key, content, model, created_at, usage_json)
                       VALUES (?, ?, ?, datetime('now'), ?)""",
                    (cache_key, body, result.model,
                     json.dumps(result.usage) if result.usage else None),
                )
                conn.commit()
            except Exception:  # noqa: BLE001 — caching is best-effort
                pass
    # Render bullets into a small block. The LLM was told to emit
    # bullet-prefixed lines; we just re-style them client-side.
    return HTMLResponse(
        f'<div class="tp-strength-ex-explained">'
        f'<pre>{body}</pre>'
        f'</div>'
    )


@app.post("/plan-strength/{session_id}/push", response_class=HTMLResponse)
def plan_strength_push(request: Request, session_id: int):
    """Upload this strength session to Garmin Connect + schedule it on
    the planned date. The modal re-renders with the pushed pill + an
    Unpush button. Errors come back as a small inline message inside
    the modal body so the dialog doesn't blow up."""
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
    except Exception as exc:  # noqa: BLE001 — Garmin auth missing
        return _render_strength_modal_with_flash(
            request, session_id,
            flash=f"Garmin not connected: {exc}",
        )
    with closing(connect()) as conn:
        from running_coach.strength import garmin_push as _strength_push
        try:
            push_result = _strength_push.push_session(conn, client, session_id)
        except Exception as exc:  # noqa: BLE001
            return _render_strength_modal_with_flash(
                request, session_id,
                flash=f"Push failed: {exc}",
            )
        s = _strength_service_for_modal(conn, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="strength session not found")
    # Upload and scheduling are separate gates. An uploaded-but-unscheduled
    # session is in Garmin Connect's workout list but not on the calendar, so
    # it will never reach the watch for that date — say so rather than
    # reporting a success the runner cannot act on.
    if push_result.get("scheduled", True):
        flash = _t("Pushed to your watch.")
    else:
        flash = _t(
            "Uploaded to Garmin, but scheduling it on {date} failed — it won't "
            "reach your watch for that day. Try pushing again.",
            date=s["planned_date"],
        )
    return templates.TemplateResponse(
        request=request,
        name="_plan_strength_modal.html",
        context={"s": s, "flash": flash},
    )


def unpush_outcome(removed: bool, error: str | None, still_pushed: bool) -> tuple[str, dict]:
    """Decide what to tell the runner after an unpush attempt.

    Pure so it can be tested without a request. Returns (message_key, params)
    for `_t()`. The route used to hard-code "Removed from your watch." for all
    four of these cases, including the two where the session is still on the
    watch.
    """
    if removed:
        return "Removed from your watch.", {}
    if error:
        return "Couldn't remove it from Garmin: {error}", {"error": error}
    if still_pushed:
        return (
            "Couldn't remove it from Garmin — it's still on your watch. Try again.",
            {},
        )
    return "That session wasn't on your watch.", {}


@app.post("/plan-strength/{session_id}/unpush", response_class=HTMLResponse)
def plan_strength_unpush(request: Request, session_id: int):
    """Remove this strength session from Garmin and clear our push state.

    Clearing local state is **not** a fallback for failing to reach Garmin.
    The session would stay on the watch with nothing left pointing at it, and
    the next push would add a second copy. `unpush_session` only clears state
    on a confirmed delete; this route honours that answer instead of
    overriding it.
    """
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
    except Exception:  # noqa: BLE001 — not connected; nothing can be removed
        client = None
    with closing(connect()) as conn:
        from running_coach.strength import garmin_push as _strength_push, service as _strength_service
        removed = False
        error: str | None = None
        if client is None:
            error = _t("Garmin isn't connected, so nothing was removed from your watch.")
        else:
            try:
                removed = _strength_push.unpush_session(conn, client, session_id)
            except Exception as exc:  # noqa: BLE001 — report, never clear blindly
                error = str(exc)
        s = _strength_service.get_session(conn, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="strength session not found")
    key, params = unpush_outcome(removed, error, bool(s.get("garmin_workout_id")))
    flash = _t(key, **params)
    return templates.TemplateResponse(
        request=request,
        name="_plan_strength_modal.html",
        context={"s": s, "flash": flash},
    )


def _strength_service_for_modal(conn, session_id: int) -> dict | None:
    """Refresh the modal context after a push/unpush — pulls the hydrated
    session including the newly-stamped garmin_workout_id / pushed_at."""
    from running_coach.strength import service as _strength_service
    return _strength_service.get_session(conn, session_id)


def _render_strength_modal_with_flash(request, session_id: int, flash: str):
    """HX helper: re-render the modal body with an error/info flash on top."""
    with closing(connect()) as conn:
        from running_coach.strength import service as _strength_service
        s = _strength_service.get_session(conn, session_id)
    if not s:
        return HTMLResponse(
            f'<div class="error" style="padding: 1rem;">{flash}</div>',
            status_code=400,
        )
    return templates.TemplateResponse(
        request=request,
        name="_plan_strength_modal.html",
        context={"s": s, "flash": flash},
    )


@app.post("/plan-strength/{session_id}/undo", response_class=HTMLResponse)
def plan_strength_undo(request: Request, session_id: int):
    """Flip a completed strength session back to pending — useful when
    the runner taps Complete by accident or wants to redo the session."""
    with closing(connect()) as conn:
        from running_coach.strength import service as _strength_service
        _strength_service.mark_incomplete(conn, session_id)
        s = _strength_service.get_session(conn, session_id)
        llm_commentary.invalidate_today(conn)
    if not s:
        raise HTTPException(status_code=404, detail="strength session not found")
    return templates.TemplateResponse(
        request=request,
        name="_plan_strength_modal.html",
        context={"s": s},
    )


@app.get("/plan-workouts/{pw_id}", response_class=HTMLResponse)
def plan_workout_modal(request: Request, pw_id: int):
    """Modal content for one planned workout. Triggered by clicking a day cell
    on the Tempo plans page; lazy-loaded via HTMX into the dialog. Returns
    the Tempo partial (no Base equivalent — Base day cards already inline
    everything this surfaces)."""
    today_iso = _date.today().isoformat()
    with closing(connect()) as conn:
        row = conn.execute(
            """SELECT pw.*,
                      a.distance_m       AS actual_distance_m,
                      a.duration_s       AS actual_duration_s,
                      a.avg_hr           AS actual_avg_hr,
                      a.training_load    AS actual_training_load,
                      a.activity_name    AS actual_name,
                      a.start_time_local AS actual_start_local,
                      p.title            AS plan_title,
                      p.status           AS plan_status,
                      p.id               AS plan_id_join
               FROM plan_workouts pw
               LEFT JOIN activities a ON a.activity_id = pw.actual_activity_id
               JOIN plans p ON p.id = pw.plan_id
               WHERE pw.id = ?""",
            (pw_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="plan workout not found")
        workout = dict(row)
        # Execution score — same computation as the plans-page week cells.
        # Fetched fresh here because the modal route doesn't go through
        # get_plan_workouts(). HR-zone columns + activity_id come via the
        # JOIN above; pull them into the activity dict the scorer expects.
        if workout.get("actual_activity_id"):
            hr_row = conn.execute(
                "SELECT hr_zone_1_s, hr_zone_2_s, hr_zone_3_s, hr_zone_4_s, hr_zone_5_s "
                "FROM activities WHERE activity_id = ?",
                (workout["actual_activity_id"],),
            ).fetchone()
            activity = {
                "activity_id": workout["actual_activity_id"],
                "distance_m":  workout["actual_distance_m"],
                "duration_s":  workout["actual_duration_s"],
                "avg_hr":      workout["actual_avg_hr"],
                **(dict(hr_row) if hr_row else {}),
            }
            from running_coach import execution_score as _es
            workout["execution_score"] = _es.compute(conn, workout, activity)
        else:
            workout["execution_score"] = None
        # Parse the structure JSON once so the template can seed per-step inputs.
        structure_raw = workout.get("workout_structure")
        if isinstance(structure_raw, str):
            try:
                workout["structure_parsed"] = json.loads(structure_raw)
            except Exception:  # noqa: BLE001
                workout["structure_parsed"] = None
        else:
            workout["structure_parsed"] = structure_raw
        # Coach-suggested swap only fires for today's workout when the rules
        # engine returned caution/easy and nothing's been logged yet.
        swap_available = False
        if (
            workout["planned_date"] == today_iso
            and not workout.get("actual_activity_id")
        ):
            recommendation = plan_coach.daily_recommendation(conn)
            swap_available = bool(
                recommendation
                and recommendation["status"] in ("caution", "easy")
            )
        else:
            recommendation = None
        # Calendar-event swap on this row (race placed here, or the session
        # freed up for it) — drives the "Race event" section in the modal.
        event_swap = event_swap_service.get_swap_for_workout(conn, pw_id)
    return templates.TemplateResponse(
        request=request,
        name="_plan_workout_modal.html",
        context={
            "w": workout,
            "today_iso": today_iso,
            "swap_available": swap_available,
            "recommendation": recommendation,
            "event_swap": event_swap,
        },
    )


@app.post("/plan-workouts/{pw_id}/apply-swap")
def apply_workout_swap(pw_id: int):
    """Apply the coach's suggested workout swap. Updates DB; re-pushes to Garmin if needed."""
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
        with closing(connect()) as conn:
            plan_service.apply_workout_swap(conn, client, pw_id)
            # Today's workout changed shape; drop the cached coach line.
            llm_commentary.invalidate_today(conn)
    except Exception:  # noqa: BLE001
        # Soft fail — still redirect so the user sees the latest state
        pass
    return RedirectResponse(url="/", status_code=303)


def _parse_optional_float(value: str | None) -> float | None:
    """Form-field helper: '' / None → None; otherwise float()."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return float(value)


def _parse_pace_input(value: str | None) -> int | None:
    """Accept either 'mm:ss' or a bare integer (seconds). Empty → None."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if ":" in value:
        m, s = value.split(":", 1)
        return int(m) * 60 + int(s)
    return int(value)


def _parse_duration_input(value: str | None) -> int | None:
    """Accept either 'h:mm:ss', 'mm:ss', or a bare integer (seconds)."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parts = value.split(":")
    if len(parts) == 1:
        return int(parts[0])
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    if len(parts) == 3:
        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    raise ValueError(f"unrecognised duration format: {value!r}")


def _parse_optional_int(value: str | None) -> int | None:
    """Form-field helper for plain integers (iterations, counts)."""
    if value is None:
        return None
    value = value.strip()
    return int(value) if value else None


@app.post("/plan-workouts/{pw_id}/edit")
def edit_plan_workout(
    pw_id: int,
    workout_type: str = Form(...),
    # Simple-type fields
    target_distance_km: str = Form(""),
    target_pace_s_per_km: str = Form(""),
    # Tempo per-step fields
    tempo_warmup_km: str = Form(""),
    tempo_active_km: str = Form(""),
    tempo_active_pace: str = Form(""),
    tempo_cooldown_km: str = Form(""),
    # Intervals per-step fields
    intervals_warmup_km: str = Form(""),
    intervals_iterations: str = Form(""),
    intervals_work_km: str = Form(""),
    intervals_work_pace: str = Form(""),
    intervals_recovery: str = Form(""),
    intervals_cooldown_km: str = Form(""),
    # Progression fields — parallel arrays, one entry per pace segment of a
    # multi-pace continuous run (e.g. peak marathon long run: E block + M finish).
    seg_km: list[str] = Form([]),
    seg_pace: list[str] = Form([]),
    seg_zone: list[str] = Form([]),
    # Time-based fields (paceless run/walk sessions — Couch to 5K, Foppen)
    intervals_warmup_time: str = Form(""),
    intervals_work_time: str = Form(""),
    intervals_cooldown_time: str = Form(""),
    simple_warmup_time: str = Form(""),
    simple_run_time: str = Form(""),
    simple_cooldown_time: str = Form(""),
):
    """Manual edit from the planned-workout modal. Handles both simple and
    structured (tempo/intervals) workouts; the per-step fields rebuild the
    `workout_structure` JSON server-side. Re-pushes to Garmin best-effort when
    the workout was previously on the watch."""
    try:
        try:
            client = get_client(prompt_mfa=_refuse_mfa)
        except Exception:  # noqa: BLE001
            client = None
        with closing(connect()) as conn:
            plan_service.edit_workout(
                conn,
                client,
                pw_id,
                workout_type=workout_type,
                target_distance_km=_parse_optional_float(target_distance_km),
                target_pace_s_per_km=_parse_pace_input(target_pace_s_per_km),
                tempo_warmup_km=_parse_optional_float(tempo_warmup_km),
                tempo_active_km=_parse_optional_float(tempo_active_km),
                tempo_active_pace_s=_parse_pace_input(tempo_active_pace),
                tempo_cooldown_km=_parse_optional_float(tempo_cooldown_km),
                intervals_warmup_km=_parse_optional_float(intervals_warmup_km),
                intervals_iterations=_parse_optional_int(intervals_iterations),
                intervals_work_km=_parse_optional_float(intervals_work_km),
                intervals_work_pace_s=_parse_pace_input(intervals_work_pace),
                intervals_recovery_s=_parse_duration_input(intervals_recovery),
                intervals_cooldown_km=_parse_optional_float(intervals_cooldown_km),
                segments=(
                    [
                        {
                            "km": _parse_optional_float(k),
                            "pace_s_per_km": _parse_pace_input(p),
                            "zone": (z or None),
                        }
                        for k, p, z in zip(seg_km, seg_pace, seg_zone)
                    ]
                    if seg_km
                    else None
                ),
                intervals_warmup_s=_parse_duration_input(intervals_warmup_time),
                intervals_work_s=_parse_duration_input(intervals_work_time),
                intervals_cooldown_s=_parse_duration_input(intervals_cooldown_time),
                simple_warmup_s=_parse_duration_input(simple_warmup_time),
                simple_run_s=_parse_duration_input(simple_run_time),
                simple_cooldown_s=_parse_duration_input(simple_cooldown_time),
            )
            # If this was today's workout, the coach line is now stale.
            llm_commentary.invalidate_today(conn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(url="/plans", status_code=303)


@app.post("/plan-workouts/{pw_id}/move")
def move_plan_workout(pw_id: int, new_date: str = Form(...)):
    """Reschedule a planned workout. Swaps with the existing workout on
    `new_date` if there is one. Re-pushes to Garmin best-effort."""
    try:
        try:
            client = get_client(prompt_mfa=_refuse_mfa)
        except Exception:  # noqa: BLE001
            client = None
        with closing(connect()) as conn:
            plan_service.move_workout(conn, client, pw_id, new_date)
            llm_commentary.invalidate_today(conn)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return RedirectResponse(url="/plans", status_code=303)


@app.post("/plan-workouts/{pw_id}/push", response_class=HTMLResponse)
def push_plan_workout(request: Request, pw_id: int):
    """Upload one planned workout to Garmin Connect and schedule it on the planned date."""
    try:
        client = get_client(prompt_mfa=_refuse_mfa)
        with closing(connect()) as conn:
            pw = plan_service.push_workout_to_garmin(conn, client, pw_id)
    except Exception as exc:  # noqa: BLE001
        return HTMLResponse(
            content=(
                f'<div class="day wtype-rest" id="day-{pw_id}" '
                f'style="border-left-color: #ef4444;">'
                f'<div class="dow" style="color:#ef4444;">Push failed</div>'
                f'<div class="wdesc">{type(exc).__name__}: {exc}</div>'
                f'</div>'
            ),
            status_code=200,
        )
    return templates.TemplateResponse(
        request=request,
        name="_day_card.html",
        context={"w": pw, "today_iso": _date.today().isoformat()},
    )


@app.get("/plans/{plan_id}", response_class=HTMLResponse)
def plan_detail(request: Request, plan_id: int):
    today_iso = _date.today().isoformat()
    with closing(connect()) as conn:
        plan = plan_service.get_plan(conn, plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="plan not found")
        weeks = plan_service.get_plan_weeks(conn, plan_id)
        adherence = plan_service.plan_adherence(conn, plan_id, today_iso)
    methodology_lookup = {m.id: m for m in list_methodologies()}
    template_name = "plan_detail.html"
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context={
            "plan": plan,
            "weeks": weeks,
            "methodology_lookup": methodology_lookup,
            "days_to_race": _days_to_race(plan),
            "adherence": adherence,
            "nav_active": "plans",
            "today_iso": today_iso,
        },
    )


@app.post("/plans/{plan_id}/match")
def plan_rematch(plan_id: int):
    """Manually re-run adherence matching for one plan."""
    with closing(connect()) as conn:
        plan_matcher.match_plan_workouts(conn, plan_id=plan_id)
    return RedirectResponse(url="/plans", status_code=303)
