"""Loads manual correction transactions (data/corrections/*.csv).

Used to compensate for an incomplete broker history: when the user knows a
position's real current value but the broker's CSV export doesn't include every
purchase, a corrective buy is added here, dated the day the gap was noticed, at
that day's market price. This correction's acquisition cost therefore equals its
market value at the time of correction (zero unrealized P&L on that portion) — no
gain/loss is invented, only the missing quantity.

CSV format (columns already normalized, no transformation needed):
date;asset_key;quantity;price;amount;note
- asset_key: ISIN (Trade Republic) or exact asset name (Fortuneo), as in
  config/tickers.json.
- amount: always negative (cash outflow), = -(quantity * price).

Delete (or empty) this once a complete broker history has been imported.
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
    # Explicitly typed columns: an untyped empty DataFrame (all object dtype)
    # would degrade the "date" column's dtype on concat with the other sources
    # whenever data/corrections/ has no file in it (the normal case, most of the time).
    dtypes = {
        "date": "datetime64[ns]",
        "quantity": "float64", "price": "float64", "fee": "float64",
        "tax": "float64", "amount": "float64",
    }
    return pd.DataFrame({c: pd.Series(dtype=dtypes.get(c, "object")) for c in COLUMNS})
