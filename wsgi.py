"""Point d'entrée WSGI pour un serveur de production (gunicorn).

dashboard/app.py est un script, pas un module de package (pas de __init__.py) :
son propre sys.path.insert() suffit pour ses imports internes (market_data,
analytics...), mais gunicorn a besoin d'un chemin d'import stable pour trouver
l'objet Flask lui-même. On ajoute donc dashboard/ au sys.path ici et on
réexporte `app` tel quel.

Usage : gunicorn wsgi:app
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard"))

from app import app  # noqa: E402
