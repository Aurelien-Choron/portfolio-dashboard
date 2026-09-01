"""Strategic allocation: target vs actual, envelope routing, and the action plan.

Two files back this view, deliberately kept apart so that recomputing never
overwrites a decision:

- config/strategy.json           the policy — hand-edited targets, bands,
                                 envelopes, funding order. Never written by code.
- config/strategy_analytics.json the measured risk figures (volatility, beta,
                                 correlations, efficient frontier, stress tests),
                                 produced by scripts/build_strategy.py.

Everything here is a pure function of those files plus the live positions, so the
page always reflects today's prices without re-running the optimiser.

Taxonomy note: asset classes stay in French (Actions, Obligations, Fonds Euros,
Livrets, Autres) — the same storage key shared with config/asset_classes.json,
config/target_allocation.json and data/accounts/accounts.json. See
analytics/patrimoine.py for the full rationale.
"""
import json
import os
import re
from datetime import date, datetime

from paths import config_root

POLICY_PATH = os.path.join(config_root(), "strategy.json")
ANALYTICS_PATH = os.path.join(config_root(), "strategy_analytics.json")

CASH_KEY = "__CASH__"
# A target line is "on band" while its drift stays inside ±band_pt. Exit lines
# (target 0) are over as soon as anything is left, hence the tiny epsilon.
EPSILON_EUR = 1.0


def _strip_readme(d: dict) -> dict:
    """Drops the documentation key, and only it.

    The other config loaders drop every key starting with '_', but here that
    convention collides with the '__CASH__'-style sentinels used for
    lines that have no broker asset_key yet — a blanket filter silently swallowed
    their valuation tilts and stress shocks.
    """
    return {k: v for k, v in d.items() if k != "_readme"}


