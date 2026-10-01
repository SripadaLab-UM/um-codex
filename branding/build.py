"""UM-Codex's logo, and every icon file made from it.

    uv run --with pillow python branding/build.py
    uv run --with pillow python branding/build.py --preview <folder>   # PNGs at 1024, 64, 32, 16

Adapted from IHS DataLab's branding/build.py at 6b6fdca (its design "1b":
Block M, four-point spark, "IHS" under it). The practice variant, the earlier
options, the header and the frontend outputs are gone; "IHS" is replaced by
"codex".

The logo: U-M's Block M (traced to its polygon, as DataLab has it) in Maize
(#FFCB05) on Blue (#00274C), with "codex" centred under it and a big
four-point spark, the AI cue, over the M's top-right corner, edged in the
tile's colour so it reads where it crosses the M. "codex" is drawn here as
geometry, no font: lowercase letters on rounded-rectangle bowls (squarish, to
sit with the slab-serifed M), one stroke weight, with the c's and e's
terminals cut along rays from the bowl's centre, the d's stem rising a little
above the x-height and an x of two crossing strokes.

From 64 pixels up the icon is the whole design; at 32 the M and its spark,
drawn bigger for its size so it reads; at 16 the M alone.

This script writes branding/um-codex-mark.svg and its 1024 px PNG (on Apple's
icon grid), its copy for the launcher window's page
(src/umcodex/ui/static/mark.svg), and the launchers' icons, src/umcodex/branding/UM-Codex.icns (with
iconutil where there is one) and UM-Codex.ico. The bitmaps are drawn with
Pillow at 4x, then scaled down. Run it again after changing anything here, and
commit what it writes.
"""

from __future__ import annotations

import argparse
import io
import math
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "src" / "umcodex" / "branding"

MAIZE = "#FFCB05"
BLUE = "#00274C"
TILE, INK = BLUE, MAIZE

# ------------------------------------------------------------------ geometry

# The Block M (a 132 x 104 box), symmetric about x = 66: the slab serifs, the
# two legs and the V between them.
BLOCK_M_SIZE = (132.0, 104.0)
BLOCK_M = [
    (0, 0), (46, 0), (66, 52), (86, 0), (132, 0), (132, 24), (119, 24), (119, 82),
    (132, 82), (132, 104), (81, 104), (81, 82), (92, 82), (92, 30.5), (72.5, 82),
    (59.5, 82), (40, 30.5), (40, 82), (51, 82), (51, 104), (0, 104), (0, 82),
    (13, 82), (13, 24), (0, 24),
]  # fmt: skip

# A shape is a tuple: ("poly", points) | ("path", [contour, ...]) (filled
# even-odd: the first contour, then holes) | ("spark", cx, cy, r).
# Angles are degrees clockwise from three o'clock (y points down).
Shape = tuple[Any, ...]
Point = tuple[float, float]


def _rect(x: float, y: float, w: float, h: float) -> Shape:
    return ("poly", [(x, y), (x + w, y), (x + w, y + h), (x, y + h)])


# "codex", in letter units: the x-height is 20, the baseline y = 20.
X_HEIGHT = 20.0
STROKE = 5.0  # the letters' weight (DataLab's "IHS": 4.5 on capitals 20 high)
BOWL = 16.5  # a bowl's outer width (c, o, d, e)
CORNER = 7.0  # the bowl's outer corner radius (at least STROKE)
C_CUT = 45.0  # the c's terminals: normal angles C_CUT and 360 - C_CUT
E_CUT = 40.0  # the e's lower terminal
ASCENDER = 6.5  # the d's stem above the x-height
X_WIDTH = 14.0  # the x's width
SPACING = 3.4  # between letters
C_KERN = 0.8  # the c's open side: a little less after it
D_KERN = 0.6  # the d's flat side: a little more after it


def _contour(cx: float, cy: float, a0: float, b0: float, d: float, start: float, end: float) -> list[Point]:
    """A rounded rectangle's outline, offset `d` from the rectangle of its
    corner centres (half sizes a0, b0, centred on cx, cy), from normal angle
    `start` to `end` (either way round). Outlines with the same a0, b0 are
    concentric, so a cut at a normal angle is square to the stroke."""
    centres = [(a0, b0), (-a0, b0), (-a0, -b0), (a0, -b0)]  # from 0, 90, 180, 270 degrees

    def at(deg: float, corner: int) -> Point:
        ox, oy = centres[corner % 4]
        return (
            cx + ox + d * math.cos(math.radians(deg)),
            cy + oy + d * math.sin(math.radians(deg)),
        )

    lo, hi = min(start, end), max(start, end)
    angles = sorted({lo, hi, *(float(k) for k in range(math.ceil(lo), math.floor(hi) + 1) if k % 2 == 0)})
    points: list[Point] = []
    for deg in angles:
        corner = math.floor(deg / 90)
        if deg % 90 == 0 and lo < deg < hi:  # a wall between two corners
            points += [at(deg, corner - 1), at(deg, corner)]
        elif deg == hi and deg % 90 == 0:
            points.append(at(deg, corner - 1))
        else:
            points.append(at(deg, corner))
    return points if start <= end else points[::-1]


