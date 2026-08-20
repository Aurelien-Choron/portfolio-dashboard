"""WSGI entry point for a production server (gunicorn).

dashboard/app.py is a script, not a package module (no __init__.py): its own
sys.path.insert() is enough for its internal imports (market_data,
analytics...), but gunicorn needs a stable import path to find the Flask
object itself. So we add dashboard/ to sys.path here and re-export `app` as is.

Usage: gunicorn wsgi:app
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard"))

from app import app  # noqa: E402
