"""Turn the GitHub avatar into the card's ASCII portrait.

Writes assets/ascii-art.txt (dark card: light glyphs on a dark background, so
bright pixels get the dense characters) and assets/ascii-art-light.txt (light
card: the ramp is inverted, so dark pixels get the dense characters).

Because the portrait is rebuilt from the live avatar on every workflow run,
changing the GitHub profile picture updates the card on its own.

Want hand-tuned art instead? Drop your own files into assets/ and create an
empty assets/ascii-art.lock -- this script then leaves them alone.

Usage:
    python tools/build_ascii.py               # download github.com/<login>.png
    python tools/build_ascii.py avatar.png    # or use a local image
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
LOCK = ASSETS / "ascii-art.lock"
LOGIN = os.environ.get("GH_LOGIN", "petruff")

COLS = 84
# build_card.ART_CELL_ASPECT: a glyph cell is 0.54 as wide as it is tall, so a
# square photo needs COLS * 0.54 rows to keep its proportions.
CELL_ASPECT = 0.54

# Sparse to dense. A plain space is the background; the rest climbs in ink.
RAMP = " .:-=+*#%@"

# Backdrop detection: a studio headshot sits on a light, colourless backdrop
# (and GitHub's own round crop adds white corners). Anything light and grey
# that is connected to the image border is treated as backdrop and left blank,
# so the portrait floats on the card instead of sitting in a block of ink.
BG_MIN_LIGHT = 150      # 0-255: darker than this is never backdrop
BG_MAX_CHROMA = 22      # max(R,G,B) - min(R,G,B): more colourful is never backdrop
BG_COVER = 0.5          # a cell is blank once this share of it is backdrop


def load_avatar(arg: str | None) -> Image.Image:
    if arg:
        return Image.open(arg)
    import requests

    resp = requests.get(f"https://github.com/{LOGIN}.png?size=460", timeout=30)
    resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content))


def backdrop_mask(rgb: Image.Image) -> Image.Image:
    """255 where the pixel is backdrop: light, grey, and reachable from the edge."""
    w, h = rgb.size
    cand = Image.new("L", (w, h), 0)
    px, cp = rgb.load(), cand.load()
    for y in range(h):
        for x in range(w):
            r, g, b = px[x, y]
            if min(r, g, b) >= BG_MIN_LIGHT and max(r, g, b) - min(r, g, b) <= BG_MAX_CHROMA:
                cp[x, y] = 128
    # Keep only candidates connected to the border: a pale shirt or a
    # highlight on the forehead is not backdrop.
    for x in range(w):
        for y in (0, h - 1):
            if cp[x, y] == 128:
                ImageDraw.floodfill(cand, (x, y), 255)
    for y in range(h):
        for x in (0, w - 1):
            if cp[x, y] == 128:
                ImageDraw.floodfill(cand, (x, y), 255)
    return cand.point(lambda v: 255 if v == 255 else 0)


def prepare(img: Image.Image) -> tuple[Image.Image, Image.Image]:
    """Return (tone, backdrop) at grid size: 0-255 brightness and 0-255 cover."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        flat = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(flat, img)
    img = img.convert("RGB")
    side = min(img.size)
    img = ImageOps.fit(img, (side, side), centering=(0.5, 0.42))
    work = img.resize((300, 300), Image.LANCZOS)
    mask = backdrop_mask(work)

    grey = ImageOps.grayscale(work)
    # Stretch contrast over the subject only, so the backdrop's white does not
    # flatten the face.
    hist = grey.histogram(mask=ImageOps.invert(mask))
    total = sum(hist)
    lo = hi = None
    seen = 0
    for v, n in enumerate(hist):
        seen += n
        if lo is None and seen >= total * 0.02:
            lo = v
        if hi is None and seen >= total * 0.98:
            hi = v
    lo, hi = lo or 0, max(hi or 255, (lo or 0) + 1)
    grey = grey.point(lambda v: max(0, min(255, round((v - lo) * 255 / (hi - lo)))))
    grey = grey.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=2))

    rows = round(COLS * CELL_ASPECT)
    return grey.resize((COLS, rows), Image.BOX), mask.resize((COLS, rows), Image.BOX)


def render(tone: Image.Image, backdrop: Image.Image, invert: bool) -> str:
    w, h = tone.size
    top = len(RAMP) - 1
    lines = []
    for y in range(h):
        row = []
        for x in range(w):
            if backdrop.getpixel((x, y)) >= 255 * BG_COVER:
                row.append(" ")
                continue
            v = tone.getpixel((x, y))
            ink = (255 - v) / 255 if invert else v / 255
            row.append(RAMP[max(1, round(ink * top))])
        lines.append("".join(row).rstrip())
    return "\n".join(lines).strip("\n") + "\n"


def main() -> None:
    if LOCK.exists():
        print(f"{LOCK.relative_to(ROOT)} present -- keeping the hand-made art")
        return
    tone, backdrop = prepare(load_avatar(sys.argv[1] if len(sys.argv) > 1 else None))
    ASSETS.mkdir(exist_ok=True)
    for name, invert in (("ascii-art.txt", False), ("ascii-art-light.txt", True)):
        out = ASSETS / name
        out.write_text(render(tone, backdrop, invert), encoding="utf-8", newline="\n")
        print(f"wrote {out.relative_to(ROOT)} ({tone.size[0]}x{tone.size[1]})")


if __name__ == "__main__":
    main()
