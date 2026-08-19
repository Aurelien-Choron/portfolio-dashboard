"""Diversification géographique et sectorielle des positions bourse.

yfinance ne donne pas le "look-through" d'un ETF (juste son pays de domiciliation
légal, inexploitable pour la répartition réelle) : la ventilation vient donc d'un
mapping saisi à la main dans config/exposure.json, relevé sur la fiche factsheet de
chaque fonds.
"""
import json
import os

from paths import config_root

EXPOSURE_PATH = os.path.join(config_root(), "exposure.json")
DIMENSIONS = ("country", "sector")


def load_exposure() -> dict:
    if not os.path.exists(EXPOSURE_PATH):
        return {}
    with open(EXPOSURE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def build_diversification(positions: list) -> dict:
    """positions : liste de {"asset_key", "name", "value"} (positions ouvertes).

    Retourne la ventilation agrégée du portefeuille par pays et par secteur (clé
    "portfolio", en €), et le détail ligne par ligne (clé "funds") pour la vue par
    fonds. Une position absente de config/exposure.json tombe sous "Non renseigné"
    plutôt que de disparaître silencieusement du total.
    """
    exposure = load_exposure()

    portfolio = {dim: {} for dim in DIMENSIONS}
    funds = []
    for p in positions:
        entry = exposure.get(p["asset_key"], {})
        fund = {"asset_key": p["asset_key"], "name": p["name"], "value": p["value"]}
        for dim in DIMENSIONS:
            breakdown = entry.get(dim) or {}
            fund[dim] = (
                {label: p["value"] * pct / 100 for label, pct in breakdown.items()}
                if breakdown
                else {"Non renseigné": p["value"]}
            )
            for label, value in fund[dim].items():
                portfolio[dim][label] = portfolio[dim].get(label, 0.0) + value
        funds.append(fund)

    return {"portfolio": portfolio, "funds": funds}
