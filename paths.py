"""Centralized resolution of the data/ and config/ directories.

By default, everything points to the data/ and config/ at the repo root (real
data, never version-controlled — see .gitignore). Setting the PORTFOLIO_ROOT
environment variable (used for the public demo deployment) makes the app
switch entirely to another directory with the same layout
(<PORTFOLIO_ROOT>/data, <PORTFOLIO_ROOT>/config) — typically demo/, which only
holds fictional data tracked in Git.
"""
import os

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def project_root() -> str:
    override = os.environ.get("PORTFOLIO_ROOT")
    if not override:
        return _REPO_ROOT
    # A relative override (e.g. "demo") is resolved against the repo root, not
    # the process's current working directory (independent of where the app is launched from).
    return override if os.path.isabs(override) else os.path.join(_REPO_ROOT, override)


def data_root() -> str:
    return os.path.join(project_root(), "data")


def config_root() -> str:
    return os.path.join(project_root(), "config")
