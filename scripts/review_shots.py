"""Sweeps every view, every tab and every breakpoint into .review-shots/.

This is the UI-work harness, not the README publisher — for that, see
scripts/generate_screenshots.py, whose machinery this reuses (including its
refusal to run against anything but the demo dataset).

    pip install -r requirements-screenshots.txt
    python scripts/review_shots.py --label baseline
    ... change something ...
    python scripts/review_shots.py --label after
    python scripts/review_shots.py --diff baseline after

Why it exists: the published screenshots only ever photograph a view's *default*
tab, and eight of the app's thirteen figures live behind a tab that is
display:none on load — exactly where Plotly mis-measures its width. A harness
that cannot open a tab cannot see the bug it is meant to catch.

The output directory is gitignored: these are working images, not deliverables.
"""
import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Inherits the PORTFOLIO_ROOT=demo guard, which runs at import time.
from scripts.generate_screenshots import _setup_forecast, capture, serve  # noqa: E402

OUT_ROOT = os.path.join(REPO_ROOT, ".review-shots")

# 360 is the floor real phones report; 420 is what the compact-mobile CSS was
# written against; 767 is one pixel below the md breakpoint, where the
# hand-written media block hands over to Tailwind's utilities; 1440 is desktop.
# Deliberately tall: these frames exist to be read, and a phone-height frame
# stops above the charts, which are the whole point of the sweep. A tall
# viewport is used rather than a full-page capture because the bottom nav is
# position:fixed and full_page paints it across the middle of the image.
HEIGHTS = {360: 2400, 420: 2400, 767: 2200, 1440: 1600}

# (slug, path, [(tab slug, tab panel id or None for the one already active)], setup)
VIEWS = [
    ("investments", "/", [
        ("performance", None),
        ("allocation", "tab-allocation"),
        ("costs", "tab-costs"),
        ("diversification", "tab-diversification"),
        ("activity", "tab-activity"),
    ], None),
    # No tabs any more: a 169-line page hiding half of itself behind a click.
    ("net-worth", "/patrimoine", [("main", None)], None),
    ("strategy", "/strategy", [
        ("plan", None),
        ("target", "tab-target"),
        ("risk", "tab-risk"),
    ], None),
    # No tabs, and it must keep it: every control drives every element through
    # one render(), so hiding the curve from its controls would break the page.
    ("forecast", "/projection", [("main", None)], _setup_forecast),
]


def build_shots(widths):
    shots = []
    for width in widths:
        for view, path, tabs, setup in VIEWS:
            height = HEIGHTS.get(width, 900)
            # The Forecast goal panel sits under the curve; at 900 the desktop
            # frame stops before the read-outs that are the point of the page.
            if view == "forecast" and width >= 1024:
                height = 2400
            viewport = {"width": width, "height": height}
            for tab_slug, tab_id in tabs:
                name = f"{width:04d}-{view}-{tab_slug}.png"
                shots.append((name, path, viewport, setup, tab_id))
    return shots


def _frames(root):
    """Every .png under `root`, keyed by its path relative to it.

    Relative rather than flat: a two-theme sweep nests its frames under
    dark/ and light/, and a diff that only listed the top level would
    compare nothing and report success.
    """
    found = set()
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.endswith(".png"):
                found.add(os.path.relpath(os.path.join(dirpath, name), root))
    return found


def run_diff(label_a, label_b, threshold=0.2):
    """Reports which frames changed between two labelled sweeps, by pixels.

    Bytes are useless here: every page prints pd.Timestamp.now() into its
    header (app.py:961 and friends), so two sweeps a minute apart differ in
    all 44 frames and a byte diff reports total change every time.

    So: count differing pixels and show the box that contains them. A frame
    under `threshold` percent is reported as clock noise, and the box says
    whether a real change is the header strip or the whole layout.
    """
    from PIL import Image, ImageChops

    dir_a, dir_b = os.path.join(OUT_ROOT, label_a), os.path.join(OUT_ROOT, label_b)
    for d in (dir_a, dir_b):
        if not os.path.isdir(d):
            sys.exit(f"no such sweep: {d}")

    names_a, names_b = _frames(dir_a), _frames(dir_b)
    if not names_a and not names_b:
        sys.exit("both sweeps are empty - nothing to compare")

    changed, quiet = [], 0
    for name in sorted(names_a & names_b):
        ia = Image.open(os.path.join(dir_a, name)).convert("RGB")
        ib = Image.open(os.path.join(dir_b, name)).convert("RGB")
        if ia.size != ib.size:
            changed.append((name, 100.0, f"size {ia.size} -> {ib.size}"))
            continue
        diff = ImageChops.difference(ia, ib).convert("L")
        box = diff.getbbox()
        if box is None:
            quiet += 1
            continue
        hits = sum(n for px, n in diff.getcolors(maxcolors=256) if px > 8)
        pct = 100.0 * hits / (ia.width * ia.height)
        if pct < threshold:
            quiet += 1
        else:
            changed.append((name, pct, f"box {box[0]},{box[1]} -> {box[2]},{box[3]}"))

    for name in sorted(names_a - names_b):
        print(f"  gone     {name}")
    for name in sorted(names_b - names_a):
        print(f"  new      {name}")
    for name, pct, note in sorted(changed, key=lambda r: -r[1]):
        print(f"  CHANGED  {name:44s} {pct:6.2f}%  {note}")

    print("")
    print(f"{len(changed)} changed, {quiet} unchanged (within {threshold}%), "
          f"{len(names_a - names_b)} gone, {len(names_b - names_a)} new")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", default="current",
                    help="subdirectory of .review-shots/ to write into (default: current)")
    ap.add_argument("--widths", default="360,1440",
                    help="comma-separated viewport widths (default: 360,1440; "
                         "the full ladder is 360,420,767,1440)")
    ap.add_argument("--themes", default="dark",
                    help="comma-separated themes: dark, light (default: dark)")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"),
                    help="compare two existing sweeps instead of capturing")
    args = ap.parse_args()

    if args.diff:
        run_diff(*args.diff)
        return

    widths = [int(w) for w in args.widths.split(",") if w.strip()]
    themes = [t.strip() for t in args.themes.split(",") if t.strip()]
    shots = build_shots(widths)

    base = serve()
    errors = []
    for theme in themes:
        out_dir = os.path.join(OUT_ROOT, args.label, theme) if len(themes) > 1 \
            else os.path.join(OUT_ROOT, args.label)
        print(f"\n{theme} theme -> {os.path.relpath(out_dir, REPO_ROOT)}")
        errors += capture(shots, out_dir, base, theme=theme)

    if errors:
        sys.exit("JavaScript errors while capturing:\n  " + "\n  ".join(errors))
    print(f"\n{len(shots) * len(themes)} frames written under "
          f".review-shots/{args.label}/ (demo data)")


if __name__ == "__main__":
    main()
