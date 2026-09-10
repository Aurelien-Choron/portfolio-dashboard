"""Generates the app mark: the header SVG and every icon file.

Run after changing the brand colour or the geometry:

    python scripts/generate_icons.py

Why a script rather than committed binaries: the mark is defined once, here, as
geometry. The header SVG and the PNG/ICO icons are then two renderings of the same
numbers, so they cannot drift apart, and regenerating after a palette change is one
command. Same convention as scripts/generate_demo_data.py.

The mark
--------
A letterform, not an abstract symbol — the previous icon was a generic bar chart in
a blue that is no longer the brand colour.

The field is a rounded square whose **top-left corner is drawn much tighter than
the other three**. That asymmetry is the same corner mark the interface puts on
everything clickable (see `.tab-btn::before` in base.html), so the icon and the UI
speak one language, and the silhouette alone is recognisable at 16px in a browser
tab. Tight, not square: the UI bracket is rounded, and a hard right angle here
would no longer echo it.

The "A" is drawn geometrically — two tapering legs from a shared apex and a
crossbar — rather than set in a typeface. No font file to depend on, exact control
at small sizes, and it keeps the neobank register: straight strokes, wide counter.
"""
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dashboard import palette  # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "dashboard", "static")
TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "dashboard", "templates")

# --- geometry, in a 0..1 square ---------------------------------------------
CORNER_RADIUS = 0.22          # of the field's side
CORNER_RADIUS_TL = 0.07       # top-left, drawn tight — the mark's signature
APEX_Y, BASE_Y = 0.20, 0.80
LEG_OUTER, LEG_INNER = 0.155, 0.375   # x of each leg's feet, left side
BAR_Y, BAR_H = 0.605, 0.105           # crossbar top and height
SUPERSAMPLE = 8               # draw large, downsample: PIL has no anti-aliasing


def letter_polygons(size: float, ox: float = 0.0, oy: float = 0.0, scale: float = 1.0):
    """The three shapes of the 'A'. Everything between them stays field colour,
    which is what forms the counter."""
    def pt(x, y):
        return (ox + (0.5 + (x - 0.5) * scale) * size,
                oy + (0.5 + (y - 0.5) * scale) * size)

    apex_half = (LEG_INNER - LEG_OUTER) / 2
    left_leg = [pt(0.5 - apex_half, APEX_Y), pt(0.5, APEX_Y),
                pt(LEG_INNER, BASE_Y), pt(LEG_OUTER, BASE_Y)]
    right_leg = [pt(0.5, APEX_Y), pt(0.5 + apex_half, APEX_Y),
                 pt(1 - LEG_OUTER, BASE_Y), pt(1 - LEG_INNER, BASE_Y)]
    # The bar spans between the legs at its own height, following their slope.
    def leg_x_at(y):
        t = (y - APEX_Y) / (BASE_Y - APEX_Y)
        return 0.5 - apex_half + (LEG_OUTER - (0.5 - apex_half)) * t

    x0, x1 = leg_x_at(BAR_Y), leg_x_at(BAR_Y + BAR_H)
    bar = [pt(x1, BAR_Y + BAR_H), pt(1 - x1, BAR_Y + BAR_H),
           pt(1 - x0, BAR_Y), pt(x0, BAR_Y)]
    return [left_leg, right_leg, bar]


def render(size: int, safe: float = 1.0, background: str | None = None) -> Image.Image:
    """`safe` shrinks the mark inside the canvas — maskable icons get cropped to a
    circle by Android, so the mark must sit inside roughly 80% of the square."""
    s = size * SUPERSAMPLE
    img = Image.new("RGBA", (s, s), background or (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    inset = s * (1 - safe) / 2
    field = [inset, inset, s - inset - 1, s - inset - 1]
    side = s - 2 * inset
    # Two passes: the tight top-left corner is drawn by overlaying a
    # small-radius rectangle, since PIL takes one radius per shape.
    d.rounded_rectangle(field, radius=side * CORNER_RADIUS, fill=palette.BRAND_LIGHT,
                        corners=(False, True, True, True))
    d.rounded_rectangle([field[0], field[1], field[0] + side * 0.5, field[1] + side * 0.5],
                        radius=side * CORNER_RADIUS_TL, fill=palette.BRAND_LIGHT,
                        corners=(True, False, False, False))
    for poly in letter_polygons(s - 2 * inset, inset, inset):
        d.polygon(poly, fill=palette.LIGHT["--brand-contrast"])
    return img.resize((size, size), Image.LANCZOS)


def svg() -> str:
    """The header mark. Uses the brand tokens, so it follows the theme, and needs
    no network request."""
    r = CORNER_RADIUS * 100
    tl = CORNER_RADIUS_TL * 100
    field = (f"M{tl},0 H{100 - r} A{r},{r} 0 0 1 100,{r} V{100 - r} "
             f"A{r},{r} 0 0 1 {100 - r},100 H{r} A{r},{r} 0 0 1 0,{100 - r} "
             f"V{tl} A{tl},{tl} 0 0 1 {tl},0 Z")
    polys = letter_polygons(100.0)
    shapes = "\n    ".join(
        '<polygon points="{}" fill="var(--brand-contrast)"/>'.format(
            " ".join(f"{x:.2f},{y:.2f}" for x, y in poly))
        for poly in polys)
    return (
        '{# Generated by scripts/generate_icons.py — do not edit by hand. #}\n'
        # No width/height here: .mark in base.html sizes it, and three
        # declarations for one glyph is two too many.
        '<svg class="mark" viewBox="0 0 100 100" '
        'aria-hidden="true" focusable="false">\n'
        f'    <path d="{field}" fill="var(--brand)"/>\n'
        f'    {shapes}\n'
        '</svg>\n'
    )


def main():
    os.makedirs(os.path.join(STATIC, "icons"), exist_ok=True)

    with open(os.path.join(TEMPLATES, "_monogram.svg"), "w", encoding="utf-8") as fh:
        fh.write(svg())
    print("wrote templates/_monogram.svg")

    for name, size in (("icons/icon-192.png", 192), ("icons/icon-512.png", 512),
                       ("icons/apple-touch-icon.png", 180)):
        # Apple does not round the corners for you and never renders transparency:
        # that one gets an opaque ground.
        opaque = name.endswith("apple-touch-icon.png")
        img = render(size, background=palette.LIGHT["--surface-1"] if opaque else None)
        img.save(os.path.join(STATIC, name))
        print(f"wrote static/{name}  {size}x{size}")

    # Maskable: Android crops to a circle, so the mark is inset into the safe zone
    # and the ground is filled edge to edge. Declaring the plain icon as maskable
    # (as the manifest used to) gets the mark's corners shaved off.
    for name, size in (("icons/icon-192-maskable.png", 192),
                       ("icons/icon-512-maskable.png", 512)):
        img = render(size, safe=0.78, background=palette.LIGHT["--surface-1"])
        img.save(os.path.join(STATIC, name))
        print(f"wrote static/{name}  {size}x{size} (safe zone 78%)")

    ico = render(64, background=palette.LIGHT["--surface-1"])
    ico.save(os.path.join(STATIC, "favicon.ico"),
             sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("wrote static/favicon.ico  16/32/48/64")


if __name__ == "__main__":
    main()