def _bowl(x: float, start: float = 0, end: float = 360, *, to_middle: bool = False) -> Shape:
    """A bowl BOWL wide and X_HEIGHT high, its left edge at x: a ring, or only
    the stretch from normal angle `start` to `end` (clockwise from three
    o'clock), cut square to the stroke. `to_middle`: carry the end on down the
    right-hand wall to the middle (the e, to meet its bar)."""
    cx, cy = x + BOWL / 2, X_HEIGHT / 2
    a0, b0 = BOWL / 2 - CORNER, X_HEIGHT / 2 - CORNER
    outer = _contour(cx, cy, a0, b0, CORNER, start, end)
    inner = _contour(cx, cy, a0, b0, CORNER - STROKE, end, start)
    if start == 0 and end == 360:
        return ("path", [outer, inner])
    if to_middle:
        outer.append((cx + a0 + CORNER, cy))
        inner.insert(0, (cx + a0 + CORNER - STROKE, cy))
    return ("path", [outer + inner])


def _x(x: float) -> list[Shape]:
    """Two strokes crossing, cut flat at the x-height and the baseline, each
    STROKE thick across."""
    w, h = X_WIDTH, X_HEIGHT
    t = STROKE * 0.94  # diagonals look heavier than uprights: a touch lighter
    dx = t
    for _ in range(20):  # the horizontal width giving that thickness across
        dx = t * math.hypot(w - dx, h) / h
    return [
        ("poly", [(x, 0), (x + dx, 0), (x + w, h), (x + w - dx, h)]),
        ("poly", [(x + w - dx, 0), (x + w, 0), (x + dx, h), (x, h)]),
    ]


def _codex() -> tuple[list[Shape], tuple[float, float]]:
    """ "codex" from the top of the d's stem (y = -ASCENDER) to the baseline;
    returns the shapes moved down so the box starts at y = 0, and its size."""
    shapes: list[Shape] = []
    x = 0.0
    shapes.append(_bowl(x, C_CUT, 360 - C_CUT))  # c
    x += BOWL + SPACING - C_KERN
    shapes.append(_bowl(x))  # o
    x += BOWL + SPACING
    # d: the bowl's left half, squared off on the right by its stem
    shapes.append(_bowl(x, 90, 270))
    left = x + CORNER  # where the half bowl ends
    shapes.append(_rect(left, 0, BOWL - CORNER - STROKE / 2, STROKE))
    shapes.append(_rect(left, X_HEIGHT - STROKE, BOWL - CORNER - STROKE / 2, STROKE))
    shapes.append(_rect(x + BOWL - STROKE, -ASCENDER, STROKE, X_HEIGHT + ASCENDER))
    x += BOWL + SPACING + D_KERN
    # e: the bowl open at the lower right, and its bar across the middle
    shapes.append(_bowl(x, E_CUT, 360, to_middle=True))
    bar = STROKE * 0.9
    shapes.append(_rect(x + STROKE / 2, X_HEIGHT / 2 - bar / 2, BOWL - STROKE / 2, bar))
    x += BOWL + SPACING
    shapes += _x(x)
    x += X_WIDTH
    return [_shift(s, 0, ASCENDER) for s in shapes], (x, X_HEIGHT + ASCENDER)


def _shift(shape: Shape, dx: float, dy: float) -> Shape:
    if shape[0] == "poly":
        return ("poly", [(x + dx, y + dy) for x, y in shape[1]])
    if shape[0] == "path":
        return ("path", [[(x + dx, y + dy) for x, y in c] for c in shape[1]])
    raise ValueError(shape[0])


# The icon, on a 64-unit square.
TILE_RADIUS = 12.0
LOCKUP_FROM = 64  # pixels: the whole design from here up
SMALL_FROM = 32  # pixels: from here to 64, the M and its spark; below, the M alone
M_ALONE = 44.0  # the M's width when it's alone (16 px)

# The M and "codex" (its width, "text") on the tile's axis, `top` the M's top;
# the spark (cx, cy, r) near the M's top-right corner.
LAYOUT = {
    "full": {"m": 30.0, "text": 44.0, "gap": 4.0, "top": 11.5, "spark": (45.5, 14.0, 11.5)},
    "small": {"m": 40.0, "top": 19.5, "spark": (46.0, 19.5, 15.5)},
}
HALO = 2.2  # the spark's knock-out edge, in the tile's colour

