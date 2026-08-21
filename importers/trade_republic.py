"""Parser for Trade Republic transaction exports.

Observed format: CSV separated by ',', UTF-8 encoding, quoted fields, one row
per movement (BUY/SELL orders appear as 2 rows: the fractional share then the
whole share, to be summed — distinct transaction_id, same trade).

Useful columns: datetime, date, account_type, category, type, asset_class,
name, symbol (actually the ISIN), shares, price, amount, fee, tax, currency.
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
    """Loads and normalizes every Trade Republic CSV found in data_dir."""
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
    # "amount" must be the actual net cash movement booked to the account.
    # Trade Republic's raw "amount" is gross of withholding tax: on
    # INTEREST_PAYMENT/DIVIDEND rows it's reduced by "tax" before the cash
    # balance is credited (e.g. a 47.16 EUR gross interest payment with 14.79
    # EUR withheld actually credits 32.37 EUR) — nothing downstream (kpis.py,
    # positions.py) ever reads "tax" separately, so it must be netted in here.
    out["amount"] = pd.to_numeric(raw["amount"], errors="coerce") - out["tax"]
    out["currency"] = raw["currency"].str.strip()
    out["raw_operation"] = raw["type"].str.strip()

    return out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def _empty() -> pd.DataFrame:
    # Explicitly typed columns: an untyped empty DataFrame (all object dtype)
    # would degrade the "date" column's dtype on concat with the other sources
    # whenever data/trade_republic/ has no CSV in it.
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
