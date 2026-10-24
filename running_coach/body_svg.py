"""Body diagram SVG geometry — silhouette path + anatomical muscle map.

Ported from the design handoff (silhouette-data.js + anatomy.js +
body-page.js). Lives separately from body.py because it's pure
geometry — no DB, no logic — and the data volume is large.

The silhouette path was traced from a reference body illustration:
260×560 viewBox, head is part of the path (no separate circle),
~186 contour points. Anatomy is a schematic muscle-group overlay
authored on the viewer-right half and mirrored to the left via
an SVG matrix transform.
"""
from __future__ import annotations


# ── Silhouette path (traced) ─────────────────────────────────────────

VIEWBOX_W = 260
VIEWBOX_H = 560

SILHOUETTE_D = (
    "M 131.3 10 L 141.7 10.7 L 148.2 13.9 L 154.1 19.8 L 157.4 27.6 "
    "L 158 43.2 L 160.6 44.5 L 160.6 50.4 L 157.4 58.2 L 154.1 60.2 "
    "L 151.5 69.3 L 151.5 85.6 L 156.1 89.5 L 169.1 96 L 194.5 105.1 "
    "L 202.3 111.6 L 204.9 116.2 L 207.5 125.3 L 207.5 150 L 211.4 167.6 "
    "L 212.7 180.7 L 212.1 186.5 L 216.6 195 L 220.5 210 L 223.1 238.6 "
    "L 227.1 262.1 L 228.4 267.3 L 240.1 280.3 L 240.1 293.4 L 239.4 291.4 "
    "L 237.5 289.4 L 236.8 290.1 L 240.1 319.4 L 236.8 319.4 L 232.9 300.5 "
    "L 231 296.6 L 230.3 302.5 L 232.3 320.7 L 229.7 322 L 227.7 318.1 "
    "L 225.8 300.5 L 224.5 297.9 L 224.5 322 L 221.2 319.4 L 218.6 299.2 "
    "L 217.9 314.8 L 214.7 314.8 L 212.1 285.5 L 214 271.2 L 213.4 266 "
    "L 209.5 253.6 L 195.1 220.4 L 192.5 210.6 L 192.5 202.2 L 189.9 185.2 "
    "L 184.7 162.4 L 183.4 157.9 L 182.1 157.9 L 174.9 201.5 L 177.6 232.1 "
    "L 181.5 247.1 L 185.4 273.8 L 185.4 307.7 L 182.8 339.6 L 177.6 367.6 "
    "L 178.9 401.5 L 180.8 415.2 L 180.2 438 L 169.7 499.2 L 171 502.4 "
    "L 171 514.8 L 177.6 525.2 L 184.1 532.4 L 188 540.2 L 185.4 544.1 "
    "L 180.8 547.4 L 178.2 546.7 L 176.2 548.7 L 173.6 548.7 L 171 546.1 "
    "L 169.7 548.7 L 167.1 550 L 161.9 548 L 158.7 544.1 L 155.4 529.2 "
    "L 152.1 523.3 L 155.4 489.4 L 147.6 439.3 L 147.6 384.5 L 138.5 318.1 "
    "L 136.5 285.5 L 132.6 286.2 L 130.7 322.7 L 122.8 374.1 L 121.5 392.4 "
    "L 122.2 436 L 114.4 488.1 L 115 505.7 L 117.6 517.4 L 117.6 523.3 "
    "L 114.4 529.2 L 111.8 542.2 L 109.8 546.1 L 105.2 549.3 L 100.7 549.3 "
    "L 98.7 546.1 L 95.5 548.7 L 92.9 548.7 L 90.9 546.7 L 88.3 547.4 "
    "L 81.8 540.9 L 82.4 537 L 98.1 516.1 L 98.1 504.4 L 100 497.9 "
    "L 89 433.4 L 89 410 L 90.9 399.5 L 90.3 387.8 L 91.6 363.7 "
    "L 89 354.6 L 86.4 335 L 83.8 296.6 L 85.1 266 L 91.6 234.7 "
    "L 94.2 209.3 L 94.2 194.3 L 87.7 157.9 L 87 157.2 L 85.7 159.2 "
    "L 80.5 181.3 L 77.9 195 L 77.2 208.7 L 74 221.7 L 59.7 254.9 "
    "L 55.7 267.9 L 57 275.1 L 57 294 L 55.1 314.2 L 54.4 315.5 "
    "L 51.8 314.8 L 51.2 298.6 L 48.6 318.1 L 46.6 322 L 44.7 321.4 "
    "L 45.3 297.9 L 44 299.2 L 41.4 319.4 L 38.2 322 L 36.9 318.1 "
    "L 39.5 302.5 L 38.8 296.6 L 36.2 302.5 L 33.6 317.5 L 30.3 320.1 "
    "L 29 316.8 L 32.9 290.1 L 32.3 289.4 L 24.5 298.6 L 21.9 299.9 "
    "L 19.9 298.6 L 30.3 279 L 40.8 267.9 L 42.1 264 L 46 241.9 "
    "L 49.9 205.4 L 53.8 193 L 57.7 186.5 L 57.7 170.9 L 61.6 152.7 "
    "L 61.6 129.2 L 64.2 117.5 L 67.5 111.6 L 75.3 105.1 L 103.3 94.7 "
    "L 117.6 86.2 L 118.9 83 L 118.9 72.5 L 115.7 61.5 L 109.8 53.6 "
    "L 109.2 44.5 L 111.8 43.2 L 111.1 34.8 L 114.4 21.7 L 120.2 14.6 "
    "L 131.3 10 Z"
)


