"""Compiles dashboard/static/app.css from the templates' utility classes.

    python scripts/build_css.py

Run it after adding, renaming or removing a Tailwind utility class in any
template — the build only ships the classes it can find, so a class added
without a rebuild silently does nothing.

Why a build at all: the app used to load cdn.tailwindcss.com, which ships a
compiler to every visitor, prints a "should not be used in production" warning
to the console, and takes the entire layout with it if the CDN is unreachable.

Node is only needed here, never at runtime and never on the deployment. The
version is pinned so two machines produce the same stylesheet; npx caches the
download, so there is no node_modules in the repo.
"""
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAILWIND = "tailwindcss@3.4.17"
OUT = os.path.join("dashboard", "static", "app.css")


def main() -> None:
    npx = shutil.which("npx")
    if not npx:
        sys.exit("npx not found — install Node.js to rebuild the stylesheet. "
                 "The committed dashboard/static/app.css stays valid until a "
                 "template gains a utility class that is not already in it.")

    cmd = [npx, "--yes", TAILWIND,
           "-c", "tailwind.config.js",
           "-i", os.path.join("scripts", "tailwind.css"),
           "-o", OUT,
           "--minify"]
    print(" ".join(cmd))
    result = subprocess.run(cmd, cwd=REPO_ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)

    size = os.path.getsize(os.path.join(REPO_ROOT, OUT))
    print(f"\n{OUT}  {size / 1024:.1f} KB")


if __name__ == "__main__":
    main()