def load_policy() -> dict | None:
    """The hand-edited strategy, or None when no strategy has been defined yet."""
    if not os.path.exists(POLICY_PATH):
        return None
    with open(POLICY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def load_analytics() -> dict | None:
    """Risk figures from scripts/build_strategy.py, or None if never generated.

    Returning None is a normal state, not an error: the Target and Action plan
    tabs work without it, only the Risk tab needs it.
    """
    if not os.path.exists(ANALYTICS_PATH):
        return None
    with open(ANALYTICS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def class_targets(policy: dict) -> dict:
    """Per-asset-class rollup of the line targets, in % of total net worth.

    This is what makes the strategy the single source of truth: the Net Worth
    page compares against these rather than a separately maintained file.
    """
    out = {}
    for t in policy.get("targets", []):
        cls = t.get("asset_class")
        if not cls:
            continue
        out[cls] = out.get(cls, 0.0) + float(t.get("target_pct") or 0.0)
    sleeve = policy.get("trading_sleeve") or {}
    if sleeve.get("cap_pct"):
        cls = sleeve.get("asset_class", "Actions")
        out[cls] = out.get(cls, 0.0) + float(sleeve["cap_pct"])
    return {k: v for k, v in out.items() if v > 0}


def _match_keys(target: dict) -> set:
    return {target["key"], *(target.get("aliases") or [])}


def _band_status(drift_pt: float, band_pt: float) -> str:
    if drift_pt > band_pt:
        return "over"
    if drift_pt < -band_pt:
        return "under"
    return "on"


def build_targets(policy: dict, positions: list, cash_total: float, total: float) -> list:
    """One row per target line: target, actual, drift, and band status.

    positions: [{"asset_key", "name", "value", "broker"}] for open positions.
    cash_total: total of the visible savings accounts (the __CASH__ line).
    """
    sleeve_members = set((policy.get("trading_sleeve") or {}).get("members") or [])
    rows = []
    for t in policy.get("targets", []):
        keys = _match_keys(t)
        if t["key"] == CASH_KEY:
            current = cash_total
            held = []
        else:
            held = [p for p in positions if p["asset_key"] in keys]
            current = sum(p["value"] for p in held)

        target_pct = float(t.get("target_pct") or 0.0)
        target_eur = target_pct / 100 * total
        current_pct = (current / total * 100) if total else 0.0
        drift_pt = current_pct - target_pct
        band = float(t.get("band_pt") or 0.0)
        status = "over" if (band == 0 and current > EPSILON_EUR) else _band_status(drift_pt, band)

        rows.append({
            "key": t["key"],
            "label": t.get("label", t["key"]),
            "ticker": t.get("ticker"),
            "envelope": t.get("envelope"),
            "asset_class": t.get("asset_class"),
            "role": t.get("role", "core"),
            "note": t.get("note"),
            # The fund actually to buy for this line, with its ISIN. Kept in the
            # policy rather than derived: picking a product is a decision.
            "instrument": t.get("instrument"),
            "held_names": [p["name"] for p in held],
            "target_pct": target_pct,
            "target_eur": target_eur,
            "current_eur": current,
            "current_pct": current_pct,
            "drift_eur": current - target_eur,
            "drift_pt": drift_pt,
            "band_pt": band,
            "status": status,
            "is_cash": t["key"] == CASH_KEY,
        })

    # A held line that no target claims (and that isn't a trading position) is a
    # gap in the policy, not something to hide: surface it so it gets a decision.
    claimed = {k for t in policy.get("targets", []) for k in _match_keys(t)}
    for p in positions:
        if p["asset_key"] in claimed or p["asset_key"] in sleeve_members:
            continue
        rows.append({
            "key": p["asset_key"], "label": p["name"], "ticker": None,
            "envelope": None, "asset_class": None, "role": "unassigned", "note": None,
            "held_names": [p["name"]],
            "target_pct": 0.0, "target_eur": 0.0,
            "current_eur": p["value"], "current_pct": (p["value"] / total * 100) if total else 0.0,
            "drift_eur": p["value"], "drift_pt": (p["value"] / total * 100) if total else 0.0,
            "band_pt": 0.0, "status": "over", "is_cash": False,
        })
    return rows


def build_sleeve(policy: dict, positions: list, total: float) -> dict:
    """The trading sleeve: a budget with a ceiling, never a target to reach.

    Reports usage and headroom. It deliberately never produces a "buy more"
    action — the point of the cap is that going under it is fine.
    """
    sleeve = policy.get("trading_sleeve") or {}
    members = set(sleeve.get("members") or [])
    held = [p for p in positions if p["asset_key"] in members]
    used = sum(p["value"] for p in held)
    cap_pct = float(sleeve.get("cap_pct") or 0.0)
    cap_eur = cap_pct / 100 * total
    return {
        "cap_pct": cap_pct,
        "cap_eur": cap_eur,
        "used_eur": used,
        "used_pct": (used / total * 100) if total else 0.0,
        "headroom_eur": cap_eur - used,
        "over_eur": max(0.0, used - cap_eur),
        "usage_ratio": (used / cap_eur * 100) if cap_eur else 0.0,
        "preferred_envelope": sleeve.get("preferred_envelope"),
        "positions": sorted(held, key=lambda p: -p["value"]),
        "note": sleeve.get("_readme"),
    }


def build_envelopes(policy: dict, positions: list, targets: list, cash_total: float = 0.0) -> list:
    """Capacity and routing per envelope, PEA ceiling included.

    The binding constraint here: equities targeted at the PEA can exceed what the
    150 000 € contribution ceiling still allows, and the excess has to be routed
    to life insurance rather than silently landing on a 30 %-taxed account.
    """
    broker_env = _strip_readme(policy.get("broker_envelopes") or {})
    envelopes = policy.get("envelopes") or {}

    held_by_env = {}
    for p in positions:
        env = broker_env.get(p["broker"])
        if env:
            held_by_env[env] = held_by_env.get(env, 0.0) + p["value"]
    # Savings accounts are not positions, so they have to be attributed explicitly
    # — otherwise the envelope carrying the whole defensive sleeve reads as empty.
    cash_env = next((name for name, e in envelopes.items() if e.get("ceiling_eur") is None
                     and e.get("tax_pct") is None), None)
    if cash_env:
        held_by_env[cash_env] = held_by_env.get(cash_env, 0.0) + cash_total

    targeted = {}
    for t in targets:
        env = t["envelope"]
        if env and t["role"] not in ("exit", "unassigned"):
            targeted[env] = targeted.get(env, 0.0) + t["target_eur"]

    rows = []
    for name, env in sorted(envelopes.items(), key=lambda kv: kv[1].get("priority") or 99):
        ceiling = env.get("ceiling_eur")
        contributed = env.get("contributed_eur")
        room = (ceiling - contributed) if (ceiling is not None and contributed is not None) else None
        current = held_by_env.get(name, 0.0)
        # Capacity = what the envelope already holds (gains do not eat the
        # ceiling) plus what may still be paid in.
        capacity = (current + room) if room is not None else None
        want = targeted.get(name, 0.0)
        overflow = max(0.0, want - capacity) if capacity is not None else 0.0
        rows.append({
            "name": name,
            "label": env.get("label", name),
            "tax_pct": env.get("tax_pct"),
            # Brokerage travels with the envelope: the action plan prices every
            # order from these, so they must survive the copy.
            "fee_pct": env.get("fee_pct") or 0.0,
            "fee_fixed_eur": env.get("fee_fixed_eur") or 0.0,
            "min_order_eur": env.get("min_order_eur") or 0.0,
            "ceiling_eur": ceiling,
            "contributed_eur": contributed,
            "room_eur": room,
            "current_eur": current,
            "capacity_eur": capacity,
            "targeted_eur": want,
            "overflow_eur": overflow,
            "fill_pct": (contributed / ceiling * 100) if ceiling else None,
            "note": env.get("note"),
            "instrument": env.get("instrument"),
        })

    # Route each envelope's overflow to the next one by priority.
    for i, row in enumerate(rows):
        if row["overflow_eur"] > EPSILON_EUR and i + 1 < len(rows):
            row["overflow_to"] = rows[i + 1]["label"]
            row["overflow_to_key"] = rows[i + 1]["name"]
        else:
            row["overflow_to"] = None
            row["overflow_to_key"] = None
    return rows


def _slug(*parts) -> str:
    """Stable id for an action, so the browser can remember it as done.

    Deliberately excludes the amount: a purchase stays the same task even after
    prices move it by a few euros.
    """
    raw = "-".join(str(p) for p in parts).lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:80]


def order_cost(envelope: dict, amount: float) -> float:
    """What placing this order actually costs at the broker.

    Two very different shapes: a percentage (PEA) makes the number of orders
    irrelevant, a flat fee (CTO) makes small orders expensive. Both matter for
    what the plan should recommend.
    """
    if amount <= 0:
        return 0.0
    return amount * (envelope.get("fee_pct") or 0.0) / 100 + (envelope.get("fee_fixed_eur") or 0.0)


def build_backlog(policy: dict, targets: list, envelopes: list, sleeve: dict,
                  expected_net: dict | None = None) -> list:
    """One-off actions, grouped by phase and priced.

    Ordering follows cost, not convenience: moves that need no new money come
    first, then the accounts to open, then the purchases. Nothing is described as
    "free" any more — a sell-then-buy inside the PEA is charged brokerage twice,
    which is exactly what makes some switches not worth doing.
    """
    by_name = {e["name"]: e for e in envelopes}
    expected_net = expected_net or {}
    actions = []

    # 1 — Exits. Priced, and judged on whether the switch pays for itself.
    exits = [t for t in targets if t["role"] == "exit" and t["current_eur"] > EPSILON_EUR]
    freed = {}
    for t in sorted(exits, key=lambda t: -t["current_eur"]):
        env = by_name.get(t["envelope"] or "", {})
        cost = order_cost(env, t["current_eur"])
        freed[t["envelope"]] = freed.get(t["envelope"], 0.0) + t["current_eur"]
        no_tax = env.get("tax_pct") in (None, 0) or t["envelope"] in ("PEA", "AV")
        actions.append({
            "id": _slug("sell", t["key"]),
            "phase": "reshuffle",
            "action": "SELL",
            "label": t["label"],
            "amount_eur": t["current_eur"],
            "cost_eur": cost,
            "envelope": env.get("label", t["envelope"]),
            "envelope_key": t["envelope"],
            "funding": "—",
            "tax": "No tax — sale inside the PEA" if t["envelope"] == "PEA"
                   else f"Flat tax {env.get('tax_pct')} % on the gain",
            "why": t.get("note") or "Line dropped from the target allocation.",
            "internal": True,
        })

    # 2 — Trading sleeve above its cap: trim back, never top up.
    if sleeve["over_eur"] > EPSILON_EUR:
        env = by_name.get(sleeve.get("preferred_envelope") or "CTO", {})
        actions.append({
            "id": "trim-trading-sleeve",
            "phase": "reshuffle",
            "action": "TRIM",
            "label": "Trading sleeve",
            "amount_eur": sleeve["over_eur"],
            "cost_eur": order_cost(env, sleeve["over_eur"]),
            "envelope": env.get("label", "CTO"),
            "envelope_key": sleeve.get("preferred_envelope") or "CTO",
            "funding": "—",
            "tax": f"Flat tax {env.get('tax_pct')} % on the gains realised",
            "why": f"Sleeve at {sleeve['used_pct']:.1f} % of net worth, above its "
                   f"{sleeve['cap_pct']:.0f} % cap. Trim back into the core.",
            "internal": True,
        })

    # 3 — Open what the overflow will need, before it is needed.
    for e in envelopes:
        if e["overflow_eur"] > EPSILON_EUR and e["overflow_to"]:
            actions.append({
                "id": _slug("open", e["overflow_to"]),
                "phase": "setup",
                "action": "OPEN",
                "label": e["overflow_to"],
                "amount_eur": 0.0,
                "cost_eur": 0.0,
                "envelope": e["overflow_to"],
                "envelope_key": None,
                "funding": "—",
                "tax": "—",
                "why": (f"{e['label']} can only take {e['capacity_eur']:,.0f} € of the "
                        f"{e['targeted_eur']:,.0f} € targeted, so {e['overflow_eur']:,.0f} € has to "
                        f"go elsewhere. Open it now even with a token payment — the tax clock "
                        f"starts at the opening date.").replace(",", " "),
                "internal": True,
                # What to buy inside it once it exists, so opening the envelope and
                # choosing the fund are one decision rather than two.
                "instrument": (by_name.get(e["overflow_to_key"]) or {}).get("instrument"),
                "is_new_line": True,
            })

    # 4 — Buys. Only for lines actually OUT of their tolerance band: a band exists
    #     precisely so a few euros of drift never triggers a paid order.
    buys = [t for t in targets if t["role"] in ("core", "diversifier") and t["status"] == "under"]
    for t in sorted(buys, key=lambda t: t["drift_pt"]):
        need = -t["drift_eur"]
        internal = min(need, freed.get(t["envelope"], 0.0))
        freed[t["envelope"]] = freed.get(t["envelope"], 0.0) - internal
        env = by_name.get(t["envelope"] or "", {})
        for amount, is_internal in ((internal, True), (need - internal, False)):
            if amount <= EPSILON_EUR:
                continue
            cost = order_cost(env, amount)
            min_order = env.get("min_order_eur") or 0
            actions.append({
                "id": _slug("buy", t["key"], "internal" if is_internal else "new"),
                "phase": "reshuffle" if is_internal else "deploy",
                "action": "BUY",
                "label": t["label"],
                "amount_eur": amount,
                "cost_eur": cost,
                "envelope": env.get("label", t["envelope"]),
                "envelope_key": t["envelope"],
                # Overwritten with the real accounts by build_funding; this is
                # only what stands when no funding source is configured.
                "funding": "Proceeds from the sales above" if is_internal
                           else "New savings",
                "tax": "No tax — reallocation inside the PEA" if (is_internal and t["envelope"] == "PEA")
                       else (f"Envelope taxed at {env.get('tax_pct')} % on exit"
                             if env.get("tax_pct") else "—"),
                "why": ("The money is already in the envelope: no new savings needed."
                        if is_internal else f"{-t['drift_pt']:.1f} pt below target."),
                "internal": is_internal,
                "too_small": bool(min_order and amount < min_order),
                # A line held at zero is a fund to choose, not just an amount to
                # place — the plan carries the product and its ISIN with it.
                "instrument": t.get("instrument"),
                "is_new_line": t["current_eur"] <= EPSILON_EUR,
            })

    # 5 — Holdings the strategy says nothing about: a decision, not an amount.
    for t in [t for t in targets if t["role"] == "unassigned"]:
        actions.append({
            "id": _slug("review", t["key"]),
            "phase": "review",
            "action": "REVIEW",
            "label": t["label"],
            "amount_eur": t["current_eur"],
            "cost_eur": 0.0,
            "envelope": "—",
            "envelope_key": None,
            "funding": "—",
            "tax": "—",
            "why": "Held but absent from the strategy: add it to config/strategy.json, or close it.",
            "internal": True,
        })

    # Is each switch worth its brokerage? A sell is charged, and so is the buy that
    # reinvests the proceeds — so the comparison is against the line the money
    # actually moves into, not against the best line in the universe.
    replacement = next((a["label"] for a in actions if a["action"] == "BUY" and a["internal"]), None)
    for a in actions:
        a["optional"] = False
        a["payback_years"] = None
        a["replacement"] = None
        # Funding defaults for every action, not just the purchases build_funding
        # fills in: the template asks all of them, and a missing key there is a
        # 500, not a blank.
        a["funding_plan"] = []
        a["unfunded_eur"] = 0.0
        a["deferred_eur"] = 0.0
        a["available_now_eur"] = 0.0
        a["deferred_until"] = None
        if a["action"] != "SELL" or replacement is None:
            continue
        a["replacement"] = replacement
        uplift = expected_net.get(replacement, 0.0) - expected_net.get(a["label"], 0.0)
        gain = a["amount_eur"] * uplift / 100
        cost = a["cost_eur"] * 2  # the sale, then the purchase that reinvests it
        # Only the number gets its thousands separator swapped — running .replace
        # over the whole sentence would eat the commas in the prose.
        cost_str = f"{cost:,.0f}".replace(",", " ")
        if gain > 0.01:
            a["payback_years"] = cost / gain
            a["optional"] = a["payback_years"] > 3
            a["why"] += (f" Switching into {replacement} adds {uplift:.2f} pt of expected return, "
                         f"so the {cost_str} € of brokerage is earned back in "
                         f"{cost / gain * 12:.0f} months.")
        else:
            a["optional"] = True
            a["why"] += (" On expected return alone this one does not pay for itself: the case for "
                         f"it is lower volatility, not higher return. Costs about {cost_str} €.")

    PHASES = {"reshuffle": 0, "setup": 1, "deploy": 2, "review": 3}
    actions.sort(key=lambda a: (PHASES.get(a["phase"], 9), a["order"] if "order" in a else 0))
    for i, a in enumerate(actions, start=1):
        a["order"] = i
    return actions


def build_funding(policy: dict, accounts: list, backlog: list, today: date | None = None) -> dict:
    """Which account pays for which purchase.

    The backlog says what to buy; this says where the euro comes from. Funding
    sources are walked in the configured order — worst-paid euro first — keeping
    each one's `keep_eur`, and a source that is not liquid yet (the term deposit)
    funds the tail of the plan instead of being pretended spendable. Brokerage is
    drawn from the same pool: the fee is paid in cash like the order itself.

    Mutates the backlog to attach each purchase's funding, because an action and
    the account behind it are one instruction, not two tables to reconcile by eye.
    """
    today = today or date.today()
    # An account with no "id" simply cannot be referenced by a funding source —
    # it stays untouched rather than breaking the plan.
    keyed = [a for a in accounts if a.get("id")]
    balances = {a["id"]: a["balance"] for a in keyed}
    labels = {a["id"]: a.get("label", a["id"]) for a in keyed}
    banks = {a["id"]: a.get("bank", "") for a in keyed}

    pool = []
    for src in policy.get("funding_sources", []):
        balance = balances.get(src["account_id"])
        if balance is None:
            continue
        usable = max(0.0, balance - float(src.get("keep_eur") or 0.0))
        if usable <= EPSILON_EUR:
            continue
        when = src.get("available_from")
        locked = bool(when and datetime.strptime(when, "%Y-%m-%d").date() > today)
        pool.append({
            "account_id": src["account_id"],
            "label": labels.get(src["account_id"], src["account_id"]),
            "bank": banks.get(src["account_id"], ""),
            "usable_eur": usable,
            "left_eur": usable,
            "note": src.get("note"),
            "available_from": when if locked else None,
            "locked": locked,
        })
    # Liquid money first, whatever the configured order says: an account that
    # locked until its maturity date must never fund the first purchase.
    order = {s["account_id"]: i for i, s in enumerate(policy.get("funding_sources", []))}
    pool.sort(key=lambda s: (s["locked"], order.get(s["account_id"], 99)))

    purchases = [a for a in backlog if a["action"] == "BUY" and not a.get("internal")]
    need = sum(a["amount_eur"] + a["cost_eur"] for a in purchases)

    liquid = [s for s in pool if not s["locked"]]
    locked = [s for s in pool if s["locked"]]
    now_pool = sum(s["usable_eur"] for s in liquid)

    def draw(action_state, sources, budget):
        """Takes `budget` out of `sources`, in order, recording who paid."""
        left = budget
        for s in sources:
            if left <= EPSILON_EUR or s["left_eur"] <= EPSILON_EUR:
                continue
            take = min(left, s["left_eur"])
            s["left_eur"] -= take
            left -= take
            action_state.append({"label": s["label"], "bank": s["bank"], "amount_eur": take,
                                 "available_from": s["available_from"]})
        return budget - left

    # Liquid money is shared pro rata rather than poured into the first line.
    # Spending it in plan order would fully fund one ETF and push every other one
    # behind the term deposit's 2028 maturity — the portfolio would sit
    # concentrated in a single index for two years, which is the opposite of what
    # the target allocation is for. Locked money then fills what is left.
    for a in purchases:
        a["funding_plan"] = []
        a["_need"] = a["amount_eur"] + a["cost_eur"]
    for a in purchases:
        share = (a["_need"] / need) if need else 0.0
        draw(a["funding_plan"], liquid, min(a["_need"], now_pool * share))
    # Rounding and per-source caps leave crumbs; hand them to whoever still needs money.
    for a in purchases:
        got = sum(d["amount_eur"] for d in a["funding_plan"])
        got += draw(a["funding_plan"], liquid, a["_need"] - got)
        got += draw(a["funding_plan"], locked, a["_need"] - got)
        a["unfunded_eur"] = max(0.0, a["_need"] - got)
        deferred = sum(d["amount_eur"] for d in a["funding_plan"] if d["available_from"])
        a["deferred_eur"] = deferred
        a["available_now_eur"] = got - deferred
        a["deferred_until"] = next((d["available_from"] for d in a["funding_plan"]
                                    if d["available_from"]), None)
        a["funding"] = " + ".join(dict.fromkeys(d["label"] for d in a["funding_plan"]))             or "No funding source left"
        del a["_need"]

    for s in pool:
        s["used_eur"] = s["usable_eur"] - s["left_eur"]

    return {
        "need_eur": need,
        "sources": pool,
        "now_pool_eur": sum(s["usable_eur"] for s in pool if not s["locked"]),
        "locked_pool_eur": sum(s["usable_eur"] for s in pool if s["locked"]),
        "used_eur": sum(s["used_eur"] for s in pool),
        "unfunded_eur": sum(a["unfunded_eur"] for a in purchases),
    }


TRADING_KEY = "__TRADING__"


def current_weights(policy: dict, positions: list, total: float) -> dict:
    """Live positions expressed as weights over the analytics' asset keys.

    Trading positions collapse into the single synthetic __TRADING__ basket the
    analytics file models them as. Whatever is left unweighted is cash.
    """
    if not total:
        return {}
    sleeve_members = set((policy.get("trading_sleeve") or {}).get("members") or [])
    key_of = {}
    for t in policy.get("targets", []):
        for k in _match_keys(t):
            key_of[k] = t["key"]

    weights = {}
    for p in positions:
        if p["asset_key"] in sleeve_members:
            target_key = TRADING_KEY
        else:
            target_key = key_of.get(p["asset_key"])
        if not target_key:
            continue
        weights[target_key] = weights.get(target_key, 0.0) + p["value"] / total
    return weights


def portfolio_risk(analytics: dict, weights: dict) -> dict | None:
    """Volatility, beta and expected return of an arbitrary mix, from the stored
    covariance matrix — so the *current* portfolio's risk follows live prices
    without re-running the optimiser.

    Weights are shares of total net worth; the remainder is treated as the
    risk-free savings sleeve.
    """
    if not analytics or not weights:
        return None
    keys = analytics["covariance"]["keys"]
    matrix = analytics["covariance"]["matrix"]
    index = {k: i for i, k in enumerate(keys)}
    used = [(k, w) for k, w in weights.items() if k in index and w > 0]
    if not used:
        return None

    by_key = {a["key"]: a for a in analytics["assets"]}
    rf = analytics["risk_free_net_pct"] / 100

    variance = 0.0
    for ka, wa in used:
        for kb, wb in used:
            variance += wa * wb * matrix[index[ka]][index[kb]]
    vol = variance ** 0.5
    invested = sum(w for _, w in used)
    ret = sum(w * by_key[k]["expected_net_pct"] / 100 for k, w in used) + (1 - invested) * rf
    beta = sum(w * by_key[k]["beta"] for k, w in used)
    return {
        "vol_pct": round(vol * 100, 2),
        "ret_pct": round(ret * 100, 2),
        "beta": round(beta, 3),
        "sharpe": round((ret - rf) / vol, 3) if vol else None,
        "invested_pct": round(invested * 100, 1),
        "cash_pct": round((1 - invested) * 100, 1),
    }


def stress_losses(analytics: dict, policy: dict, weights: dict) -> list:
    """Applies each configured shock to an arbitrary mix of the analytics' assets."""
    if not analytics:
        return []
    scenarios = _strip_readme(policy.get("stress_scenarios") or {})
    key_by_label = {}
    out = []
    for entry in analytics.get("stress", []):
        shocks = scenarios.get(entry["scenario"], {})
        loss = sum(w * (shocks.get(k, 0.0) / 100) for k, w in weights.items())
        loss += max(0.0, 1 - sum(weights.values())) * (shocks.get(CASH_KEY, 0.0) / 100)
        out.append({
            "scenario": entry["scenario"],
            "target_pct": entry["target_pct"],
            "current_pct": round(loss * 100, 2),
        })
    return out


def build(policy: dict, positions: list, accounts: list, cash_total: float, total: float,
          analytics: dict | None = None) -> dict:
    """Assembles everything the Strategy page needs, in one pass."""
    expected = {a["label"]: a["expected_net_pct"] for a in (analytics or {}).get("assets", [])}
    targets = build_targets(policy, positions, cash_total, total)
    sleeve = build_sleeve(policy, positions, total)
    envelopes = build_envelopes(policy, positions, targets, cash_total)
    backlog = build_backlog(policy, targets, envelopes, sleeve, expected)
    funding = build_funding(policy, accounts, backlog)

    invested_target = sum(t["target_eur"] for t in targets if not t["is_cash"]) + sleeve["cap_eur"]
    invested_now = sum(p["value"] for p in positions)
    # Three different things, deliberately kept apart:
    #   - new money the plan directs out of savings,
    #   - money already invested that merely changes line (free, inside the PEA),
    #   - trading headroom, which stays entirely optional.
    to_deploy = sum(a["amount_eur"] for a in backlog
                    if a["action"] == "BUY" and not a.get("internal"))
    reallocate = sum(a["amount_eur"] for a in backlog
                     if a["action"] == "BUY" and a.get("internal"))
    return {
        "profile": policy.get("profile"),
        "as_of": policy.get("as_of"),
        "risk": policy.get("risk") or {},
        "targets": targets,
        "sleeve": sleeve,
        "envelopes": envelopes,
        "backlog": backlog,
        "funding": funding,
        "total": total,
        "invested_now_eur": invested_now,
        "invested_target_eur": invested_target,
        "invested_now_pct": (invested_now / total * 100) if total else 0.0,
        "invested_target_pct": (invested_target / total * 100) if total else 0.0,
        "cash_now_eur": cash_total,
        "to_deploy_eur": to_deploy,
        "reallocate_eur": reallocate,
        "discretionary_eur": max(0.0, sleeve["headroom_eur"]),
        "cash_release_eur": max(0.0, cash_total - sum(t["target_eur"] for t in targets if t["is_cash"])),
        "total_cost_eur": sum(a["cost_eur"] for a in backlog),
        "phases": [
            {"key": "reshuffle", "title": "Reshuffle what you already hold",
             "hint": "No new savings needed — the money is already invested and only changes line. "
                     "Brokerage still applies on both legs, so each switch has to earn it back."},
            {"key": "setup", "title": "Open what the plan needs",
             "hint": "Nothing to invest yet, but the clock starts at the opening date."},
            {"key": "deploy", "title": "Put new savings to work",
             "hint": "Each purchase names the account that pays for it, worst-paid euro first. On "
                     "the PEA the 0.25 % fee is proportional, so splitting an order into several "
                     "instalments costs nothing extra — spread them if it helps you sleep."},
            {"key": "review", "title": "Decide what to do with these",
             "hint": "Held today but absent from the strategy."},
        ],
    }
