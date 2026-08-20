"""Global net worth view: investments + savings/cash accounts, compared to a target allocation.

Data source: data/accounts/accounts.json (accounts, entered by hand) and
config/target_allocation.json (target allocation in %, entered by hand).

Category taxonomy note: CATEGORY_ORDER, DEFAULT_ASSET_CLASS and every category
value handled here are deliberately kept in French (Actions, Obligations, Fonds
Euros, Livrets, Autres). They are the storage key shared with each user's own
private config/asset_classes.json, config/target_allocation.json and
data/accounts/accounts.json — none of which are tracked in Git. Renaming this
taxonomy would silently break anyone's existing local setup. English display
labels live in dashboard/app.py's CATEGORY_LABELS and are applied only when
rendering the templates.
"""
import json
import os
from datetime import datetime

from paths import config_root, data_root

ACCOUNTS_PATH = os.path.join(data_root(), "accounts", "accounts.json")
TARGET_PATH = os.path.join(config_root(), "target_allocation.json")
ASSET_CLASSES_PATH = os.path.join(config_root(), "asset_classes.json")
DEFAULT_ASSET_CLASS = "Actions"
# Fixed order: a category's color must stay the same across reloads, regardless
# of its current weight (see dataviz skill — color follows the entity, never its rank).
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
    """Assembles the net worth view from the investment value (computed elsewhere)
    and the accounts/targets loaded from the config files.

    Accounts marked 'visible: false' (e.g. transient cash) are excluded from every
    total, chart, and table in this view.

    bourse_positions: list of {"asset_key": ..., "value": ...} for open investment
    positions, used to break investments down by asset class (Stocks/Bonds/Other)
    in the comparison against targets — an asset not classified in
    config/asset_classes.json defaults to "Actions" (Stocks).
    """
    bourse_by_broker = bourse_by_broker or {}
    bourse_positions = bourse_positions or []
    accounts = [a for a in load_accounts() if a.get("visible", True)]
    target = load_target_allocation()
    asset_classes = load_asset_classes()

    total = bourse_value + sum(a["balance"] for a in accounts)

    # Comparison against targets: investments are broken down line by line into
    # asset classes (an investment line isn't itself "a category" — it holds
    # stocks, gold, etc.), other accounts keep their own class.
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

    # Breakdown by bank: investment positions split by broker + accounts by bank.
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
