"""Résolution centralisée des dossiers data/ et config/.

Par défaut, tout pointe vers le data/ et le config/ à la racine du repo (données
réelles, jamais versionnées — voir .gitignore). En définissant la variable
d'environnement PORTFOLIO_ROOT (utilisé pour le déploiement de démo publique),
l'app bascule entièrement sur un autre dossier ayant la même structure
(<PORTFOLIO_ROOT>/data, <PORTFOLIO_ROOT>/config) — typiquement demo/, qui ne
contient que des données fictives versionnées dans Git.
"""
import os

_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))


def project_root() -> str:
    override = os.environ.get("PORTFOLIO_ROOT")
    if not override:
        return _REPO_ROOT
    # Un override relatif (ex. "demo") est résolu par rapport à la racine du repo,
    # pas au répertoire courant du process (indépendant de l'endroit d'où l'app est lancée).
    return override if os.path.isabs(override) else os.path.join(_REPO_ROOT, override)


def data_root() -> str:
    return os.path.join(project_root(), "data")


def config_root() -> str:
    return os.path.join(project_root(), "config")
