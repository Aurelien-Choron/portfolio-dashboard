"""Parser for Fortuneo's "transaction history" exports.

Observed format: CSV separated by ';', Windows-1252 encoding, dot decimals,
DD/MM/YYYY dates, one empty trailing column (trailing ';' at end of line).

Source columns:
libellé;Opération;Place;Date;Qté;Prix d'éxé;Montant brut;Courtage/Prélèvement;Montant net;Devise;
"""

import glob
import os

import pandas as pd

# Fortuneo operation labels -> normalized type.
# These dict keys are the literal French strings Fortuneo's own CSV export uses
# for its "Opération" column — they must stay in French to keep parsing real
# Fortuneo exports, independent of the app's own display language.
# "OST de création de coupons" / "ANNUL." entries are technical bookkeeping
# entries tied to optional coupon detachment: they're kept as type OTHER
# (visible in the activity log) but excluded from dividend/cash-flow totals to
# avoid any double counting, since their exact accounting treatment isn't certain.
OPERATION_MAP = {
    "achat comptant": "BUY",
    "vente comptant": "SELL",
    "encaissement coupons intérêt/dividende": "DIVIDEND",
    "versement": "DEPOSIT",
    "retrait": "WITHDRAWAL",
}


def _map_type(operation: str) -> str:
    op = operation.strip().lower()
    if op in OPERATION_MAP:
        return OPERATION_MAP[op]
    if op.startswith("ost de création de coupons") or op.startswith("annul."):
        return "OTHER"
    return "OTHER"


def load(data_dir: str) -> pd.DataFrame:
    """Loads and normalizes every Fortuneo CSV found in data_dir."""
    files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    if not files:
        return _empty()

    frames = []
    for path in files:
        df = pd.read_csv(path, sep=";", encoding="cp1252", dtype=str)
        df = df.rename(columns=lambda c: c.strip())
        df = df.dropna(axis=1, how="all")  # phantom column from the trailing ';'
        frames.append(df)

    raw = pd.concat(frames, ignore_index=True)
    raw = raw.drop_duplicates()

    out = pd.DataFrame()
    out["date"] = pd.to_datetime(raw["Date"], format="%d/%m/%Y", errors="coerce")
    out["broker"] = "fortuneo"
    out["account"] = "PEA"
    out["type"] = raw["Opération"].apply(_map_type)
    out["name"] = raw["libellé"].str.strip()
    out["isin"] = None
    out["quantity"] = pd.to_numeric(raw["Qté"], errors="coerce")
    out["price"] = pd.to_numeric(raw["Prix d'éxé"], errors="coerce")
    out["fee"] = pd.to_numeric(raw["Courtage/Prélèvement"], errors="coerce").abs()
    out["tax"] = 0.0
    out["amount"] = pd.to_numeric(raw["Montant net"], errors="coerce")
    out["currency"] = raw["Devise"].str.strip()
    out["raw_operation"] = raw["Opération"].str.strip()

    return out.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def _empty() -> pd.DataFrame:
    # Explicitly typed columns: an untyped empty DataFrame (all object dtype)
    # would degrade the "date" column's dtype on concat with the other sources
    # whenever data/fortuneo/ has no CSV in it.
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
