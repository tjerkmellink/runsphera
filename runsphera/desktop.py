"""Desktop launcher: a native window wrapping the local dashboard.

Daily use (no console window):
    .venv\\Scripts\\pythonw.exe -m runsphera.desktop

Debug (keeps a console for tracebacks):
    .venv\\Scripts\\python.exe -m runsphera.desktop

Starts the FastAPI app on 127.0.0.1:8000 in a background thread and opens a
native OS window pointed at it (Edge WebView2 on Windows 11). Closing the
window shuts the server down. If something is already serving on the port
(e.g. you ran `python -m runsphera.web` separately), the launcher skips
starting its own server and just opens a window against the running one.

While uvicorn boots (cold start is ~10-20s), the window shows a branded
RunSphera splash; it swaps to the app once the server actually answers an
HTTP request, and falls back to a Retry screen if it never does.
"""
from __future__ import annotations

import base64
import ctypes
import socket
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path


class _TimestampedStream:
    """Line-prefixing wrapper so the launcher log reads as a timeline.

    Without wall-clock stamps and elapsed times the log could tell us *that* a
    boot failed but never *where* it stalled, which is the only thing worth
    knowing when the window is stuck on the splash.
    """

    def __init__(self, stream) -> None:
        self._stream = stream
        self._start = time.monotonic()
        self._at_line_start = True

    def write(self, text: str) -> int:
        for part in text.splitlines(keepends=True):
            if self._at_line_start and part.strip():
                stamp = time.strftime("%H:%M:%S")
                self._stream.write(f"{stamp} +{time.monotonic() - self._start:6.1f}s  ")
            self._stream.write(part)
            self._at_line_start = part.endswith("\n")
        return len(text)

    def flush(self) -> None:
        self._stream.flush()

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._stream.fileno()

    def writable(self) -> bool:
        return True

    def close(self) -> None:
        self._stream.close()


def _attach_streams() -> Path | None:
    """Give the process real stdout/stderr before anything else imports.

    pythonw.exe starts with `sys.stdout is None`. Any library that so much as
    inspects it then explodes — uvicorn's log formatter calls
    `sys.stdout.isatty()` in `uvicorn.Config.__init__`, so merely constructing
    the config raised, killing the launcher before it could open a window. With
    no console attached the traceback went nowhere, which made it look like the
    app "just didn't start".

    Pointing the streams at a log file both fixes that class of crash and leaves
    a readable trace the next time a windowless launch misbehaves. Must run
    before `import uvicorn`.
    """
    if sys.stdout is not None and sys.stderr is not None:
        return None
    log_path = Path(__file__).resolve().parent.parent / "data" / "desktop.log"
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        # Truncate per launch: this log exists to explain *this* start-up, and an
        # ever-growing file made it impossible to tell which run a line came from.
        stream = _TimestampedStream(open(log_path, "w", encoding="utf-8", buffering=1))
    except OSError:
        # Read-only install or no data dir — a black hole still beats a crash.
        import os

        stream = open(os.devnull, "w", encoding="utf-8")
        log_path = None
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream
    return log_path


_LOG_PATH = _attach_streams()

import uvicorn  # noqa: E402  (must follow _attach_streams)

# `webview` is imported inside main(), not here — see the note there. Only main()
# touches it; every annotation referencing it is a string under
# `from __future__ import annotations`, so nothing needs it at module level.

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"
# Probe a route that returns instantly. Polling `/` instead would time out on
# every attempt — the dashboard needs seconds to render — and the launcher would
# fall through to the Retry screen even though the server was up all along.
HEALTH_URL = f"{URL}/healthz"
APP_ID = "RunSphera.Coach"  # Windows taskbar identity (groups under our own icon)

_HERE = Path(__file__).resolve().parent
# Stable WebView2 profile (see the note in main()); keeps cookies across launches.
_WEBVIEW_PROFILE = _HERE.parent / "data" / "webview"
_BRAND = _HERE / "web" / "static" / "brand"
_ICON = _HERE / "assets" / "RunSphera.ico"


def _data_uri(path: Path, mime: str) -> str:
    """Base64 data: URI, so the splash needs no server and no external files."""
    try:
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
    except OSError:
        return ""


_SPLASH_LIGHT = _data_uri(_BRAND / "splash-light.jpg", "image/jpeg")
_SPLASH_DARK = _data_uri(_BRAND / "splash-dark.jpg", "image/jpeg")

# The light splash has the RunSphera wordmark + tagline baked into the artwork,
# so we overlay only the live spinner. The dark splash is still the textless
# hero, so we overlay an HTML wordmark in dark mode until a baked dark splash
# lands (drop `Splash - Dark-clean`, rebuild, then flip this to True).
_DARK_WORDMARK_BAKED = False