# One mark placed on the tile: its shapes, scale, x, y, and the width of the
# tile-coloured edge knocked out round it (None: none).
Placed = tuple[list[Shape], float, float, float, "float | None"]


def tier(size: int) -> str:
    """Which version of the icon a size in pixels gets."""
    if size >= LOCKUP_FROM:
        return "full"
    return "small" if size >= SMALL_FROM else "m"


def _spark_points(cx: float, cy: float, r: float, steps: int = 12) -> list[Point]:
    tips = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    waist = 0.12 * r
    corners = [(1, -1), (1, 1), (-1, 1), (-1, -1)]
    points: list[Point] = []
    for k in range(4):
        a, b = tips[k], tips[(k + 1) % 4]
        c = (cx + corners[k][0] * waist, cy + corners[k][1] * waist)
        for n in range(steps):
            t = n / steps
            points.append(
                (
                    (1 - t) ** 2 * a[0] + 2 * (1 - t) * t * c[0] + t**2 * b[0],
                    (1 - t) ** 2 * a[1] + 2 * (1 - t) * t * c[1] + t**2 * b[1],
                )
            )
    return points


def _placements(tier_: str) -> list[Placed]:
    """What goes on the 64-unit tile: "full", "small" (the M and its spark) or
    "m" (the M alone)."""
    mw, mh = BLOCK_M_SIZE
    m_shapes: list[Shape] = [("poly", BLOCK_M)]
    if tier_ == "m":
        s = M_ALONE / mw
        return [(m_shapes, s, (64 - M_ALONE) / 2, (64 - mh * s) / 2, None)]
    spec = LAYOUT[tier_]
    m_scale = spec["m"] / mw
    placed: list[Placed] = [(m_shapes, m_scale, (64 - spec["m"]) / 2, spec["top"], None)]
    if tier_ == "full":
        letters, (tw, _) = _codex()
        t_scale = spec["text"] / tw
        y = spec["top"] + mh * m_scale + spec["gap"]
        placed.append((letters, t_scale, (64 - spec["text"]) / 2, y, None))
    cx, cy, r = spec["spark"]
    placed.append(([("spark", cx, cy, r)], 1.0, 0.0, 0.0, HALO))
    return placed


# ------------------------------------------------------------------ SVG


def _n(v: float) -> str:
    return f"{round(v, 3):g}"


def _svg_d(shape: Shape) -> str:
    kind = shape[0]
    if kind == "poly":
        return "M" + " ".join(f"{_n(x)} {_n(y)}" for x, y in shape[1]) + "Z"
    if kind == "path":
        return "".join("M" + " ".join(f"{_n(x)} {_n(y)}" for x, y in c) + "Z" for c in shape[1])
    if kind == "spark":
        _, cx, cy, r = shape
        tips = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
        waist = 0.12 * r
        corners = [(1, -1), (1, 1), (-1, 1), (-1, -1)]
        d = f"M{_n(tips[0][0])} {_n(tips[0][1])}"
        for k in range(4):
            b = tips[(k + 1) % 4]
            c = (cx + corners[k][0] * waist, cy + corners[k][1] * waist)
            d += f"Q{_n(c[0])} {_n(c[1])} {_n(b[0])} {_n(b[1])}"
        return d + "Z"
    raise ValueError(kind)


def _svg_elements(shapes: Sequence[Shape], colour: str, halo: tuple[str, float] | None) -> str:
    parts = []
    for shape in shapes:
        d = _svg_d(shape)
        rule = ' fill-rule="evenodd"' if shape[0] == "path" else ""
        if halo:
            parts.append(
                f'<path d="{d}" fill="{colour}" stroke="{halo[0]}" '
                f'stroke-width="{_n(2 * halo[1])}" stroke-linejoin="round" paint-order="stroke"/>'
            )
        else:
            parts.append(f'<path d="{d}"{rule} fill="{colour}"/>')
    return "".join(parts)


def icon_svg(tier_: str = "full") -> str:
    body = [f'<rect width="64" height="64" rx="{_n(TILE_RADIUS)}" fill="{TILE}"/>']
    for shapes, scale, x, y, halo in _placements(tier_):
        inner = _svg_elements(shapes, INK, (TILE, halo) if halo else None)
        body.append(f'<g transform="translate({_n(x)} {_n(y)}) scale({_n(scale)})">{inner}</g>')
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">\n'
        "  <title>UM-Codex</title>\n  " + "\n  ".join(body) + "\n</svg>\n"
    )


# ------------------------------------------------------------------ bitmaps


