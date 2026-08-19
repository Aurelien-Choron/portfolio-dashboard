"""Charge des transactions correctives manuelles (data/corrections/*.csv).

Sert à compenser un historique de courtier incomplet : quand l'utilisateur connaît
la valeur actuelle réelle d'une position mais que l'export CSV du courtier ne
contient pas tous les achats, on ajoute ici un achat correctif daté du jour où
l'écart a été constaté, au prix du marché de ce jour-là. Le coût d'acquisition de
ce correctif est donc égal à sa valeur de marché au moment de la correction (P&L
latent nul sur cette portion) : on ne invente pas de plus/moins-value, seulement
la quantité manquante.

Format des CSV (colonnes déjà normalisées, pas de transformation à faire) :
date;asset_key;quantity;price;amount;note
- asset_key : ISIN (Trade Republic) ou nom exact de l'actif (Fortuneo), comme dans
  config/tickers.json.
- amount : toujours négatif (sortie de cash), = -(quantity * price).

À supprimer (ou vider) dès qu'un historique complet du courtier est importé.
"""

import glob
import os

import pandas as pd

COLUMNS = [
    "date", "broker", "account", "type", "name", "isin",
    "quantity", "price", "fee", "tax", "amount", "currency", "raw_operation",
]


def load(data_dir: str) -> pd.DataFrame:
    files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    if not files:
        return _empty()

    frames = [pd.read_csv(path, sep=";", dtype=str) for path in files]
    raw = pd.concat(frames, ignore_index=True)

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(raw["date"], errors="coerce")
    out["broker"] = "correction_manuelle"
    out["account"] = "PEA"
    out["type"] = "BUY"
    out["name"] = raw["asset_key"]
    out["isin"] = None
    out["quantity"] = pd.to_numeric(raw["quantity"], errors="coerce")
    out["price"] = pd.to_numeric(raw["price"], errors="coerce")
    out["fee"] = 0.0
    out["tax"] = 0.0
    out["amount"] = pd.to_numeric(raw["amount"], errors="coerce")
    out["currency"] = "EUR"
    out["raw_operation"] = raw["note"]

    return out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def _empty() -> pd.DataFrame:
    # Colonnes explicitement typées : un DataFrame vide non typé (tout en object)
    # dégraderait le dtype de "date" au concat avec les autres sources dès que
    # data/corrections/ ne contient aucun fichier (cas normal la plupart du temps).
    dtypes = {
        "date": "datetime64[ns]",
        "quantity": "float64", "price": "float64", "fee": "float64",
        "tax": "float64", "amount": "float64",
    }
    return pd.DataFrame({c: pd.Series(dtype=dtypes.get(c, "object")) for c in COLUMNS})
