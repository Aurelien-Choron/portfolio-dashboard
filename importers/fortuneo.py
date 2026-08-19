"""Parseur pour les exports 'Historique des opérations' de Fortuneo.

Format observé : CSV séparé par ';', encodage Windows-1252, décimales en point,
dates DD/MM/YYYY, une colonne finale vide (';' de fin de ligne).

Colonnes sources :
libellé;Opération;Place;Date;Qté;Prix d'éxé;Montant brut;Courtage/Prélèvement;Montant net;Devise;
"""

import glob
import os

import pandas as pd

# Libellés d'opération Fortuneo -> type normalisé.
# Les opérations "OST de création de coupons" / "ANNUL." sont des écritures
# techniques liées au détachement de coupons optionnels : elles sont gardées
# en type OTHER (visibles dans le journal) mais exclues des totaux de
# dividendes/cash-flow pour éviter tout double comptage, faute de certitude
# sur leur traitement comptable exact.
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
    """Charge et normalise tous les CSV Fortuneo présents dans data_dir."""
    files = sorted(glob.glob(os.path.join(data_dir, "*.csv")))
    if not files:
        return _empty()

    frames = []
    for path in files:
        df = pd.read_csv(path, sep=";", encoding="cp1252", dtype=str)
        df = df.rename(columns=lambda c: c.strip())
        df = df.dropna(axis=1, how="all")  # colonne fantôme du ';' final
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
    # Colonnes explicitement typées : un DataFrame vide non typé (tout en object)
    # dégraderait le dtype de "date" au concat avec les autres sources dès que
    # data/fortuneo/ ne contient aucun CSV.
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
