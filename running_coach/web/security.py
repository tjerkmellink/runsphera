"""Same-origin enforcement for the local web app.

The app has no accounts and no sessions, so there is no credential to bind a
request to. Binding to loopback is *not* a defence on its own: any page the
runner visits while RunSphera is running can submit a form to a predictable
localhost URL, and the browser will deliver it. That is enough to hard-delete
a training plan — and plans, diary entries and body history are not
regenerable (see architecture decision #2).

Two checks, and both are needed:

* **Host allow-list** — blocks DNS rebinding, where an attacker's domain
  resolves to 127.0.0.1 so that `Origin` *and* `Host` both read `evil.com`
  and a naive "Origin equals Host" comparison passes happily.
* **Origin match** — blocks classic CSRF. A browser always sends `Origin` on
  a cross-origin POST and page JavaScript cannot suppress or forge it.

A request carrying neither `Origin` nor `Referer` is allowed through: CSRF
needs a browser's ambient authority, and browsers always send one of the two
on a state-changing request. This keeps curl, the ingest scripts and the
Starlette test client working.

Serving the app somewhere other than loopback (a home server reached from a
phone, say) means naming that host in `RUNNING_COACH_ALLOWED_HOSTS` as a
comma-separated list. Secure by default; opt in deliberately.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

# Methods that do not change state. HEAD/OPTIONS are included so HTMX and
# browsers can probe freely; the Host check still applies to them.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})

# "testserver" is the host Starlette's TestClient sends.
DEFAULT_ALLOWED_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "0.0.0.0", "testserver"}  # noqa: S104
)

_ENV_ALLOWED_HOSTS = "RUNNING_COACH_ALLOWED_HOSTS"


def bare_host(value: str) -> str:
    """Reduce a Host header or an Origin URL to a bare lowercase hostname.

    Handles every shape these headers arrive in::

        "http://localhost:8000"  -> "localhost"
        "localhost:8000"         -> "localhost"
        "[::1]:8000"             -> "::1"
        "::1"                    -> "::1"
    """
    v = (value or "").strip()
    if not v:
        return ""
    if "://" in v:
        v = urlsplit(v).netloc
    if v.startswith("["):  # bracketed IPv6 literal, optionally with a port
        end = v.find("]")
        if end != -1:
            return v[1:end].lower()
    if v.count(":") > 1:  # bare IPv6 literal, no port to strip
        return v.lower()
    if ":" in v:
        v = v.rsplit(":", 1)[0]
    return v.lower()


def allowed_hosts() -> frozenset[str]:
    """Default loopback hosts, plus anything named in the environment."""
    extra = os.environ.get(_ENV_ALLOWED_HOSTS, "")
    names = {h.strip().lower() for h in extra.split(",") if h.strip()}
    return DEFAULT_ALLOWED_HOSTS | names


class SameOriginMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin state changes and unexpected Host headers.

    Deliberately loud: a refusal returns 403 with a reason rather than
    silently doing nothing, so a misconfigured host shows up immediately
    instead of looking like a dead button.
    """

    def __init__(self, app, hosts: frozenset[str] | None = None) -> None:
        super().__init__(app)
        self._hosts = hosts

    @property
    def hosts(self) -> frozenset[str]:
        # Read through on each request so a test (or a launcher) can set the
        # env var after the app object is built.
        return self._hosts if self._hosts is not None else allowed_hosts()

    def refusal(self, method: str, host_header: str, origin: str | None,
                referer: str | None) -> str | None:
        """Return a refusal reason, or None to allow. Pure — unit-testable."""
        host = bare_host(host_header)
        if host and host not in self.hosts:
            return (
                f"Refused: unexpected Host header {host!r}. If you are serving "
                f"RunSphera on this host deliberately, add it to "
                f"{_ENV_ALLOWED_HOSTS}."
            )
        if method.upper() in SAFE_METHODS:
            return None
        source = origin or referer
        if source is None:
            return None  # not a browser; CSRF does not apply
        if bare_host(source) != host:
            return (
                "Refused: cross-origin request to a state-changing endpoint."
            )
        return None

    async def dispatch(self, request, call_next):
        reason = self.refusal(
            request.method,
            request.headers.get("host", ""),
            request.headers.get("origin"),
            request.headers.get("referer"),
        )
        if reason is not None:
            return PlainTextResponse(reason, status_code=403)
        return await call_next(request)
