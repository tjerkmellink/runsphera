# Same-origin protection

> Stops another website from reaching into your RunSphera instance while it's running.

## Purpose

RunSphera has no accounts and no login. Any request that arrives is honoured — which is
fine, because it only listens on `localhost`.

Listening on loopback is **not** a defence on its own. While the app is running, any page
you happen to visit in the same browser can submit a form to
`http://localhost:8000/plans/3/delete`. The browser will deliver it, and the server has no
way to tell that request apart from one you made yourself. Plan IDs are sequential
integers, so guessing one is trivial.

The payoff of getting this right is blunt: plans, diary entries and body history are **not
regenerable and have no backup** (architecture decision #2). A single cross-origin POST
could destroy a training block you spent five months building.

## How it works (user view)

Invisible when everything is normal. Every page, button and HTMX fragment behaves exactly
as before.

It becomes visible in two situations:

- **Another site tries to change something.** The request is refused with `403` and the
  plain-text reason *"Refused: cross-origin request to a state-changing endpoint."*
- **You reach the app on an unexpected hostname.** The refusal names the host and tells
  you which environment variable to set, rather than silently failing.

Refusals are deliberately loud. A silent no-op would look like a dead button — the failure
mode this codebase has been bitten by most often.

## How it works (implementation)

- **Modules**: [`runsphera/web/security.py`](../runsphera/web/security.py) — the
  whole feature. `bare_host()` normalises a `Host`/`Origin` header to a bare hostname;
  `allowed_hosts()` resolves the allow-list; `SameOriginMiddleware.refusal()` is a pure
  function returning a reason string or `None`.
- **Wiring**: [`runsphera/web/app.py`](../runsphera/web/app.py) —
  `app.add_middleware(SameOriginMiddleware)`, immediately after the `FastAPI()` call so it
  wraps every route.
- **Routes**: all of them. 70 `@app.post` routes are covered without being touched
  individually.
- **DB**: none.
- **External services**: none.

Two independent checks, and both are needed:

| Check | Applies to | Stops |
|---|---|---|
| `Host` is in the allow-list | every request, including `GET` | DNS rebinding |
| `Origin`/`Referer` host matches `Host` | state-changing methods only | classic CSRF |

The Host check cannot be skipped by folding it into the Origin check. In a DNS-rebinding
attack the attacker's domain resolves to `127.0.0.1`, so `Origin` *and* `Host` both read
`evil.com` and a naive "do they match?" comparison passes happily.

A request carrying **neither** `Origin` nor `Referer` is allowed through. CSRF depends on a
browser's ambient authority, and browsers always send one of the two on a state-changing
request. This is what keeps `curl`, the ingest scripts and the Starlette test client
working.

`GET`, `HEAD`, `OPTIONS` and `TRACE` skip the origin check but **not** the Host check —
rebinding reads data with `GET`.

## Configuration

| Setting | Default | Where |
|---|---|---|
| `RUNSPHERA_ALLOWED_HOSTS` | unset | `.env` or the environment |

The pre-rename `RUNNING_COACH_ALLOWED_HOSTS` is still read, and the two are
*merged* rather than one shadowing the other — a host the operator deliberately
allowed stays allowed whichever name they used.

Allowed by default: `localhost`, `127.0.0.1`, `::1`, `0.0.0.0`, and `testserver` (the host
Starlette's test client sends).

Serving RunSphera somewhere other than loopback — a home server you reach from your phone,
say — means naming that host explicitly:

```
RUNSPHERA_ALLOWED_HOSTS=pi.local,192.168.1.40
```

Comma-separated, case-insensitive, and additive: the loopback defaults always remain. The
allow-list is read per request, so changing it needs no code change — only a restart to
pick up a new `.env`.

## Known limitations

- **No per-request token.** This is origin validation, not a CSRF token. It relies on the
  browser sending `Origin` honestly, which browsers do and page JavaScript cannot override.
  A token would need session state the app deliberately does not have.
- **A non-browser client on your machine is unaffected.** Any local process that can run
  `curl` can still reach the API, because it sends no `Origin`. That is accepted: such a
  process could read `data/running_coach.db` directly anyway.
- **An allow-listed host is trusted completely.** Adding `pi.local` means any page served
  from `pi.local` can post to the app. Add hosts you control.
- **No rate limiting or audit log.** Out of scope for a single-user local app.
- **The `.error` CSS class uses hardcoded reds** rather than the `--bad` token. Pre-existing
  in `base.html`, not introduced here, but it should go through the status palette.

## Verification

Start the app on a throwaway database so nothing real is at risk:

```powershell
$env:RUNSPHERA_DB = "$env:TEMP\smoke.db"
.venv\Scripts\python.exe -m uvicorn runsphera.web.app:app --port 8771
```

Then, from another shell:

```bash
# Normal pages still work
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8771/          # 200

# The attack is refused
curl -s -X POST -H "Origin: http://evil.com" \
     http://127.0.0.1:8771/plans/1/delete                                 # 403

# DNS rebinding is refused
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
     -H "Host: evil.com" -H "Origin: http://evil.com" \
     http://127.0.0.1:8771/plans/1/delete                                 # 403

# Your own requests are not
curl -s -o /dev/null -w "%{http_code}\n" -X POST \
     -H "Origin: http://127.0.0.1:8771" \
     http://127.0.0.1:8771/plans/1/delete                                 # 303
```

Automated coverage: [`tests/test_same_origin.py`](../tests/test_same_origin.py) — 14 tests
over `refusal()` and `bare_host()`, including the cross-origin delete, the rebinding case,
IPv6 forms, and the non-browser passthrough.

## Future improvements

1. **Route the `.error` class through `--bad`** so refusal banners obey the status palette.
2. **Bind to `127.0.0.1` explicitly** rather than `0.0.0.0` in the launcher, so the app is
   not reachable from the LAN unless the operator opts in.
3. **A one-line Settings readout** showing the active allow-list, so a self-hoster can see
   what the app will accept without reading the environment.

---

*Last updated: 2026-10-23*
