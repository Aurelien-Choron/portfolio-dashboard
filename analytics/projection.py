"""Forecast: today's net worth carried forward, and what an ideal mix would do.

Nothing here compounds anything. This module only assembles the *parameters* of
each scenario — an annualised expected return and a volatility, both already net
of the envelope's tax rate — out of figures the Strategy page has measured or
judged. The compounding itself lives in exactly one place, the Monte Carlo
simulator in dashboard/templates/projection.html, so the chart and the goal
calculator can never disagree about what a euro grows into.

The usual split applies (see scripts/build_strategy.py): volatilities are
measured from weekly returns in euros, expected returns are judgements. The page
says which is which rather than blending them into one confident-looking curve.
"""


def ideal_same_risk(analytics: dict, vol_pct: float) -> dict | None:
    """The best mix available *at a given volatility*, on the capital market line.

    Blending the tangency portfolio with guaranteed savings traces a straight
    line from the risk-free rate through the tangency point; below the tangency's
    own volatility, that line is the highest return the measured covariance
    matrix allows. Benchmarking against the raw tangency portfolio instead would
    mostly measure the extra risk it takes, not the quality of its construction —
    so the benchmark is pinned to the volatility already being run.

    Past the tangency's volatility the line only continues on borrowed money,
    which is not on the table here: k is capped at 1 and `capped` says so.
    """
    tangency = (analytics or {}).get("tangency")
    if not tangency or not tangency.get("vol_pct"):
        return None
    rf = analytics["risk_free_net_pct"]
    k = min(1.0, (vol_pct or 0.0) / tangency["vol_pct"])
    return {
        "vol_pct": round(k * tangency["vol_pct"], 2),
        "ret_pct": round(rf + k * (tangency["ret_pct"] - rf), 2),
        "tangency_pct": round(k * 100, 1),
        "savings_pct": round((1 - k) * 100, 1),
        "capped": (vol_pct or 0.0) > tangency["vol_pct"],
    }


def build_scenarios(analytics: dict | None, current_risk: dict | None) -> list:
    """Every mix the Forecast page can project, as an (expected return, volatility) pair.

    Ordered from what you hold, to what the strategy targets, to the best the
    measured covariances allow at that same risk — then the individual lines,
    which are what answers "how much a month, on which asset, to reach a million".

    Returns [] when the risk figures have never been generated; the page then
    falls back to a hand-entered rate.
    """
    if not analytics:
        return []
    rf = analytics["risk_free_net_pct"]
    out = []

    if current_risk:
        out.append({
            "key": "today", "label": "Today's mix", "kind": "reference",
            "ret_pct": current_risk["ret_pct"], "vol_pct": current_risk["vol_pct"],
            "note": f"{current_risk['invested_pct']:g} % invested, "
                    f"{current_risk['cash_pct']:g} % guaranteed savings",
        })

    target = analytics.get("target_portfolio")
    if target:
        out.append({
            "key": "target", "label": "Strategy target", "kind": "reference",
            "ret_pct": target["ret_pct"], "vol_pct": target["vol_pct"],
            "note": f"{target['invested_pct']:g} % invested, "
                    f"{target['cash_pct']:g} % guaranteed savings",
        })

    # Pinned to today's risk when there is a live portfolio, to the target's
    # otherwise — the comparison is only meaningful against something real. The
    # label names its anchor: an "ideal" that quietly moved to a different
    # volatility would be the exact confusion this construction exists to avoid.
    anchor_of = "today" if current_risk else "target"
    anchor = (current_risk or target or {}).get("vol_pct")
    ideal = ideal_same_risk(analytics, anchor) if anchor else None
    if ideal:
        note = (f"{ideal['tangency_pct']:g} % tangency portfolio, "
                f"{ideal['savings_pct']:g} % guaranteed savings")
        if ideal["capped"]:
            note = ("100 % tangency portfolio — going past its own volatility "
                    "would take borrowed money, which this never assumes")
        out.append({
            "key": "ideal", "kind": "reference",
            "label": "Ideal at today's risk" if anchor_of == "today"
                     else "Ideal at the target's risk",
            "dash": True, "ret_pct": ideal["ret_pct"], "vol_pct": ideal["vol_pct"],
            "note": note,
        })

    out.append({
        "key": "savings", "label": "Guaranteed savings only", "kind": "asset",
        "ret_pct": rf, "vol_pct": 0.0,
        "note": "Regulated savings, net of tax. No volatility, no surprise.",
    })
    for asset in analytics.get("assets", []):
        note = f"Beta {asset['beta']:g} · worst drawdown {asset['max_dd_pct']:g} % over the window"
        if asset.get("proxy"):
            note += f" · measured on the proxy {asset['proxy']}"
        out.append({
            "key": f"asset:{asset['key']}", "label": f"100 % {asset['label']}",
            "kind": "asset", "ret_pct": asset["expected_net_pct"],
            "vol_pct": asset["vol_pct"], "note": note,
        })
    return out


def default_scenario(scenarios: list) -> str:
    """What to select on arrival: the strategy's own target if there is one.

    The page opens on the mix the user has decided to hold, not on the one they
    happen to hold today — the forecast is about where the plan leads.
    """
    keys = [s["key"] for s in scenarios]
    for preferred in ("target", "today", "savings"):
        if preferred in keys:
            return preferred
    return keys[0] if keys else "custom"


def starting_capital(positions: list, accounts: list) -> dict:
    """Where the projection starts: net worth, split the way the risk model reads it.

    Same arithmetic as the Strategy page — invested lines plus every visible
    account — so the two pages cannot quote different net worths.
    """
    invested = sum(p["value"] for p in positions)
    cash = sum(a["balance"] for a in accounts)
    return {
        "invested_eur": invested,
        "cash_eur": cash,
        "total_eur": invested + cash,
    }