# ── Region geometry (27 hitboxes + glow centers) ─────────────────────
# Each entry: (design_key, region, side, cx, cy, rx, ry)
# design_key uses the design's compact form: 'hipflexor-L', 'ham-R',
# 'upperback' (no side suffix for midline). This is what the rendered
# SVG hooks use — body.py provides translation to/from DB form.
# Viewer-left = person's Right (-R); viewer-right = person's Left (-L).

REGIONS: dict[str, list[dict]] = {
    "front": [
        {"key": "shoulder-R",  "region": "Shoulder",   "side": "Right", "cx": 72,  "cy": 138, "rx": 22, "ry": 17},
        {"key": "shoulder-L",  "region": "Shoulder",   "side": "Left",  "cx": 196, "cy": 138, "rx": 22, "ry": 17},
        {"key": "hipflexor-R", "region": "Hip flexor", "side": "Right", "cx": 112, "cy": 292, "rx": 14, "ry": 15},
        {"key": "hipflexor-L", "region": "Hip flexor", "side": "Left",  "cx": 150, "cy": 292, "rx": 14, "ry": 15},
        {"key": "quad-R",      "region": "Quad",       "side": "Right", "cx": 108, "cy": 348, "rx": 18, "ry": 34},
        {"key": "quad-L",      "region": "Quad",       "side": "Left",  "cx": 162, "cy": 348, "rx": 18, "ry": 34},
        {"key": "knee-R",      "region": "Knee",       "side": "Right", "cx": 105, "cy": 410, "rx": 15, "ry": 15},
        {"key": "knee-L",      "region": "Knee",       "side": "Left",  "cx": 164, "cy": 410, "rx": 15, "ry": 15},
        {"key": "shin-R",      "region": "Shin",       "side": "Right", "cx": 106, "cy": 452, "rx": 13, "ry": 27},
        {"key": "shin-L",      "region": "Shin",       "side": "Left",  "cx": 164, "cy": 452, "rx": 13, "ry": 27},
        {"key": "ankle-R",     "region": "Ankle",      "side": "Right", "cx": 107, "cy": 508, "rx": 11, "ry": 12},
        {"key": "ankle-L",     "region": "Ankle",      "side": "Left",  "cx": 162, "cy": 508, "rx": 11, "ry": 12},
        {"key": "foot-R",      "region": "Foot",       "side": "Right", "cx": 99,  "cy": 536, "rx": 16, "ry": 10},
        {"key": "foot-L",      "region": "Foot",       "side": "Left",  "cx": 170, "cy": 536, "rx": 16, "ry": 10},
    ],
    "back": [
        # Note: back view is NOT mirrored — when you're behind someone,
        # their left is your left. So viewer-left (cx < 130) carries the
        # -L suffix (person's Left); viewer-right (cx > 130) carries -R.
        # This corrects the handoff's REGIONS["back"], which followed the
        # front-view convention by mistake.
        {"key": "neck",        "region": "Neck",       "side": "",      "cx": 130, "cy": 98,  "rx": 16, "ry": 13},
        {"key": "upperback",   "region": "Upper back", "side": "",      "cx": 130, "cy": 150, "rx": 36, "ry": 32},
        {"key": "lowerback",   "region": "Lower back", "side": "",      "cx": 130, "cy": 225, "rx": 30, "ry": 28},
        {"key": "glute-L",     "region": "Glute",      "side": "Left",  "cx": 98,  "cy": 288, "rx": 19, "ry": 21},
        {"key": "glute-R",     "region": "Glute",      "side": "Right", "cx": 162, "cy": 288, "rx": 19, "ry": 21},
        {"key": "ham-L",       "region": "Hamstring",  "side": "Left",  "cx": 108, "cy": 352, "rx": 18, "ry": 34},
        {"key": "ham-R",       "region": "Hamstring",  "side": "Right", "cx": 162, "cy": 352, "rx": 18, "ry": 34},
        {"key": "calf-L",      "region": "Calf",       "side": "Left",  "cx": 106, "cy": 448, "rx": 15, "ry": 28},
        {"key": "calf-R",      "region": "Calf",       "side": "Right", "cx": 164, "cy": 448, "rx": 15, "ry": 28},
        {"key": "achilles-L",  "region": "Achilles",   "side": "Left",  "cx": 107, "cy": 506, "rx": 9,  "ry": 13},
        {"key": "achilles-R",  "region": "Achilles",   "side": "Right", "cx": 162, "cy": 506, "rx": 9,  "ry": 13},
        {"key": "heel-L",      "region": "Heel",       "side": "Left",  "cx": 99,  "cy": 536, "rx": 14, "ry": 10},
        {"key": "heel-R",      "region": "Heel",       "side": "Right", "cx": 168, "cy": 536, "rx": 14, "ry": 10},
    ],
}


