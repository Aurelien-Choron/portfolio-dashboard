"""Combine les imports Fortuneo + Trade Republic en un journal unique normalisé."""

import os

import pandas as pd

from . import corrections, fortuneo, trade_republic

COLUMNS = [
    "date", "broker", "account", "type", "name", "isin",
    "quantity", "price", "fee", "tax", "amount", "currency", "raw_operation",
]


def asset_key(row) -> str:
    """Clé d'agrégation d'un actif : ISIN si connu, sinon nom normalisé."""
    if row.get("isin"):
        return str(row["isin"])
    return str(row.get("name") or "INCONNU").strip()


def load_all(data_root: str) -> pd.DataFrame:
    """Charge, normalise et fusionne toutes les sources CSV disponibles."""
    fortuneo_df = fortuneo.load(os.path.join(data_root, "fortuneo"))
    tr_df = trade_republic.load(os.path.join(data_root, "trade_republic"))
    corrections_df = corrections.load(os.path.join(data_root, "corrections"))

    combined = pd.concat([fortuneo_df, tr_df, corrections_df], ignore_index=True)
    if combined.empty:
        return combined

    combined = combined.sort_values("date").reset_index(drop=True)
    combined["asset_key"] = combined.apply(asset_key, axis=1)
    return combined


def save_processed(df: pd.DataFrame, data_root: str) -> str:
    out_path = os.path.join(data_root, "processed", "transactions.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df.to_csv(out_path, index=False)
    return out_path
