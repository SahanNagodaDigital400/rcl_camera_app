"""Render the PWA icon set from the one master logo.

The master (`apps/web/brand/rocell-logo.png`) is the brand asset as supplied:
the four-square mark with its own white frame. Everything under
`apps/web/public/icons/` is generated from it and nothing else, so the icons
cannot drift apart from each other or from the brand.

Two families come out of it, because the platforms ask for two different
things and handing one to the other looks broken:

* **`any`** — shown as given. The master already carries a ~4% white frame, so
  it is only resized. Corner rounding by the platform nibbles that frame,
  which is what the frame is for.
* **`maskable`** — the platform crops to a shape of its choosing, and
  guarantees nothing outside the centred circle of 80% diameter. The mark is
  scaled down onto a white field so the wordmark stays inside that circle:
  the tail of the final `l` reaches the mark's right edge at mid-height,
  exactly where a circular mask cuts closest. Handing the platform an `any`
  icon here would cut the wordmark in half.

Regenerating is a deliberate act, not a build step: the output is committed,
and `apps/web` builds with npm and never runs Python.

    uv run python scripts/generate_brand_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent
MASTER = REPO_ROOT / "apps" / "web" / "brand" / "rocell-logo.png"
ICONS = REPO_ROOT / "apps" / "web" / "public" / "icons"
FAVICON = REPO_ROOT / "apps" / "web" / "public" / "favicon.ico"

# The white field a scaled-down mark sits on, and the field a favicon's
# transparency would otherwise be composited against by a dark browser chrome.
WHITE = (255, 255, 255)

# How much of a maskable icon's edge the mark spans. The safe area is a circle
# of 80% diameter, whose inscribed square is only 57% — small enough that the
# icon reads as a stamp rather than a logo. 0.66 keeps every part of the
# wordmark inside the safe circle and loses only the outermost corner of a flat
# colour square, which is what platform masks round off anyway.
MASKABLE_SPAN = 0.66

# `sizes` in the manifest, per purpose. 192 and 512 are the two the install
# prompt requires; 512 is also the splash screen's source.
ANY_SIZES = (192, 512)
MASKABLE_SIZES = (192, 512)

# iOS applies its own rounded-rect mask and ignores the manifest entirely, so
# this one is linked from the document head at the one size iOS asks for.
APPLE_TOUCH_SIZE = 180

# Sizes inside favicon.ico. A browser asks for /favicon.ico whether or not the
# head links one; 48 is what Windows shortcuts pick up.
FAVICON_SIZES = (16, 32, 48)


def load_master() -> Image.Image:
    """The master as RGB, with its own white frame intact."""
    if not MASTER.exists():
        raise SystemExit(f"Master logo is missing: {MASTER}")
    master = Image.open(MASTER).convert("RGB")
    if master.width != master.height:
        raise SystemExit(f"Master logo must be square, got {master.width}x{master.height}")
    return master


def trimmed(master: Image.Image) -> Image.Image:
    """The mark alone, with the master's white frame cropped away.

    A maskable icon adds a margin of its own, and stacking that on top of the
    master's frame would shrink the mark twice over.
    """
    from PIL import ImageChops

    field = Image.new("RGB", master.size, WHITE)
    box = ImageChops.difference(master, field).getbbox()
    if box is None:
        raise SystemExit("Master logo is blank")
    return master.crop(box)


def resized(source: Image.Image, size: int) -> Image.Image:
    return source.resize((size, size), Image.Resampling.LANCZOS)


def maskable(mark: Image.Image, size: int) -> Image.Image:
    """The mark centred on a white field, inside the maskable safe area."""
    canvas = Image.new("RGB", (size, size), WHITE)
    span = round(size * MASKABLE_SPAN)
    offset = (size - span) // 2
    canvas.paste(resized(mark, span), (offset, offset))
    return canvas


def write(image: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=True)
    print(f"  {path.relative_to(REPO_ROOT)}  {image.width}x{image.height}")


def main() -> None:
    master = load_master()
    mark = trimmed(master)
    print(f"Master {master.width}x{master.width}, mark {mark.width}x{mark.height}")

    for size in ANY_SIZES:
        write(resized(master, size), ICONS / f"icon-{size}.png")
    for size in MASKABLE_SIZES:
        write(maskable(mark, size), ICONS / f"icon-maskable-{size}.png")
    write(resized(master, APPLE_TOUCH_SIZE), ICONS / "apple-touch-icon.png")

    largest = max(FAVICON_SIZES)
    resized(master, largest).save(
        FAVICON,
        format="ICO",
        sizes=[(size, size) for size in FAVICON_SIZES],
    )
    print(f"  {FAVICON.relative_to(REPO_ROOT)}  {', '.join(str(s) for s in FAVICON_SIZES)}")


if __name__ == "__main__":
    main()
