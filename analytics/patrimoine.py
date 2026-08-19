"""Vue patrimoine global : bourse + comptes d'épargne/cash, comparés à une répartition cible.

Source de données : data/accounts/accounts.json (comptes, saisis à la main) et
config/target_allocation.json (répartition cible en %, saisie à la main).
"""
import json
import os
from datetime import datetime

from paths import config_root, data_root

ACCOUNTS_PATH = os.path.join(data_root(), "accounts", "accounts.json")
TARGET_PATH = os.path.join(config_root(), "target_allocation.json")
ASSET_CLASSES_PATH = os.path.join(config_root(), "asset_classes.json")
DEFAULT_ASSET_CLASS = "Actions"
# Ordre fixe : la couleur d'une catégorie doit rester la même d'un chargement à l'autre,
# indépendamment de son poids actuel (voir dataviz skill — la couleur suit l'entité, jamais son rang).
CATEGORY_ORDER = ["Actions", "Obligations", "Fonds Euros", "Livrets", "Autres"]


def _category_sort_key(category: str) -> tuple:
    try:
        return (0, CATEGORY_ORDER.index(category))
    except ValueError:
        return (1, category)


def _fmt_date_fr(iso_date):
    if not iso_date:
        return None
    return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%d/%m/%Y")


def load_accounts() -> list:
    if not os.path.exists(ACCOUNTS_PATH):
        return []
    with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    accounts = []
    for a in data.get("accounts", []):
        a = dict(a)
        a.setdefault("rate_pct", None)
        ceiling = a.get("ceiling")
        a["ceiling_pct"] = (a["balance"] / ceiling * 100) if ceiling else None
        a["maturity_date_fr"] = _fmt_date_fr(a.get("maturity_date"))
        accounts.append(a)
    return accounts


def load_target_allocation() -> dict:
    if not os.path.exists(TARGET_PATH):
        return {}
    with open(TARGET_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def load_asset_classes() -> dict:
    if not os.path.exists(ASSET_CLASSES_PATH):
        return {}
    with open(ASSET_CLASSES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def build_patrimoine(
    bourse_value: float,
    bourse_by_broker: dict | None = None,
    bourse_positions: list | None = None,
) -> dict:
    """Assemble la vue patrimoine à partir de la valeur bourse (calculée par ailleurs)
    et des comptes/cibles chargés depuis les fichiers de config.

    Les comptes marqués 'visible: false' (ex. cash de passage) sont exclus de tous
    les totaux, graphiques et tableaux de cette vue.

    bourse_positions : liste de {"asset_key": ..., "value": ...} pour les positions bourse
    ouvertes, utilisée pour ventiler la bourse par classe d'actif (Actions/Obligations/Autres)
    dans la comparaison aux cibles — un actif non classé dans config/asset_classes.json est
    compté comme "Actions" par défaut.
    """
    bourse_by_broker = bourse_by_broker or {}
    bourse_positions = bourse_positions or []
    accounts = [a for a in load_accounts() if a.get("visible", True)]
    target = load_target_allocation()
    asset_classes = load_asset_classes()

    total = bourse_value + sum(a["balance"] for a in accounts)

    # Comparaison aux cibles : la bourse est éclatée ligne par ligne en classes d'actif
    # (une ligne Bourse n'est pas "une catégorie", elle contient des actions, de l'or, etc.),
    # les comptes hors bourse gardent leur propre classe.
    class_totals = {}
    for p in bourse_positions:
        cls = asset_classes.get(p["asset_key"], DEFAULT_ASSET_CLASS)
        class_totals[cls] = class_totals.get(cls, 0.0) + p["value"]
    for a in accounts:
        class_totals[a["category"]] = class_totals.get(a["category"], 0.0) + a["balance"]

    categories = list(dict.fromkeys(list(class_totals) + list(target)))
    comparison = []
    for cat in categories:
        actual_value = class_totals.get(cat, 0.0)
        actual_pct = (actual_value / total * 100) if total else 0.0
        target_pct = target.get(cat)
        gap_pct = (actual_pct - target_pct) if target_pct is not None else None
        comparison.append({
            "category": cat,
            "value": actual_value,
            "actual_pct": actual_pct,
            "target_pct": target_pct,
            "gap_pct": gap_pct,
        })
    comparison.sort(key=lambda c: _category_sort_key(c["category"]))
    by_category = {c["category"]: c for c in comparison}

    # Répartition par banque : positions bourse ventilées par courtier + comptes par banque.
    bank_totals = {}
    for bank, value in bourse_by_broker.items():
        bank_totals[bank] = bank_totals.get(bank, 0.0) + value
    for a in accounts:
        bank = a.get("bank")
        if bank:
            bank_totals[bank] = bank_totals.get(bank, 0.0) + a["balance"]
    bank_slices = sorted(
        ({"label": bank, "value": value} for bank, value in bank_totals.items() if value > 0),
        key=lambda s: -s["value"],
    )

    epargne_total = sum(a["balance"] for a in accounts)

    return {
        "accounts": accounts,
        "bank_slices": bank_slices,
        "total": total,
        "comparison": comparison,
        "by_category": by_category,
        "bourse_value": bourse_value,
        "epargne_total": epargne_total,
    }