# ── Anatomy: schematic muscle groups (ported from anatomy.js) ─────────
# Each entry: side ('R' authored on viewer-right, 'C' central),
# optional mg (design region key for hover-link), optional poly
# (list of (x, y) points fed through Catmull-Rom to a closed curve)
# OR ell (cx, cy, rx, ry for ellipse), optional detail (raw path d).

FRONT_MUSCLES = [
    {"side": "R", "poly": [(130,98),(152,104),(176,116),(196,132),(176,134),(150,118)]},  # trapezius upper
    {"side": "R", "mg": "shoulder-L", "poly": [(176,120),(196,116),(210,134),(208,158),(193,162),(180,142)]},  # deltoid
    {"side": "R", "poly": [(131,150),(160,146),(182,158),(180,176),(160,188),(134,184),(131,166)]},  # pectoral
    {"side": "R", "poly": [(190,150),(206,152),(214,180),(212,205),(200,208),(189,180)]},  # biceps
    {"side": "R", "poly": [(196,212),(214,218),(224,250),(221,260),(208,260),(196,232)]},  # forearm
    {"side": "C",
     "poly": [(108,154),(152,154),(154,205),(150,250),(130,262),(110,250),(106,205)],
     "detail": "M130 158 V258 M107.5 178 H152.5 M105.5 202 H154.5 M107.5 228 H152.5"},  # rectus abdominis
    {"side": "R", "poly": [(152,168),(172,178),(174,218),(164,250),(152,244),(151,205)]},  # oblique
    {"side": "R", "mg": "hipflexor-L", "poly": [(131,242),(150,246),(156,268),(150,290),(134,292),(131,266)]},  # hip flexor
    {"side": "R", "mg": "quad-L",
     "poly": [(143,300),(166,304),(178,340),(176,378),(168,396),(152,396),(143,350),(142,320)],
     "detail": "M162 312 Q167 355 164 392 M171 322 Q175 355 172 384"},  # quadriceps
    {"side": "R", "mg": "knee-L", "ell": (164, 410, 11, 9)},  # patella
    {"side": "R", "mg": "shin-L", "poly": [(150,418),(166,424),(172,462),(170,486),(158,484),(149,440)]},  # tibialis anterior
]

