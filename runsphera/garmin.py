"""Garmin Connect client wrapper.

Two ways to authenticate:

1. **CLI / .env path** — call `get_client()`. It resumes from the cached token
   dir if present, otherwise falls back to GARMIN_EMAIL / GARMIN_PASSWORD env
   vars + a stdin prompt for the email verification code. Used by the CLI
   ingest script.

2. **Web path** — call `start_login(email, password)` then `complete_mfa(code)`.
   Non-blocking (`return_on_mfa=True`), so the FastAPI route can hand control
   back to the user between the credentials submission and the MFA code entry.

Both paths end with the session cached in `.garmin_tokens/`. **The password is
never persisted** — only the resulting session token.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from garminconnect import Garmin


# ---- Token-dir resolution ------------------------------------------------

def _default_token_dir() -> Path:
    load_dotenv()
    return Path(os.getenv("GARMIN_TOKEN_DIR", ".garmin_tokens")).expanduser().resolve()


# ---- CLI / .env login (unchanged interface) ------------------------------

def _prompt_mfa_stdin() -> str:
    return input("Garmin MFA code: ").strip()


def _refuse_mfa() -> str:
    raise RuntimeError(
        "Garmin needs an MFA code but no interactive prompt is available. "
        "Run `python -m runsphera.ingest` from a terminal once to refresh the cached token."
    )


def get_client(
    token_dir: Path | None = None,
    prompt_mfa: Callable[[], str] | None = None,
) -> Garmin:
    """Return an authenticated Garmin client.

    Tries cached tokens first; falls back to GARMIN_EMAIL/PASSWORD env vars.
    Used by the CLI ingest and the web push routes (which pass `_refuse_mfa`
    so the call fails cleanly instead of blocking on stdin).
    """
    load_dotenv()
    if token_dir is None:
        token_dir = _default_token_dir()
    token_dir.mkdir(parents=True, exist_ok=True)

    client = Garmin(
        email=os.getenv("GARMIN_EMAIL"),
        password=os.getenv("GARMIN_PASSWORD"),
        prompt_mfa=prompt_mfa or _prompt_mfa_stdin,
    )
    client.login(str(token_dir))
    return client


# ---- Auth status probe ---------------------------------------------------

def is_authenticated(token_dir: Path | None = None) -> bool:
    """Cheap check: does the token cache directory have files in it?

    Doesn't probe Garmin — if the tokens are expired/invalid, the actual
    sync attempt will fail and the route can redirect to /auth then.
    """
    if token_dir is None:
        token_dir = _default_token_dir()
    try:
        return token_dir.exists() and any(token_dir.iterdir())
    except Exception:  # noqa: BLE001
        return False


def clear_auth(token_dir: Path | None = None) -> None:
    """Remove the cached session — used by the 'Disconnect' button."""
    if token_dir is None:
        token_dir = _default_token_dir()
    if token_dir.exists():
        for p in token_dir.iterdir():
            try:
                p.unlink()
            except Exception:  # noqa: BLE001
                pass


# ---- Web auth flow (return_on_mfa, non-blocking) -------------------------

# Module-level pending-auth slot. Single-user local app: one slot is enough.
# Holds: {"client": Garmin, "client_state": dict, "email": str, "token_dir": Path}
_pending_auth: dict[str, Any] | None = None


def _persist_session(client: Garmin, token_dir: Path) -> None:
    """Dump the garth-layer tokens to disk after a return_on_mfa login completes."""
    token_dir.mkdir(parents=True, exist_ok=True)
    try:
        client.client.dump(str(token_dir))
    except Exception:  # noqa: BLE001 — garth may auto-persist; best-effort
        pass


def start_login(
    email: str,
    password: str,
    token_dir: Path | None = None,
) -> dict[str, Any]:
    """Begin the web auth flow.

    Returns one of:
      {"status": "complete"}            — auth done, token cached
      {"status": "mfa_required"}        — call complete_mfa(code) next
      {"status": "failed", "error": ..} — network/credential error
    """
    global _pending_auth
    if token_dir is None:
        token_dir = _default_token_dir()

    client = Garmin(email=email, password=password, return_on_mfa=True)
    try:
        mfa_status, _legacy = client.login(str(token_dir))
    except Exception as exc:  # noqa: BLE001
        _pending_auth = None
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}

    if mfa_status:
        # Garmin demanded a one-time code (email verification or true MFA).
        _pending_auth = {
            "client": client,
            "client_state": mfa_status,
            "email": email,
            "token_dir": token_dir,
        }
        return {"status": "mfa_required"}

    # No MFA — token cache already in place from the garth layer; force-persist for safety.
    _persist_session(client, token_dir)
    _pending_auth = None
    return {"status": "complete", "full_name": getattr(client, "full_name", "") or None}


def complete_mfa(code: str) -> dict[str, Any]:
    """Finish a pending MFA challenge with the user's entered code."""
    global _pending_auth
    if not _pending_auth:
        return {"status": "failed", "error": "no login in progress — start over"}

    client = _pending_auth["client"]
    client_state = _pending_auth["client_state"]
    token_dir = _pending_auth["token_dir"]
    email = _pending_auth["email"]

    try:
        client.resume_login(client_state, code.strip())
    except Exception as exc:  # noqa: BLE001
        _pending_auth = None
        return {"status": "failed", "email": email, "error": f"{type(exc).__name__}: {exc}"}

    _persist_session(client, token_dir)
    _pending_auth = None
    return {
        "status": "complete",
        "email": email,
        "full_name": getattr(client, "full_name", "") or None,
    }


