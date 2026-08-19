"""Parseur pour les exports de transactions Trade Republic.

Format observé : CSV séparé par ',', encodage UTF-8, champs entre guillemets,
une ligne par mouvement (les ordres BUY/SELL apparaissent en 2 lignes :
la part fractionnée puis la part entière, à additionner par transaction_id
distincts mais même trade).

Colonnes utiles : datetime, date, account_type, category, type, asset_class,
name, symbol (en réalité l'ISIN), shares, price, amount, fee, tax, currency.
"""

import glob
import os

import pandas as pd

TYPE_MAP = {
    "BUY": "BUY",
    "SELL": "SELL",
    "DIVIDEND": "DIVIDEND",
    "INTEREST_PAYMENT": "INTEREST",
    "TRANSFER_INBOUND": "DEPOSIT",
    "TRANSFER_INSTANT_INBOUND": "DEPOSIT",
    "TRANSFER_OUTBOUND": "WITHDRAWAL",
    "TRANSFER_INSTANT_OUTBOUND": "WITHDRAWAL",
}


def _map_type(row_type: str) -> str:
    return TYPE_MAP.get(row_type, "OTHER")


def load(data_dir: str) -> pd.DataFrame:
    """Charge et normalise tous les CSV Trade Republic présents dans data_dir."""
    files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    if not files:
        return _empty()

    frames = [pd.read_csv(path, dtype=str) for path in files]
    raw = pd.concat(frames, ignore_index=True)
    if "transaction_id" in raw.columns:
        raw = raw.drop_duplicates(subset=["transaction_id"])
    else:
        raw = raw.drop_duplicates()

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(raw["date"], errors="coerce")
    out["broker"] = "trade_republic"
    out["account"] = raw.get("account_type", "DEFAULT")
    out["type"] = raw["type"].apply(_map_type)
    out["name"] = raw["name"].where(raw["name"].notna() & (raw["name"] != ""), None)
    out["isin"] = raw["symbol"].where(raw["symbol"].notna() & (raw["symbol"] != ""), None)
    out["quantity"] = pd.to_numeric(raw["shares"], errors="coerce")
    out["price"] = pd.to_numeric(raw["price"], errors="coerce")
    out["fee"] = pd.to_numeric(raw["fee"], errors="coerce").abs().fillna(0.0)
    out["tax"] = pd.to_numeric(raw["tax"], errors="coerce").abs().fillna(0.0)
    out["amount"] = pd.to_numeric(raw["amount"], errors="coerce")
    out["currency"] = raw["currency"].str.strip()
    out["raw_operation"] = raw["type"].str.strip()

    return out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def _empty() -> pd.DataFrame:
    # Colonnes explicitement typées : un DataFrame vide non typé (tout en object)
    # dégraderait le dtype de "date" au concat avec les autres sources dès que
    # data/trade_republic/ ne contient aucun CSV.
    columns = [
        "date", "broker", "account", "type", "name", "isin",
        "quantity", "price", "fee", "tax", "amount", "currency", "raw_operation",
    ]
    dtypes = {
        "date": "datetime64[ns]",
        "quantity": "float64", "price": "float64", "fee": "float64",
        "tax": "float64", "amount": "float64",
    }
    return pd.DataFrame({c: pd.Series(dtype=dtypes.get(c, "object")) for c in columns})