BACK_MUSCLES = [
    # mg tags use -R on viewer-right authored shapes because the BACK
    # view is not mirrored (viewer-right = person's right). The L-side
    # gets generated by the matrix mirror, where _swap_side_suffix flips
    # -R → -L on the mg tag so the muscle still tags the correct region.
    {"side": "R", "mg": "neck", "poly": [(130,86),(146,92),(148,110),(130,112)]},  # neck
    {"side": "R", "mg": "upperback", "poly": [(130,94),(156,106),(178,132),(190,162),(152,178),(130,176)]},  # trapezius diamond
    {"side": "R", "poly": [(176,122),(196,118),(210,136),(208,160),(193,164),(180,144)]},  # posterior deltoid
    {"side": "R", "poly": [(150,178),(178,184),(176,224),(150,256),(134,232),(143,196)]},  # latissimus dorsi
    {"side": "R", "poly": [(190,150),(208,152),(216,182),(214,208),(200,210),(189,180)]},  # triceps
    {"side": "R", "poly": [(196,214),(214,220),(224,252),(221,262),(208,262),(196,234)]},  # forearm
    {"side": "R", "mg": "lowerback",
     "poly": [(131,198),(148,202),(150,244),(144,266),(131,266),(131,224)],
     "detail": "M139 208 V260"},  # erector spinae
    {"side": "R", "mg": "glute-R",
     "poly": [(131,258),(160,258),(184,280),(182,312),(156,322),(134,312),(131,284)],
     "detail": "M132 270 Q160 276 178 300"},  # gluteus maximus (viewer-right = person's right)
    {"side": "R", "mg": "ham-R",
     "poly": [(140,304),(166,308),(178,344),(177,384),(168,402),(152,402),(141,352),(140,322)],
     "detail": "M162 314 Q168 356 165 398 M171 324 Q176 356 173 386"},  # hamstrings
    {"side": "R", "mg": "calf-R",
     "poly": [(148,414),(168,418),(178,448),(176,480),(164,492),(152,486),(147,452),(147,428)],
     "detail": "M163 422 Q166 456 163 486"},  # gastrocnemius
    {"side": "R", "mg": "achilles-R", "poly": [(158,492),(167,494),(168,516),(156,516),(155,496)]},  # achilles
    {"side": "R", "mg": "heel-R", "ell": (168, 536, 13, 9)},  # heel
]


def _catmull_closed(points: list[tuple[float, float]]) -> str:
    """Convert a list of (x, y) points to a smooth closed cubic-Bezier
    path via Catmull-Rom interpolation. Ported from anatomy.js."""
    n = len(points)
    if n == 0:
        return ""
    p0 = points[0]
    d = f"M {p0[0]:.1f} {p0[1]:.1f} "
    for i in range(n):
        p_prev = points[(i - 1 + n) % n]
        p_cur = points[i]
        p_next = points[(i + 1) % n]
        p_after = points[(i + 2) % n]
        c1x = p_cur[0] + (p_next[0] - p_prev[0]) / 6
        c1y = p_cur[1] + (p_next[1] - p_prev[1]) / 6
        c2x = p_next[0] - (p_after[0] - p_cur[0]) / 6
        c2y = p_next[1] - (p_cur[1] - p_prev[1]) / 6
        # Note: matched the JS formula exactly. c2y uses (p_cur - p_prev)
        # in JS source — see anatomy.js line 21 (`p3[1]-p1[1]` → after vs cur).
        c2y = p_next[1] - (p_after[1] - p_cur[1]) / 6
        d += f"C {c1x:.1f} {c1y:.1f} {c2x:.1f} {c2y:.1f} {p_next[0]:.1f} {p_next[1]:.1f} "
    return d + "Z"


