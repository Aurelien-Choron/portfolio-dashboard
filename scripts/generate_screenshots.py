"""(Re)generates docs/screenshots/ from the fictional demo dataset, in dark mode.

Run it whenever a view changes enough that the README's images stop matching:

    pip install -r requirements-screenshots.txt
    python scripts/generate_screenshots.py

The demo root is forced here, not passed in: these images end up in a public
README, and a screenshot is the easiest way for a real balance to escape a
repository whose .gitignore only ever protected data *files*. The script
refuses to run against anything else rather than trusting the caller's
environment.

Playwright is deliberately kept out of requirements.txt — the Flask app never
imports it, and the deployment has no reason to install a browser.

`serve()`, `capture()` and the viewport constants are shared with
scripts/review_shots.py, which sweeps every view at every breakpoint during UI
work. The demo-root guard above runs on import, so anything reusing this module
inherits it.
"""
import json
import os
import socket
import sys
import threading
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Before importing the app: paths.py reads PORTFOLIO_ROOT at call time, but the
# module-level DATA_ROOT in dashboard/app.py is resolved on import.
_requested = os.environ.get("PORTFOLIO_ROOT", "demo")
if _requested != "demo":
    sys.exit(f"refusing to run against PORTFOLIO_ROOT={_requested!r}: "
             "these screenshots are published, so they may only ever show demo data")
os.environ["PORTFOLIO_ROOT"] = "demo"

from dashboard.app import app  # noqa: E402  (must follow the env var above)

OUT_DIR = os.path.join(REPO_ROOT, "docs", "screenshots")

# Same frames as the images already in the README: a desktop viewport and a
# phone-sized one, captured at 1x. Not full-page — the bottom nav bar is
# position:fixed, and a full-page capture paints it across the middle.
DESKTOP = {"width": 1440, "height": 900}
# The Forecast page gets a taller frame: its goal panel — the reason the page
# exists — sits under the chart, and at 900px the shot would stop at the curve.
# 1370 fits all three of its read-outs.
DESKTOP_TALL = {"width": 1440, "height": 1370}
PHONE = {"width": 420, "height": 909}

# Only review_shots.py uses these two. NARROW is the one that matters: 360px is
# the floor real phones report, and the compact-mobile CSS was written against
# 420. TABLET sits one pixel below the md breakpoint, where the hand-written
# `max-width: 767px` block and Tailwind's `md:` utilities hand over to each other.
NARROW = {"width": 360, "height": 780}
TABLET = {"width": 767, "height": 1024}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve() -> str:
    """Starts the demo app on a free port in a daemon thread; returns its base URL."""
    port = _free_port()
    threading.Thread(target=lambda: app.run(port=port, use_reloader=False),
                     daemon=True).start()
    time.sleep(2.5)
    return f"http://127.0.0.1:{port}"


def _setup_forecast(page) -> None:
    """Puts the Forecast page on a state worth showing.

    25 years at 1 000 €/month against a million: the median lands short of the
    target while the band's upper edge crosses it, so the shot shows what the
    page is actually for — a probability, not a single confident number.
    """
    page.select_option("#pj-scenario", "target")
    page.fill("#pj-monthly", "1000")
    page.eval_on_selector("#pj-horizon", "e => { e.value = 25; e.dispatchEvent(new Event('input')); }")
    # Otherwise the last field keeps its focus ring and the shot looks mid-edit.
    page.eval_on_selector("#pj-monthly", "e => e.blur()")
    page.wait_for_timeout(600)


def capture(shots, out_dir, base, theme="dark") -> list:
    """Renders `shots` into `out_dir`; returns the JS errors seen, if any.

    A shot is (name, path, viewport, setup) with an optional 5th element: the
    id of a tab panel to open before the capture. That element is not a
    convenience — eight of the app's figures are first drawn inside a
    display:none panel, which is precisely where Plotly mis-measures them, so a
    harness that can only photograph the default tab cannot see the bug.
    """
    from playwright.sync_api import sync_playwright

    os.makedirs(out_dir, exist_ok=True)
    errors = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for shot in shots:
            name, path, viewport, setup = shot[:4]
            tab = shot[4] if len(shot) > 4 else None
            context = browser.new_context(viewport=viewport)
            # base.html reads this before the first paint, so the page never
            # flashes the other theme into the capture.
            context.add_init_script(
                "try { localStorage.setItem('theme', %s); } catch (e) {}" % json.dumps(theme))
            page = context.new_page()
            page.on("pageerror", lambda e, n=name: errors.append(f"{n}: {e}"))
            page.goto(base + path, wait_until="networkidle")
            page.wait_for_timeout(1500)  # let Plotly finish drawing
            if tab:
                page.click(f'[data-tab-target="{tab}"]')
                page.wait_for_timeout(900)  # the tab's figures resize on reveal
            if setup:
                setup(page)
            page.screenshot(path=os.path.join(out_dir, name))
            print(f"  {name:34s} {viewport['width']}x{viewport['height']}  {path}")
            context.close()
        browser.close()
    return errors


SHOTS = [
    ("strategy.png", "/strategy", DESKTOP, None),
    ("investments.png", "/", DESKTOP, None),
    ("net-worth.png", "/patrimoine", DESKTOP, None),
    ("forecast.png", "/projection", DESKTOP_TALL, _setup_forecast),
    ("mobile-strategy.png", "/strategy", PHONE, None),
    ("mobile-investments.png", "/", PHONE, None),
    ("mobile-forecast.png", "/projection", PHONE, _setup_forecast),
]


def main() -> None:
    errors = capture(SHOTS, OUT_DIR, serve(), theme="dark")
    if errors:
        sys.exit("JavaScript errors while capturing:\n  " + "\n  ".join(errors))
    print(f"\n{len(SHOTS)} screenshots written to docs/screenshots/ (demo data, dark theme)")


if __name__ == "__main__":
    main()
