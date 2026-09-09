"""Reports how much of each Plotly figure is actually plot area, per breakpoint.

    pip install -r requirements-screenshots.txt
    python scripts/chart_metrics.py                # 360 and 1440
    python scripts/chart_metrics.py --widths 360   # just the phone

This is the acceptance test for "the charts are crushed on mobile". A screenshot
shows you that a chart looks wrong; this says by how much and where the width
went, so a fix can be judged instead of admired.

Read `_fullLayout._size`, not `_fullLayout.margin`. `margin` is what the figure
*asked* for; `_size` is what Plotly settled on after `automargin` grew it to fit
tick labels, and the gap between the two is the whole story on a 326px canvas.

Only visible figures are measured. A chart sitting in an inactive tab panel
legitimately reports Plotly's 700px default — it is re-measured on reveal by
initTabs — so including hidden ones invents a bug that is not there.
"""
import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Inherits the PORTFOLIO_ROOT=demo guard, which runs at import time.
from scripts.generate_screenshots import serve  # noqa: E402
from scripts.review_shots import VIEWS  # noqa: E402

# Below these, a figure is spending more on furniture than on data.
MIN_WIDTH_PCT = 70
MIN_HEIGHT_PCT = 60

PROBE = """() => [...document.querySelectorAll('[id^="chart-"]')]
  .filter(el => el._fullLayout && el._fullLayout._size
                && el.offsetParent !== null && el.offsetWidth > 0)
  .map(el => { const fl = el._fullLayout, s = fl._size;
    return {id: el.id, w: Math.round(fl.width), h: Math.round(fl.height),
            l: Math.round(s.l), r: Math.round(s.r), t: Math.round(s.t), b: Math.round(s.b),
            pw: Math.round(s.w), ph: Math.round(s.h),
            pctw: Math.round(100 * s.w / fl.width),
            pcth: Math.round(100 * s.h / fl.height)}; })"""


def measure(page, base, width):
    """Walks every view and tab at `width`, returning one row per figure."""
    rows, seen = [], set()
    for view, path, tabs, setup in VIEWS:
        for tab_slug, tab_id in tabs:
            page.goto(base + path, wait_until="networkidle")
            page.wait_for_timeout(1200)
            if tab_id:
                page.click(f'[data-tab-target="{tab_id}"]')
                page.wait_for_timeout(1000)
            if setup:
                setup(page)
            for c in page.evaluate(PROBE):
                if c["id"] in seen:
                    continue
                seen.add(c["id"])
                rows.append(c)
    return rows


def report(width, rows) -> int:
    print(f"\n=== viewport {width}px ===")
    print(f"{'chart':24s} {'fig':>5s} {'left':>5s} {'right':>5s} {'plotW':>6s} {'W%':>5s}"
          f"  {'top':>4s} {'bot':>4s} {'plotH':>6s} {'H%':>5s}")
    failures = 0
    for c in sorted(rows, key=lambda r: r["pctw"]):
        warn = ""
        if c["pctw"] < MIN_WIDTH_PCT:
            warn += "  <-- WIDTH"
            failures += 1
        if c["pcth"] < MIN_HEIGHT_PCT:
            warn += "  <-- HEIGHT"
            failures += 1
        print(f"{c['id']:24s} {c['w']:5d} {c['l']:5d} {c['r']:5d} {c['pw']:6d} {c['pctw']:4d}%"
              f"  {c['t']:4d} {c['b']:4d} {c['ph']:6d} {c['pcth']:4d}%{warn}")
    return failures


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--widths", default="360,1440", help="comma-separated viewport widths")
    ap.add_argument("--strict", action="store_true",
                    help=f"exit non-zero if any figure is under {MIN_WIDTH_PCT}%% wide "
                         f"or {MIN_HEIGHT_PCT}%% tall")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    base = serve()
    failures = 0
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for width in [int(w) for w in args.widths.split(",") if w.strip()]:
            ctx = browser.new_context(viewport={"width": width, "height": 2400})
            ctx.add_init_script("try { localStorage.setItem('theme','dark'); } catch (e) {}")
            page = ctx.new_page()
            failures += report(width, measure(page, base, width))
            ctx.close()
        browser.close()

    if failures:
        msg = f"\n{failures} figure(s) below threshold"
        if args.strict:
            sys.exit(msg)
        print(msg)


if __name__ == "__main__":
    main()