def fetch_profile(client: Garmin) -> dict:
    """Best-effort read of the user's body profile from Garmin, for the
    optional Fuel pre-fill. Normalises to `{weight_kg, height_cm,
    birth_year, sex}` and returns only the fields actually present —
    Garmin's payloads vary by account, so every field is tolerated as
    missing. Never raises on a parse miss; an empty dict means "nothing
    usable found".
    """
    out: dict[str, Any] = {}

    # `get_userprofile_settings()` carries the static body data in a
    # `userData` block (weight in grams, height in cm, ISO birthDate,
    # gender MALE/FEMALE).
    try:
        settings = client.get_userprofile_settings() or {}
        ud = settings.get("userData") or {}
        weight_g = ud.get("weight")
        if weight_g:
            out["weight_kg"] = round(float(weight_g) / 1000.0, 1)
        height_cm = ud.get("height")
        if height_cm:
            out["height_cm"] = round(float(height_cm), 1)
        gender = (ud.get("gender") or "").strip().lower()
        if gender in ("male", "female"):
            out["sex"] = gender
        birth = ud.get("birthDate") or ud.get("birthdate")
        if birth and len(str(birth)) >= 4:
            try:
                out["birth_year"] = int(str(birth)[:4])
            except ValueError:
                pass
    except Exception:  # noqa: BLE001 — pre-fill is optional, never fatal
        pass

    # Latest weigh-in overrides the (often stale) profile weight.
    try:
        from datetime import date, timedelta

        end = date.today()
        start = end - timedelta(days=60)
        comp = client.get_body_composition(start.isoformat(), end.isoformat()) or {}
        # Shape: {"totalAverage": {"weight": <grams>, ...}, ...}
        avg = comp.get("totalAverage") or {}
        latest_weight_g = avg.get("weight")
        if latest_weight_g:
            out["weight_kg"] = round(float(latest_weight_g) / 1000.0, 1)
    except Exception:  # noqa: BLE001
        pass

    return out


def pending_email() -> str | None:
    """Email of the in-progress login, if any — for pre-filling the MFA form."""
    return _pending_auth["email"] if _pending_auth else None


def cancel_pending_login() -> None:
    global _pending_auth
    _pending_auth = None
