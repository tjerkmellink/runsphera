# Desktop launcher

> Install once, then launch RunSphera from a pinned taskbar / Desktop / Start-Menu shortcut — its own native window, no VS Code, no terminal, no browser tab.

## Purpose

Daily use of the app used to mean: open VS Code, run `python -m running_coach.web`, then open a browser at `localhost:8000`. Three steps and a lingering terminal. The desktop launcher collapses that to one click on a **RunSphera** shortcut. It wraps the existing local web app in a native OS window (Edge WebView2 on Windows 11) so RunSphera feels like a standalone application while the architecture underneath is unchanged.

Setup and daily launch are now split into two things:

- **`install.cmd`** — the installer. Run once. Creates the virtual environment, installs dependencies, and creates the RunSphera shortcuts. Re-run it to repair a broken install.
- **The RunSphera shortcut** — the entry point. Desktop + Start Menu (and pin it to the taskbar). Launches the app directly with the right icon and taskbar identity.

## How it works (user view)

- **First run (fresh checkout, no `.venv` yet)**: double-click **`install.cmd`**. A console window opens, creates the virtual environment, installs dependencies from `requirements.txt` (a few minutes), creates the shortcuts, and starts the app. If no Python 3 is installed at all, it explains where to get it and waits for a keypress instead of flashing an error.
- **Every run after that**: launch from the **RunSphera shortcut** (Desktop, Start Menu, or pinned taskbar). A native "RunSphera" window opens on the dashboard. No console window lingers.
- **Pin it**: right-click the Desktop or Start-Menu shortcut → *Pin to taskbar*. Pin the **shortcut**, not the running window — see "Taskbar identity" below for why.
- **While it boots**: the window shows a branded RunSphera splash (hero art + wordmark + a live spinner) instead of a blank/"can't reach page" screen, then swaps to the dashboard once the server actually answers. Past ~20s the spinner's status line starts reporting elapsed seconds, so a slow boot reads as slow rather than hung. The **Retry** screen appears only if the server actually dies (or wedges past a 10-minute ceiling) — see "Waiting on liveness, not a timeout".
- **How long that takes**: **wildly variable — measured between 6s and 116s on the same machine.** Warm it's ~6s; a cold cache pushes it past a minute. Almost all of it is disk I/O and antivirus scanning of the venv, not app code (see "Startup cost" below).
- **Close the window** to quit — the background server shuts down with it.
- Everything inside the window is the normal app: sync, plans, diary, settings. First-run Garmin sign-in + MFA works inside the window just as it does in a browser.

If you already have a server running (e.g. you ran `python -m running_coach.web` separately), the launcher detects the open port and just opens a window against that instance instead of starting a second server.

## How it works (implementation)

