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

from analytics import strategy as strategy_mod
from paths import config_root, data_root

ACCOUNTS_PATH = os.path.join(data_root(), "accounts", "accounts.json")
TARGET_PATH = os.path.join(config_root(), "target_allocation.json")
ASSET_CLASSES_PATH = os.path.join(config_root(), "asset_classes.json")
DEFAULT_ASSET_CLASS = "Actions"
# Display-only category for the investment envelopes listed in the account table.
# Deliberately NOT part of CATEGORY_ORDER: it is not an asset class, and the
# comparison against targets still splits those positions line by line.
INVESTMENT_CATEGORY = "__INVESTMENTS__"
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
    """Target allocation per asset class, in % of total net worth.

    When a strategic allocation exists (config/strategy.json), its per-line
    targets are rolled up to asset classes and win: they are the single source of
    truth, so this page can never contradict the Strategy page. Otherwise the
    hand-written config/target_allocation.json is used, unchanged.
    """
    policy = strategy_mod.load_policy()
    if policy:
        derived = strategy_mod.class_targets(policy)
        if derived:
            return derived

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


def build_investment_accounts(bourse_by_broker: dict, broker_labels: dict | None = None) -> list:
    """The investment envelopes, seen as accounts — because a PEA is an account.

    bourse_by_broker: {raw broker code: market value} for open positions.

    The account table used to stop at savings, which meant the reader had to add
    two pages together to get their own total. The individual *positions* still
    belong on the Investments page; what belongs here is the envelope, what it is
    worth, and — for the PEA — how much of the contribution ceiling is gone,
    which is the constraint that actually binds the strategy.

    Grouped by tax envelope when config/strategy.json defines one (several
    brokers can feed the same envelope), by broker otherwise.
    """
    broker_labels = broker_labels or {}
    policy = strategy_mod.load_policy() or {}
    broker_env = {k: v for k, v in (policy.get("broker_envelopes") or {}).items()
                  if not k.startswith("_")}
    envelopes = policy.get("envelopes") or {}

    grouped = {}
    for broker, value in bourse_by_broker.items():
        if value <= 0:
            continue
        key = broker_env.get(broker) or broker
        row = grouped.setdefault(key, {"value": 0.0, "brokers": []})
        row["value"] += value
        row["brokers"].append(broker_labels.get(broker, broker))

    rows = []
    for key, row in grouped.items():
        env = envelopes.get(key) or {}
        ceiling = env.get("ceiling_eur")
        contributed = env.get("contributed_eur")
        # A PEA's ceiling caps what you PAY IN, not what the account is worth —
        # showing value/ceiling would quietly overstate the room left, so the
        # ratio is built from contributions and says so.
        ceiling_label = None
        if ceiling and contributed is not None:
            ceiling_label = (f"{contributed:,.0f} € paid in of {ceiling:,.0f} €"
                             .replace(",", " "))
        rows.append({
            "id": f"envelope_{key.lower()}",
            "label": key,
            "bank": " · ".join(dict.fromkeys(row["brokers"])),
            "category": INVESTMENT_CATEGORY,
            "balance": row["value"],
            "rate_pct": None,
            "ceiling": ceiling,
            "ceiling_pct": (contributed / ceiling * 100) if (ceiling and contributed) else None,
            "ceiling_label": ceiling_label,
            "maturity_date_fr": None,
            "is_investment": True,
        })
    return sorted(rows, key=lambda r: -r["balance"])


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
