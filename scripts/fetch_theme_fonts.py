"""One-shot helper: download woff2 font files from Google Fonts and emit a
local @font-face CSS pointing at them. Run from the project root:

    .venv\\Scripts\\python.exe scripts\\fetch_theme_fonts.py

Output:
    runsphera/web/static/fonts/<family>-<weight>[i].woff2
    runsphera/web/static/fonts/tempo-fonts.css
    runsphera/web/static/fonts/redline-fonts.css

Google Fonts serves different files based on User-Agent; we ask for the modern
Chrome stack to get woff2 (smallest, broadly supported).
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS_DIR = ROOT / "runsphera" / "web" / "static" / "fonts"
FONTS_DIR.mkdir(parents=True, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Per-theme font shopping list. Slugs map to a stable local filename.
THEMES: dict[str, list[dict]] = {
    "tempo": [
        {"family": "Inter", "weights": [300, 400, 500, 600, 700, 800], "italic": False, "slug": "inter"},
        {"family": "JetBrains Mono", "weights": [400, 500, 600, 700], "italic": False, "slug": "jetbrains-mono"},
        {"family": "Archivo Black", "weights": [400], "italic": False, "slug": "archivo-black"},
    ],
    "redline": [
        {"family": "Inter", "weights": [300, 400, 500, 600, 700, 800], "italic": False, "slug": "inter"},
        {"family": "IBM Plex Mono", "weights": [400, 500, 600, 700], "italic": False, "slug": "ibm-plex-mono"},
        {"family": "Barlow Condensed", "weights": [700, 900], "italic": True, "slug": "barlow-condensed"},
    ],
}


def _fetch(url: str, *, text: bool = False, params: dict | None = None) -> bytes | str:
    if params:
        from urllib.parse import urlencode
        url = f"{url}?{urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = resp.read()
    return data.decode("utf-8") if text else data


def google_css_url(family: str, weights: list[int], italic: bool) -> str:
    """Build a Google Fonts v2 CSS URL covering the requested weights (and
    italic counterparts when needed)."""
    fam = family.replace(" ", "+")
    if italic:
        axes = "ital,wght"
        pairs = [f"0,{w}" for w in weights] + [f"1,{w}" for w in weights]
    else:
        axes = "wght"
        pairs = [str(w) for w in weights]
    return f"https://fonts.googleapis.com/css2?family={fam}:{axes}@{';'.join(pairs)}&display=swap"


# Google Fonts splits each weight into multiple subsets (cyrillic, greek, latin,
# latin-ext, vietnamese, ...). We pull just the latin subset — covers Western
# European including Dutch, and keeps the byte budget tight.
_BLOCK_RE = re.compile(
    r"/\*\s*([\w-]+)\s*\*/\s*"                # subset comment (e.g. /* latin */)
    r"@font-face\s*\{([^}]+)\}",
    re.DOTALL,
)
_WEIGHT_RE = re.compile(r"font-weight:\s*(\d+)")
_STYLE_RE = re.compile(r"font-style:\s*(\w+)")
_SRC_RE = re.compile(r"url\((https://[^)]+\.woff2)\)")

WANTED_SUBSETS = ("latin",)


def parse_faces(css: str) -> list[dict]:
    out: list[dict] = []
    for subset, block in _BLOCK_RE.findall(css):
        if subset not in WANTED_SUBSETS:
            continue
        w = _WEIGHT_RE.search(block)
        s = _STYLE_RE.search(block)
        u = _SRC_RE.search(block)
        if not (w and u):
            continue
        out.append({
            "subset": subset,
            "weight": int(w.group(1)),
            "style": (s.group(1) if s else "normal"),
            "url": u.group(1),
        })
    return out


def download_family(family: str, weights: list[int], italic: bool, slug: str) -> list[dict]:
    """Returns list of {family, weight, style, filename} after downloading."""
    css_url = google_css_url(family, weights, italic)
    css = _fetch(css_url, text=True)
    faces = parse_faces(css)
    saved: list[dict] = []
    for f in faces:
        if f["weight"] not in weights:
            continue
        suffix = "i" if f["style"] == "italic" else ""
        local_name = f"{slug}-{f['weight']}{suffix}.woff2"
        local_path = FONTS_DIR / local_name
        # Force re-download if the file is suspiciously small (stale from a bad
        # earlier subset selection).
        if local_path.exists() and local_path.stat().st_size > 4000:
            print(f"  cached     {local_name:32}  {local_path.stat().st_size:>7} bytes")
        else:
            data = _fetch(f["url"])
            local_path.write_bytes(data)
            print(f"  downloaded {local_name:32}  {len(data):>7} bytes")
        saved.append({
            "family": family,
            "weight": f["weight"],
            "style": f["style"],
            "filename": local_name,
        })
    return saved


def write_theme_css(theme_name: str, all_faces: list[dict]) -> None:
    css_path = FONTS_DIR / f"{theme_name}-fonts.css"
    lines = [f"/* {theme_name.upper()} theme fonts — self-hosted from Google Fonts. */"]
    for f in all_faces:
        lines.append(
            "@font-face { "
            f"font-family: '{f['family']}'; "
            f"font-style: {f['style']}; "
            f"font-weight: {f['weight']}; "
            "font-display: swap; "
            f"src: url('/static/fonts/{f['filename']}') format('woff2'); "
            "}"
        )
    css_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  wrote      {css_path.relative_to(ROOT)}")


def main() -> int:
    themes = sys.argv[1:] or list(THEMES.keys())
    for theme in themes:
        if theme not in THEMES:
            print(f"unknown theme: {theme}", file=sys.stderr)
            return 1
        print(f"\n=== {theme} ===")
        all_faces: list[dict] = []
        for f in THEMES[theme]:
            faces = download_family(f["family"], f["weights"], f["italic"], f["slug"])
            all_faces.extend(faces)
        write_theme_css(theme, all_faces)
    return 0


if __name__ == "__main__":
    sys.exit(main())