- **Modules**:
  - `running_coach/desktop.py` — the launcher. Attaches real stdout/stderr (see "`pythonw` has no stdout" below), sets the Windows AppUserModelID, starts `uvicorn` in a daemon thread (unless `127.0.0.1:8000` is already serving), shows the splash immediately, polls `/healthz` until the app answers, then loads the dashboard (or the Retry screen on timeout). Signals `server.should_exit` on window close.
  - `install.cmd` — repo-root installer/repair batch file. Health-checks the environment, sets it up if needed, then runs `scripts/install_shortcut.ps1` and launches the app.
  - `scripts/install_shortcut.ps1` — authors the `RunSphera.lnk` shortcuts (repo root, Desktop, Start Menu) with the icon and AppUserModelID (PowerShell + inline C#, no extra deps).
- **Brand assets** (`running_coach/assets/RunSphera.ico`, `running_coach/web/static/brand/*`) are generated from the `brand/` masters by `scripts/build_brand_assets.py`. Committed so a fresh install has them without rebuilding.
- **Self-bootstrapping**: `install.cmd` health-checks — `.venv\Scripts\pythonw.exe` must exist *and* `python -c "import fastapi, uvicorn, jinja2, webview"` must succeed. If either fails (fresh checkout, or a previous install died halfway), it sets the venv up. The import check makes it self-healing — a broken venv triggers a re-install when you re-run `install.cmd`, no marker files involved.
- **Splash/retry**: the splash and error screens are self-contained HTML built in `desktop.py` (`_splash_html` / `_error_html`); the splash embeds the hero JPEGs as base64 data URIs so it needs no server. Retry is wired through a pywebview `js_api` bridge (`_Bridge.retry`).
- **Readiness probe**: `GET /healthz` in `running_coach/web/app.py` — returns a bare `ok`, touching no DB and rendering no template. The launcher must be able to distinguish "still booting" from "never coming up", and `/` is useless for that: it takes 1.5–3s to render, so probing it with any sane per-request timeout reads a healthy server as a dead one.
- **Routes / DB / templates**: one route added (`/healthz`); otherwise it serves the existing FastAPI app verbatim.

Data flow: RunSphera shortcut → `pythonw -m running_coach.desktop` → uvicorn (background thread) + pywebview window showing the splash (main thread, blocks) → HTTP-ready → load dashboard → window close → `should_exit` → thread join.

## `pythonw` has no stdout (the silent-failure trap)

The shortcut runs `pythonw.exe`, which starts with **`sys.stdout` and `sys.stderr` set to `None`**. That breaks more than printing: any library that merely *inspects* the stream crashes. uvicorn's log formatter calls `sys.stdout.isatty()` in `uvicorn.Config.__init__`, so simply constructing the config raised `ValueError: Unable to configure formatter 'default'` — the server never started, and with no console the traceback went nowhere. The app looked like it "just didn't start".

Two guards, both in `desktop.py`:

- **`_attach_streams()`** runs at import time, *before* `import uvicorn`, and points `sys.stdout`/`sys.stderr` at `data/desktop.log` (falling back to `os.devnull` if that path isn't writable). This is why the `uvicorn`/`webview` imports sit below a function definition instead of at the top of the file — do not "tidy" them back up, or the crash returns.
- **The server start is wrapped in `try/except`**, which logs the traceback and still opens the window. A Retry screen naming the log file is a far better failure than a process that vanishes.

**When a launch misbehaves, read `data/desktop.log` first** — it holds anything the windowless process printed, including tracebacks. Every line is prefixed with a wall-clock time and seconds-since-launch, and the file is **truncated on each launch** so it always describes the run you just did. It's gitignored. A healthy boot looks like:

```
15:04:45 +   0.6s  launcher: module imported; python=...\.venv\Scripts\pythonw.exe
15:04:46 +   1.1s  launcher: server thread started
15:04:46 +   1.4s  launcher: webview imported in 0.2s
15:04:52 +   7.9s  ready: http://127.0.0.1:8000/healthz answered after 4.1s (2 probes)
15:04:52 +   7.9s  launcher: loading http://127.0.0.1:8000
```

The elapsed stamp on the *first* line is the cost of importing this module (mostly `import uvicorn`), which is otherwise invisible — on the cold run that reproduced the failure it read `+35.9s`.

One more silent-failure trap closed on the same path: `_run_server` catches **`BaseException`**, not `Exception`. When uvicorn cannot load the ASGI app it calls `sys.exit(3)`, and a `SystemExit` raised in a non-main thread is discarded by `threading` with no excepthook and no output — a server that never answers and never says why.

Note that launching `pythonw` from a shell (bash, or PowerShell with `-RedirectStandardOutput`) **hands it an inherited stdout pipe**, so `sys.stdout` is not `None` and this whole failure mode disappears. Reproducing it requires launching the way the shortcut does — the `.lnk`, or `Start-Process` with no redirection.

## Waiting on liveness, not a timeout

The launcher originally waited a fixed 60s for the server, then 120s. **Both were wrong, and no constant is right.** Measured on one machine across a single afternoon, time-to-first-response ranged from **4s to 70s**, and total time-to-dashboard from **6s to 116s** — the same code, the same checkout, differing only in how much of `.venv` the OS still had cached and what the antivirus felt like doing. Pick a constant and you either declare a healthy-but-cold boot dead (the bug users actually hit: splash → "Couldn't start the app") or make a genuinely dead server hang the splash for minutes.

`_wait_until_ready` therefore polls on **liveness** instead:

- **We started the server** → keep waiting as long as the uvicorn thread is alive; bail the instant it dies. A 10-minute `CEILING` catches a wedged-but-alive thread.
- **Something else already holds the port** → there is no thread to watch, and that server is by definition already booted, so it gets only `ATTACHED_CEILING` (30s) before the Retry screen. If it hasn't answered by then it isn't RunSphera.

**Retry** restarts a dead server rather than just re-polling a corpse — `_Bridge` owns the server lifecycle (`start_server` / `_server_alive` / `shutdown`) precisely so it can.

## Startup cost

Measured on this machine, launching `pythonw -m running_coach.desktop` with a timestamped trace:

| Step | Cold | Warm |
| --- | --- | --- |
| `import running_coach.desktop` (chiefly `import uvicorn`) | 35.9s | 0.6s |
| `import webview` | (in the same 35.9s) | 0.2s |
| uvicorn thread up to answering `/healthz` (imports `running_coach.web.app`) | 69.8s | 4.1s |
| `GET /` (dashboard render) | ~2s | ~1.7s |
| **Total to dashboard** | **~116s** | **~8s** |

Two things follow, and both are counter-intuitive:

**The dashboard render is the cheap part.** It never exceeded ~3s. All the pain is in imports.

**The imports are not slow — reading them off disk is.** Warm, the entire cost is under 1s for `uvicorn` + `webview` and ~4s for the app; `python -X importtime -c "import running_coach.web.app"` totals ~2.3s and attributes ~1.1s of that to `anthropic`, imported eagerly via `running_coach.llm.commentary`. The 30–70s cold penalty is the OS and antivirus reading thousands of small `.pyc`/`.dll` files out of `.venv`. That is why a launch that takes two minutes for the user takes six seconds when reproduced a minute later: the second run reads everything from the file cache.

So micro-optimising imports buys a second or two warm and barely dents the cold case. **Excluding the checkout (and the venv) from real-time antivirus scanning is by far the biggest available win.** Code-side, the module now starts the uvicorn thread *before* `import webview`, so those two independent cold-start costs overlap instead of running back to back; lazy-importing `anthropic` behind the first coach-commentary call is the remaining worthwhile trim.

## Taskbar identity (why pin the shortcut, not the window)

Setting the window icon alone is **not** enough for pinning. If you pin the *running window*, Windows creates the pin from the bare process — `pythonw.exe` with no arguments — so the pin shows the Python icon and clicking it just runs an empty Python that exits ("pinned app doesn't work").

The fix is the shortcut, which carries both the `RunSphera.ico` icon **and** `System.AppUserModel.ID = RunSphera.Coach`, matching the AppUserModelID the process sets via `SetCurrentProcessExplicitAppUserModelID`. That shared identity lets the running window merge into the pinned shortcut. So: **pin the shortcut**, and it keeps the RunSphera icon and launches correctly.

## Configuration

- **Host/port**: constants `HOST` / `PORT` in `running_coach/desktop.py` (default `127.0.0.1:8000`).
- **Window size**: `width` / `height` / `min_size` in the `webview.create_window(...)` call.
- **App identity**: `APP_ID` in `desktop.py` and `$AppId` in `install_shortcut.ps1` — keep them equal.
- **Debug variant**: run `.venv\Scripts\python.exe -m running_coach.desktop` (note: `python`, not `pythonw`) to keep a console for tracebacks.

## Known limitations

- **Windows-only as shipped.** `install.cmd`, `install_shortcut.ps1`, and the `pythonw.exe` path are Windows. `pywebview` itself is cross-platform, so `desktop.py` would run on macOS/Linux with a different launcher.
- **Machine-specific shortcut.** `RunSphera.lnk` hardcodes this checkout's paths, so it isn't portable between machines/users. Distributing to other users would want a real installer or a PyInstaller `.exe` with the icon embedded. `RunSphera.lnk` is gitignored.
- **Splash masks, doesn't cure, the cold start.** A cold boot can still take ~2 minutes behind the splash. It's dominated by disk/antivirus cost, not import cost — see "Startup cost".
- **WebView2 profile is stored, not private.** `webview.start(private_mode=False, storage_path=data/webview)`. pywebview's default builds a throwaway profile per launch under `%TEMP%` and deletes it on exit; on Windows that regularly fails (`WinError 32 … used by another process`) and leaks orphaned `msedgewebview2` processes and temp folders — 19 of them had accumulated here. The stored profile also keeps the Garmin session alive between launches. Delete `data/webview/` to reset it.
- **A stale instance on port 8000 wins.** The launcher attaches to whatever already serves the port, so an older build left running keeps serving its own (older) code. `_server_responds` treats a 404 as "up" so this attaches rather than hanging, but if the window looks out of date, check for a leftover `pythonw` process.
- **WebView2 dependency.** Relies on the Edge WebView2 runtime, which ships with Windows 11.
- **No tray / background mode.** Closing the window quits; window = app.
- **Dark splash wordmark.** The light splash has the wordmark baked into the art; the dark splash still overlays an HTML wordmark until a baked dark splash lands (`_DARK_WORDMARK_BAKED` in `desktop.py`).

## Verification

0. Bootstrap path: rename `.venv` away, double-click `install.cmd` — a setup console appears, installs everything, creates shortcuts, and starts the app. Self-heal path: `pip uninstall -y fastapi` inside the venv, run `install.cmd` again — setup re-runs and repairs it.
1. Ensure nothing is on port 8000, then launch the RunSphera shortcut. The splash appears immediately and a "RunSphera" window swaps to the dashboard within a few seconds (longer on a cold start).
1a. Windowless-launch regression: with nothing on port 8000, run `Start-Process .venv\Scripts\pythonw.exe -ArgumentList "-m","running_coach.desktop"` — **no** output redirection, so `sys.stdout` is `None` as it is under the shortcut — then confirm `curl http://127.0.0.1:8000/healthz` returns `ok` and the process has a window. Launching via bash instead will *not* exercise this path.
2. Close the window. Confirm no `python`/`pythonw` process is left listening on 8000 (`Get-NetTCPConnection -LocalPort 8000 -State Listen`).
3. Taskbar: pin the Desktop shortcut, launch it — the pinned icon stays RunSphera (not the Python feather) and the running window merges into the pin.
4. Attach path: start `python -m running_coach.web` manually, then launch the shortcut. It opens a window against the existing server without a port-clash error.

## Future improvements

- Cross-platform launcher scripts (`.command` / `.desktop`) and a portable installer / bundled `.exe` if the app ever ships to other users.
- A baked dark splash so both light and dark use the same wordmark treatment.
- Lazy-import `anthropic` (~1.1s of warm import) behind the first coach-commentary call.
- Recommend an antivirus exclusion for the checkout in `install.cmd`'s closing notes — the single biggest cold-start win available.
- Consider a tray-resident mode, or keeping the server warm between launches, so the cold start is paid once per boot rather than once per launch.

---

*Last updated: 2026-08-12*