def _splash_html() -> str:
    """Branded loading splash: baked hero background + a live spinner overlay."""
    overlay_mark = (
        ""
        if _DARK_WORDMARK_BAKED
        else """
  <div class="overlay-mark">
    <h1 class="wordmark">RunSphera</h1>
    <p class="tagline">Keep on running.</p>
  </div>"""
    )
    return f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  html, body {{ height: 100%; margin: 0; overflow: hidden; }}
  body {{
    position: relative;
    background: #f6f4ef center/cover no-repeat;
    background-image: url("{_SPLASH_LIGHT}");
    color: #16130f;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    -webkit-user-select: none; user-select: none;
  }}
  @media (prefers-color-scheme: dark) {{
    body {{ background-color: #0a0a0a; color: #f3efe8; background-image: url("{_SPLASH_DARK}"); }}
  }}
  /* HTML wordmark: hidden in light (baked into art), shown in dark until baked. */
  .overlay-mark {{
    display: none; position: absolute; top: 40%; left: 0; right: 0;
    transform: translateY(-50%); text-align: center;
  }}
  @media (prefers-color-scheme: dark) {{ .overlay-mark {{ display: block; }} }}
  .wordmark {{
    font-weight: 900; font-style: italic; font-size: 3.2rem;
    letter-spacing: -0.03em; line-height: 1; margin: 0;
  }}
  .tagline {{
    color: #ff3b1f; font-weight: 600; font-style: italic;
    font-size: 1.05rem; margin: 0.5rem 0 0;
  }}
  .loader {{
    position: absolute; top: 66%; left: 0; right: 0; text-align: center;
  }}
  .ring {{
    width: 42px; height: 42px; border-radius: 50%;
    border: 4px solid rgba(127,127,127,0.28); border-top-color: #ff3b1f;
    animation: spin 0.9s linear infinite; margin: 0 auto;
  }}
  .status {{
    margin-top: 1rem; font-size: 0.8rem; letter-spacing: 0.12em;
    color: #7a756c; text-transform: uppercase;
    font-family: ui-monospace, 'JetBrains Mono', monospace;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  @media (prefers-reduced-motion: reduce) {{ .ring {{ animation-duration: 2.4s; }} }}
</style>
</head>
<body>{overlay_mark}
  <div class="loader">
    <div class="ring"></div>
    <div class="status">Warming up&hellip;</div>
  </div>
</body>
</html>
"""


def _error_html() -> str:
    """Shown when the server never answers: recoverable, not a dead end."""
    log_line = (
        f"Startup log: <code>{_LOG_PATH}</code><br>" if _LOG_PATH is not None else ""
    )
    return f"""\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  html, body {{ height: 100%; margin: 0; }}
  body {{
    display: flex; flex-direction: column;
    align-items: center; justify-content: center; text-align: center;
    padding: 2rem; gap: 0.4rem;
    background: #f6f4ef; color: #16130f;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    -webkit-user-select: none; user-select: none;
  }}
  @media (prefers-color-scheme: dark) {{ body {{ background: #0a0a0a; color: #f3efe8; }} }}
  .wordmark {{ font-weight: 900; font-style: italic; font-size: 1.6rem; letter-spacing: -0.03em; margin: 0 0 1rem; }}
  h2 {{ font-size: 1.25rem; margin: 0; }}
  p {{ color: #7a756c; max-width: 34rem; line-height: 1.5; margin: 0.35rem 0 0; }}
  .btn {{
    margin-top: 1.5rem; border: 0; border-radius: 10px; cursor: pointer;
    background: #ff3b1f; color: #fffaf3; font-weight: 700;
    font-size: 0.95rem; padding: 0.7rem 1.6rem;
  }}
  .btn:active {{ transform: translateY(1px); }}
  .details-toggle {{
    margin-top: 1.1rem; font-size: 0.78rem; color: #7a756c;
    background: none; border: 0; cursor: pointer; text-decoration: underline;
  }}
  .details {{
    display: none; margin-top: 0.9rem; text-align: left;
    max-width: 34rem; font-size: 0.8rem; line-height: 1.6; color: #7a756c;
    font-family: ui-monospace, 'JetBrains Mono', monospace;
  }}
  .details.show {{ display: block; }}
  code {{ font-family: ui-monospace, 'JetBrains Mono', monospace; }}
</style>
</head>
<body>
  <h1 class="wordmark">RunSphera</h1>
  <h2>Couldn&rsquo;t start the app</h2>
  <p>The dashboard didn&rsquo;t respond in time. This is usually temporary &mdash; give it another try.</p>
  <button class="btn" onclick="window.pywebview.api.retry()">Retry</button>
  <button class="details-toggle" onclick="document.getElementById('d').classList.toggle('show')">Show details</button>
  <div class="details" id="d">
    Serving address: <code>{URL}</code><br>
    {log_line}
    If Retry keeps failing, launch the debug build to see the error:<br>
    <code>.venv\\Scripts\\python.exe -m runsphera.desktop</code>
  </div>
</body>
</html>
"""


def _port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    """True if something accepts a TCP connection on host:port right now."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        return sock.connect_ex((host, port)) == 0


def _probe(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """Ask whether the app answers HTTP. Returns (responded, reason-if-not).

    The reason matters: "connection refused" (not listening yet) and "timed out"
    (listening but wedged) are the same symptom on screen and completely
    different bugs, so the loser of a boot race gets logged either way.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            if resp.status < 500:
                return True, ""
            return False, f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        # An error *status* still proves something is serving. Notably a 404
        # means an older RunSphera build (one without /healthz) already holds
        # the port — load the app anyway rather than sit here until we time out.
        if exc.code < 500:
            return True, ""
        return False, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        return False, f"{type(exc.reason).__name__}: {exc.reason}"
    except (TimeoutError, ConnectionError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"


# Hard ceiling on the wait for a server we started. Only reached if the thread is
# alive but wedged — a healthy cold start is an order of magnitude faster.
CEILING = 600.0
# Ceiling when something *else* already holds the port. That server is by
# definition already booted, so it should answer at once; if it doesn't, it isn't
# ours and no amount of patience will help.
ATTACHED_CEILING = 30.0
# Cold starts past this look broken to the user, so the splash starts explaining
# itself rather than spinning mutely.
EXPLAIN_AFTER = 20.0


def _wait_until_ready(
    url: str,
    is_alive: "Callable[[], bool] | None" = None,
    on_progress: "Callable[[float], None] | None" = None,
    ceiling: float = CEILING,
) -> bool:
    """Poll until the app answers, the server dies, or the ceiling is hit.

    Deliberately *not* a fixed timeout. Boot time here is dominated by disk I/O
    and antivirus scanning of the venv, which varies enormously — a warm start
    answers in 3s, a cold one has been measured at 34s and 62s on the same
    machine. Any constant is therefore either too short (a healthy-but-cold boot
    gets declared dead, which is the bug users actually hit) or so long that a
    genuinely dead server hangs the splash.

    Liveness is the honest signal: while our own uvicorn thread is running there
    is every reason to keep waiting, and the moment it dies there is no reason to
    wait at all.
    """
    start = time.monotonic()
    attempts = 0
    last_reason = "no attempt made"
    while True:
        attempts += 1
        ok, last_reason = _probe(url)
        elapsed = time.monotonic() - start
        if ok:
            print(f"ready: {url} answered after {elapsed:.1f}s ({attempts} probes)")
            return True
        if is_alive is not None and not is_alive():
            print(f"NOT READY: the server thread exited after {elapsed:.1f}s "
                  f"({attempts} probes); last failure: {last_reason}")
            return False
        if elapsed > ceiling:
            print(f"NOT READY: gave up after {elapsed:.0f}s ({attempts} probes); "
                  f"the server is still running but never answered; "
                  f"last failure: {last_reason}")
            return False
        if on_progress is not None:
            on_progress(elapsed)
        time.sleep(0.25)


class _Bridge:
    """JS <-> Python bridge; owns the server so Retry can restart a dead one."""

    def __init__(self, url: str, health_url: str) -> None:
        self._url = url
        self._health_url = health_url
        self._window: webview.Window | None = None
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    def attach(self, window: "webview.Window") -> None:
        self._window = window

    # -- server lifecycle -------------------------------------------------

    def start_server(self) -> None:
        """Start uvicorn unless the port is already served or we already did.

        Never raises: without a console a crash here is invisible, so it logs
        and lets the window open on the Retry screen instead of the process
        vanishing with no explanation.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        if _port_is_open(HOST, PORT):
            print("launcher: port already serving — attaching to that instance")
            return
        try:
            config = uvicorn.Config(
                "runsphera.web.app:app",
                host=HOST,
                port=PORT,
                reload=False,
                log_level="warning",
            )
            self._server = uvicorn.Server(config)
            self._thread = threading.Thread(
                target=_run_server, args=(self._server,), daemon=True
            )
            self._thread.start()
            print("launcher: server thread started")
        except Exception:
            traceback.print_exc()
            self._server = self._thread = None

    def _server_alive(self) -> bool:
        """True while there's reason to keep waiting for a response.

        When we didn't start the server (something else holds the port) there is
        no thread to watch, so fall back to the ceiling.
        """
        if self._thread is None:
            return True
        return self._thread.is_alive()

    def shutdown(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)

    # -- boot / retry -----------------------------------------------------

    def _set_status(self, text: str) -> None:
        """Update the splash's status line, ignoring a navigated-away document."""
        window = self._window
        if window is None:
            return
        try:
            window.evaluate_js(
                "(function(el){if(el)el.textContent=%r;})"
                "(document.querySelector('.status'))" % text
            )
        except Exception:
            pass  # page already replaced, or the bridge is gone — cosmetic only

    def boot(self, show_splash: bool = True) -> None:
        """Wait for the server, then load the app — or the retry screen."""
        window = self._window
        if window is None:
            return
        if show_splash:
            window.load_html(_splash_html())

        shown: list[str] = []

        def progress(elapsed: float) -> None:
            # Cheap throttle: only repaint when the whole-second label changes.
            label = (
                "Warming up…"
                if elapsed < EXPLAIN_AFTER
                else f"First launch is slow — {int(elapsed)}s"
            )
            if not shown or shown[-1] != label:
                shown.append(label)
                self._set_status(label)

        # We own the server → wait as long as it lives. Someone else owns it →
        # it is already up, so give it only a short grace period.
        ceiling = CEILING if self._thread is not None else ATTACHED_CEILING
        if _wait_until_ready(
            self._health_url, self._server_alive, progress, ceiling
        ):
            print(f"launcher: loading {self._url}")
            window.load_url(self._url)
        else:
            print("launcher: showing the Retry screen")
            window.load_html(_error_html())

    def retry(self) -> None:
        print("launcher: Retry pressed")

        def again() -> None:
            # A dead server is the likely reason we're here — restart it.
            self.start_server()
            self.boot(show_splash=True)

        # Run off the JS-bridge thread so the wait doesn't block it.
        threading.Thread(target=again, daemon=True).start()


def _run_server(server: "uvicorn.Server") -> None:
    """Run uvicorn, making sure a failure to boot leaves a trace.

    `BaseException` is deliberate. When uvicorn can't load the ASGI app it calls
    `sys.exit(3)`, and a `SystemExit` raised in a non-main thread is discarded
    silently by `threading` — no excepthook, no output. That produced exactly the
    symptom we were chasing: a server that never answered and never explained
    why.
    """
    try:
        server.run()
        print("server: uvicorn.run() returned (shutting down)")
    except BaseException:
        print("server: uvicorn died during start-up")
        traceback.print_exc()


def _set_windows_app_identity() -> None:
    """Group the window under our own taskbar identity, not 'Python'."""
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass  # non-Windows or API unavailable; harmless


def main() -> None:
    _set_windows_app_identity()
    # The elapsed stamp on this first line is the cost of importing this module
    # (chiefly `import uvicorn`) — the clock starts when the log is attached.
    print(f"launcher: module imported; python={sys.executable}")

    bridge = _Bridge(URL, HEALTH_URL)
    bridge.start_server()

    # Import webview *after* the server thread is running, so its (cold-start)
    # disk cost overlaps the server's instead of running before it. Both imports
    # are I/O-bound on a cold cache — measured at ~36s for uvicorn+webview and
    # ~70s for the app — and there is no reason to serialise them.
    t_import = time.monotonic()
    import webview

    print(f"launcher: webview imported in {time.monotonic() - t_import:.1f}s")

    # Open the window immediately on a splash screen; swap to the app once the
    # server actually answers. Avoids the "can't reach this page" flash.
    window = webview.create_window(
        "RunSphera",
        html=_splash_html(),
        js_api=bridge,
        width=1280,
        height=920,
        min_size=(900, 600),
    )
    bridge.attach(window)

    icon = str(_ICON) if _ICON.exists() else None
    # Splash is already shown by create_window, so skip re-rendering it here.
    #
    # private_mode=False + a fixed storage_path keeps WebView2's profile in one
    # place. The default (private mode) makes a throwaway profile per launch and
    # deletes it on exit, which on Windows regularly fails with "the process
    # cannot access the file" and leaves orphaned msedgewebview2 processes and
    # temp folders piling up. A stable profile also keeps the Garmin session
    # alive between launches instead of forcing a fresh sign-in.
    webview.start(
        lambda: bridge.boot(show_splash=False),
        icon=icon,
        private_mode=False,
        storage_path=str(_WEBVIEW_PROFILE),
    )

    bridge.shutdown()


if __name__ == "__main__":
    main()