def _paint(
    image: Image.Image,
    shapes: Sequence[Shape],
    at: Callable[[float, float], Point],
    unit: float,
    halo: tuple[str, float] | None = None,
) -> None:
    pen = ImageDraw.Draw(image)
    for shape in shapes:
        kind = shape[0]
        if kind == "poly":
            pen.polygon([at(x, y) for x, y in shape[1]], fill=INK)
        elif kind == "path":  # even-odd: the first contour, less the holes
            mask = Image.new("L", image.size, 0)
            mpen = ImageDraw.Draw(mask)
            for k, contour in enumerate(shape[1]):
                mpen.polygon([at(x, y) for x, y in contour], fill=255 if k == 0 else 0)
            image.paste(INK, (0, 0), mask)
        elif kind == "spark":
            _, cx, cy, r = shape
            points = [at(x, y) for x, y in _spark_points(cx, cy, r)]
            if halo:  # the knock-out edge: a tile-coloured stroke round it
                pen.line(
                    [*points, points[0], points[1]],
                    fill=halo[0],
                    joint="curve",
                    width=max(1, round(2 * halo[1] * unit)),
                )
            pen.polygon(points, fill=INK)


def draw(size: int, *, mac: bool = False, tier_: str | None = None) -> Image.Image:
    """The icon as a square RGBA bitmap. `mac`: on Apple's icon grid (an
    824/1024 rounded body, the rest transparent). `tier_`: which version (by
    default the one for `size`)."""
    scale = 4
    big = size * scale
    image = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    if mac:
        offset, unit, radius = big * 100 / 1024, big * 824 / 1024 / 64, big * 185 / 1024
    else:
        offset, unit, radius = 0.0, big / 64, TILE_RADIUS * big / 64
    pen.rounded_rectangle(
        (offset, offset, offset + 64 * unit - 1, offset + 64 * unit - 1), radius=radius, fill=TILE
    )
    for shapes, s, x, y, halo in _placements(tier_ or tier(size)):

        def at(u: float, v: float, s: float = s, x: float = x, y: float = y) -> Point:
            return offset + (x + u * s) * unit, offset + (y + v * s) * unit

        _paint(image, shapes, at, s * unit, (TILE, halo) if halo else None)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def icns() -> bytes:
    """With Apple's iconutil where there is one (every size, as macOS
    expects); otherwise Pillow's writer."""
    if shutil.which("iconutil"):
        with tempfile.TemporaryDirectory() as folder:
            iconset = Path(folder) / "UM-Codex.iconset"
            iconset.mkdir()
            for points in (16, 32, 128, 256, 512):
                for factor, name in ((1, ""), (2, "@2x")):
                    # By the size it's seen at (points), so a 16-point icon
                    # on a Retina screen is still the M alone.
                    image = draw(points * factor, mac=True, tier_=tier(points))
                    image.save(iconset / f"icon_{points}x{points}{name}.png")
            out = Path(folder) / "UM-Codex.icns"
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
            return out.read_bytes()
    buffer = io.BytesIO()
    big = draw(1024, mac=True)
    sizes = [draw(s, mac=True) for s in (16, 32, 64, 128, 256, 512)]
    big.save(buffer, format="ICNS", append_images=sizes)
    return buffer.getvalue()


def ico() -> bytes:
    buffer = io.BytesIO()
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    # Each size drawn on its own, so small ones stay crisp.
    frames = [draw(s) for s in sizes]
    frames[-1].save(buffer, format="ICO", sizes=[(s, s) for s in sizes], append_images=frames[:-1])
    return buffer.getvalue()


def png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# ------------------------------------------------------------------ main


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preview", type=Path, help="write the icon at 1024, 64, 32 and 16 px here (and 8x zooms)"
    )
    args = parser.parse_args()
    if args.preview:
        args.preview.mkdir(parents=True, exist_ok=True)
        for size in (1024, 64, 32, 16):
            image = draw(size)
            image.save(args.preview / f"um-codex-{size}.png")
            if size < 1024:
                zoom = image.resize((size * 8, size * 8), Image.Resampling.NEAREST)
                zoom.save(args.preview / f"um-codex-{size}-zoom.png")
        print(f"wrote {args.preview}/um-codex-*.png")
        return
    PACKAGE.mkdir(parents=True, exist_ok=True)
    written: dict[Path, bytes] = {
        REPO / "branding" / "um-codex-mark.svg": icon_svg().encode(),
        REPO / "src" / "umcodex" / "ui" / "static" / "mark.svg": icon_svg().encode(),  # the launcher window's
        REPO / "branding" / "um-codex-mark-1024.png": png(draw(1024, mac=True)),
        PACKAGE / "UM-Codex.icns": icns(),
        PACKAGE / "UM-Codex.ico": ico(),
    }
    for path, data in written.items():
        path.write_bytes(data)
        print(f"wrote {path.relative_to(REPO)} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
