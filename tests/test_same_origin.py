"""Regression tests for cross-origin protection on state-changing routes.

The app has no accounts, so loopback binding was the only thing between a
malicious page and a hard-delete of a non-regenerable plan — and loopback
does not stop a cross-origin form POST. See runsphera/web/security.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from runsphera.web.security import (  # noqa: E402
    SameOriginMiddleware,
    bare_host,
)

APP_HOST = "localhost:8000"


# SameOriginMiddleware.__init__ needs an ASGI app; these tests only exercise
# the pure `refusal()` decision, so build a bare instance instead.
def _middleware(hosts=None) -> SameOriginMiddleware:
    mw = SameOriginMiddleware.__new__(SameOriginMiddleware)
    mw._hosts = hosts
    return mw


# ── bare_host parsing ────────────────────────────────────────────────────

def test_bare_host_strips_scheme_and_port():
    assert bare_host("http://localhost:8000") == "localhost"
    assert bare_host("localhost:8000") == "localhost"
    assert bare_host("HTTP://LocalHost:8000") == "localhost"


def test_bare_host_handles_ipv6():
    assert bare_host("[::1]:8000") == "::1"
    assert bare_host("::1") == "::1"
    assert bare_host("http://[::1]:8000") == "::1"


def test_bare_host_empty_is_empty():
    assert bare_host("") == ""
    assert bare_host(None) == ""


# ── the attack this exists to stop ───────────────────────────────────────

def test_cross_origin_post_to_plan_delete_is_refused():
    """A form on evil.com auto-posting to localhost must not delete a plan."""
    mw = _middleware()
    reason = mw.refusal("POST", APP_HOST, "http://evil.com", None)
    assert reason is not None
    assert "cross-origin" in reason.lower()


def test_cross_origin_via_referer_is_refused():
    """Origin absent but Referer foreign — still cross-origin."""
    mw = _middleware()
    reason = mw.refusal("POST", APP_HOST, None, "http://evil.com/page")
    assert reason is not None


def test_dns_rebinding_is_refused():
    """Origin == Host == evil.com passes a naive equality check.

    An attacker domain resolving to 127.0.0.1 produces exactly that, which
    is why the Host allow-list is a separate check.
    """
    mw = _middleware()
    reason = mw.refusal("POST", "evil.com", "http://evil.com", None)
    assert reason is not None
    assert "host" in reason.lower()


def test_dns_rebinding_refused_on_get_too():
    """Rebinding reads data with GET; the Host check is not method-gated."""
    mw = _middleware()
    assert mw.refusal("GET", "evil.com", None, None) is not None


# ── legitimate traffic must still work ───────────────────────────────────

def test_same_origin_post_is_allowed():
    mw = _middleware()
    assert mw.refusal("POST", APP_HOST, f"http://{APP_HOST}", None) is None


def test_loopback_variants_allowed():
    mw = _middleware()
    for host in ("localhost:8000", "127.0.0.1:8000", "[::1]:8000"):
        assert mw.refusal("POST", host, f"http://{host}", None) is None, host


def test_plain_get_is_allowed():
    mw = _middleware()
    assert mw.refusal("GET", APP_HOST, None, None) is None


def test_non_browser_client_is_allowed():
    """curl and the ingest scripts send neither header; CSRF needs a browser."""
    mw = _middleware()
    assert mw.refusal("POST", APP_HOST, None, None) is None


def test_origin_wins_over_referer():
    """A foreign Referer with a matching Origin is same-origin navigation."""
    mw = _middleware()
    reason = mw.refusal("POST", APP_HOST, f"http://{APP_HOST}", "http://evil.com/x")
    assert reason is None


def test_extra_host_can_be_allowed_explicitly():
    """Self-hosting beyond loopback is opt-in, not blocked outright."""
    mw = _middleware(hosts=frozenset({"localhost", "runsphera.lan"}))
    assert mw.refusal("POST", "runsphera.lan", "http://runsphera.lan", None) is None
    assert mw.refusal("POST", "evil.com", "http://evil.com", None) is not None


def test_env_var_extends_allow_list():
    from runsphera.web import security

    os.environ["RUNNING_COACH_ALLOWED_HOSTS"] = "pi.local, nas.lan"
    try:
        hosts = security.allowed_hosts()
        assert "pi.local" in hosts
        assert "nas.lan" in hosts
        assert "localhost" in hosts  # defaults survive
    finally:
        del os.environ["RUNNING_COACH_ALLOWED_HOSTS"]


def main():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"  ok  {fn.__name__}")
    print(f"{len(fns)} passed")


if __name__ == "__main__":
    main()
