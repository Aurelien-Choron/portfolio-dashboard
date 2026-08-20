"""Geographic and sector diversification of investment positions.

yfinance doesn't provide an ETF's "look-through" holdings (just its legal
domicile, useless for a real breakdown): the breakdown therefore comes from a
mapping entered by hand in config/exposure.json, taken from each fund's factsheet.
"""
import json
import os

from paths import config_root

EXPOSURE_PATH = os.path.join(config_root(), "exposure.json")
DIMENSIONS = ("country", "sector")


def load_exposure() -> dict:
    if not os.path.exists(EXPOSURE_PATH):
        return {}
    with open(EXPOSURE_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def build_diversification(positions: list) -> dict:
    """positions: list of {"asset_key", "name", "value"} (open positions).

    Returns the portfolio's aggregated breakdown by country and by sector (key
    "portfolio", in €), and the row-by-row detail (key "funds") for the per-fund
    view. A position missing from config/exposure.json falls under "Not specified"
    rather than silently disappearing from the total.
    """
    exposure = load_exposure()

    portfolio = {dim: {} for dim in DIMENSIONS}
    funds = []
    for p in positions:
        entry = exposure.get(p["asset_key"], {})
        fund = {"asset_key": p["asset_key"], "name": p["name"], "value": p["value"]}
        for dim in DIMENSIONS:
            breakdown = entry.get(dim) or {}
            fund[dim] = (
                {label: p["value"] * pct / 100 for label, pct in breakdown.items()}
                if breakdown
                else {"Not specified": p["value"]}
            )
            for label, value in fund[dim].items():
                portfolio[dim][label] = portfolio[dim].get(label, 0.0) + value
        funds.append(fund)

    return {"portfolio": portfolio, "funds": funds}