def _swap_side_suffix(mg: str) -> str:
    """Mirror a region key from one side to the other ('quad-L' -> 'quad-R')."""
    if not mg:
        return mg
    if mg.endswith("-L"):
        return mg[:-2] + "-R"
    if mg.endswith("-R"):
        return mg[:-2] + "-L"
    return mg


def _shape_markup(shape: dict, mg: str) -> str:
    """Render one muscle shape as inner SVG markup."""
    attr = f' data-mg="{mg}"' if mg else ""
    if "ell" in shape:
        cx, cy, rx, ry = shape["ell"]
        return f'<ellipse class="m"{attr} cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}"/>'
    d = _catmull_closed(shape["poly"])
    return f'<path class="m"{attr} d="{d}"/>'


def _side_pass(groups: list[dict], mirror: bool) -> str:
    """Render one pass of muscles (R-side, or mirror for L-side)."""
    body_parts: list[str] = []
    details: list[str] = []
    for s in groups:
        if s["side"] == "C":
            if mirror:
                continue  # central shapes render once
            body_parts.append(_shape_markup(s, s.get("mg", "")))
            if "detail" in s:
                details.append(f'<path class="m-detail" d="{s["detail"]}"/>')
            continue
        mg = _swap_side_suffix(s.get("mg", "")) if mirror else s.get("mg", "")
        body_parts.append(_shape_markup(s, mg))
        if "detail" in s:
            details.append(f'<path class="m-detail" d="{s["detail"]}"/>')
    return "".join(body_parts) + "".join(details)


def build_muscles_svg(face: str) -> str:
    """Return inner SVG markup for the muscle layer at this face.

    Authored on the viewer-right (x > 130); the left side is generated
    by mirroring via an SVG `matrix(-1 0 0 1 260 0)` transform group.
    """
    groups = FRONT_MUSCLES if face == "front" else BACK_MUSCLES
    right = _side_pass(groups, mirror=False)
    left = _side_pass(groups, mirror=True)
    return right + f'<g transform="matrix(-1 0 0 1 260 0)">{left}</g>'


# ── DB-to-design key translation ─────────────────────────────────────
# Our DB stores ('hip_flexor', 'left'); the design uses 'front:hipflexor-L'.
# The face is derivable from the region (calf is always back, quad always
# front, etc.), so the mapping is one-to-one.

REGION_FACE: dict[str, str] = {
    "shoulder": "front",
    "hip_flexor": "front",
    "quad": "front",
    "knee": "front",
    "shin": "front",
    "ankle": "front",
    "foot": "front",
    "neck": "back",
    "upper_back": "back",
    "lower_back": "back",
    "glute": "back",
    "hamstring": "back",
    "calf": "back",
    "achilles": "back",
    "heel": "back",
}

# DB region key → design's compact form
_TO_DESIGN_REGION = {
    "hip_flexor": "hipflexor",
    "upper_back": "upperback",
    "lower_back": "lowerback",
    "hamstring": "ham",
}
_FROM_DESIGN_REGION = {v: k for k, v in _TO_DESIGN_REGION.items()}


def to_design_key(region: str, side: str) -> str:
    """('hip_flexor', 'left') -> 'front:hipflexor-L'.
    ('neck', 'midline') -> 'back:neck'."""
    face = REGION_FACE.get(region, "front")
    design_region = _TO_DESIGN_REGION.get(region, region)
    if side == "midline":
        return f"{face}:{design_region}"
    suffix = "L" if side == "left" else "R"
    return f"{face}:{design_region}-{suffix}"


def from_design_key(design_key: str) -> tuple[str, str]:
    """'front:hipflexor-L' -> ('hip_flexor', 'left').
    'back:neck' -> ('neck', 'midline')."""
    _, rest = design_key.split(":", 1)
    if rest.endswith("-L") or rest.endswith("-R"):
        bare, suffix = rest[:-2], rest[-1]
        side = "left" if suffix == "L" else "right"
    else:
        bare, side = rest, "midline"
    db_region = _FROM_DESIGN_REGION.get(bare, bare)
    return db_region, side


def region_face(region: str) -> str:
    """Return 'front' or 'back' for a DB region key."""
    return REGION_FACE.get(region, "front")
