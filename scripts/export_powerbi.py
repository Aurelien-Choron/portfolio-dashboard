"""Exports what the Power BI twin of this dashboard (powerbi/) reads, and the
figures it has to reproduce.

The Power BI report rebuilds the journal, the positions and every measure on its
own, from the raw broker CSVs and config JSON under demo/. It can't get two
things by itself:

  * prices. Calling Yahoo Finance from Power Query is fragile (cookies, crumbs,
    rate limits), so each asset's daily EUR close is frozen into
    powerbi/data/prices_daily.csv;
  * an answer key. powerbi/data/expected_values.json holds the figures this app
    computes *on that same frozen snapshot*, so every DAX measure can be checked
    against the Python it replaces. A screenshot taken on other prices would not
    do.

It also writes the reference tables that live in code rather than in config
(asset-class and broker labels and colours), plus the report's two themes. All
of these come from dashboard/palette.py and dashboard/app.py, so the report
cannot drift from the app's colours.

Demo only: everything written here is committed, so, like
generate_screenshots.py, it refuses any PORTFOLIO_ROOT but demo.

Usage: python scripts/export_powerbi.py
"""
import csv
import json
import os
import sys
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

# Before importing anything that resolves paths on import (market_data,
# analytics.*, dashboard.app): see the same guard in generate_screenshots.py.
_requested = os.environ.get("PORTFOLIO_ROOT", "demo")
if _requested != "demo":
    sys.exit(f"refusing to run against PORTFOLIO_ROOT={_requested!r}: "
             "the Power BI exports are committed, so they may only ever hold demo data")
os.environ["PORTFOLIO_ROOT"] = "demo"

import pandas as pd  # noqa: E402

import market_data  # noqa: E402
from analytics import exposure, kpis, patrimoine, performance, performance_by_asset  # noqa: E402
from analytics import positions as positions_mod  # noqa: E402
from analytics import projection, strategy  # noqa: E402
from dashboard import palette  # noqa: E402
from dashboard.app import BROKER_COLORS, BROKER_LABELS, BROKER_ORDER, CATEGORY_LABELS  # noqa: E402
from importers import normalize  # noqa: E402
from paths import data_root  # noqa: E402

OUT_DIR = os.path.join(REPO_ROOT, "powerbi")
DATA_DIR = os.path.join(OUT_DIR, "data")
THEME_DIR = os.path.join(OUT_DIR, "theme")

# Four decimals is finer than any price the brokers quote. The answer key is
# computed from the rounded values, not the raw ones, so Power BI and Python
# multiply exactly the same numbers.
PRICE_DECIMALS = 4


# ------------------------------------------------------------------ prices
def price_snapshot(transactions: pd.DataFrame) -> tuple[dict, pd.Timestamp]:
    """{asset_key: Series of EUR closes} up to the last *complete* session.

    Today's row is dropped: during market hours Yahoo reports the live price as
    today's close, and that number would still be moving when the snapshot
    froze it.
    """
    traded = transactions[transactions["type"].isin(["BUY", "SELL"])]
    start = transactions["date"].min().normalize()
    history = market_data.fetch_price_history(sorted(traded["asset_key"].unique()), start=start)

    today = pd.Timestamp.today().normalize()
    snapshot = {}
    for key, series in history.items():
        series = series.copy()
        series.index = pd.to_datetime(series.index).tz_localize(None).normalize()
        series = series[series.index < today].round(PRICE_DECIMALS)
        if not series.empty:
            snapshot[key] = series
    if not snapshot:
        sys.exit("no price history came back from Yahoo Finance: nothing to freeze")
    as_of = max(s.index.max() for s in snapshot.values())
    return snapshot, as_of


def write_prices(snapshot: dict) -> str:
    tickers = market_data.load_ticker_map()
    path = os.path.join(DATA_DIR, "prices_daily.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "asset_key", "ticker", "close_eur"])
        for key in sorted(snapshot):
            for day, close in snapshot[key].items():
                writer.writerow([day.date().isoformat(), key, tickers.get(key, ""),
                                 f"{close:.{PRICE_DECIMALS}f}"])
    return path


def frozen_market(snapshot: dict, as_of: pd.Timestamp):
    """Serves the snapshot in place of Yahoo Finance, and pins "today" to as_of.

    Every analytics function below runs unmodified: each one still believes it
    is fetching live prices on the day it is called.
    """
    def last_prices(asset_keys):
        return {k: (float(snapshot[k].iloc[-1]), snapshot[k].index[-1])
                for k in asset_keys if k in snapshot}

    def price_history(asset_keys, start):
        return {k: snapshot[k] for k in asset_keys if k in snapshot}

    patches = [
        mock.patch.object(market_data, "fetch_last_prices", last_prices),
        mock.patch.object(market_data, "fetch_price_history", price_history),
        mock.patch.object(pd.Timestamp, "today", classmethod(lambda cls, tz=None: as_of)),
    ]

    class _All:
        def __enter__(self):
            for p in patches:
                p.start()

        def __exit__(self, *exc):
            for p in reversed(patches):
                p.stop()

    return _All()


# -------------------------------------------------------------- answer key
def _round(value, digits=4):
    """Walks a structure and rounds its floats: the file is read by a person."""
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float):
        return None if pd.isna(value) else round(value, digits)
    if isinstance(value, dict):
        return {k: _round(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round(v, digits) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "item"):  # numpy scalars
        return _round(value.item(), digits)
    return value


def investments_section(transactions: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    pos_df = kpis.enrich_with_prices(
        positions_mod.positions_frame(positions_mod.build_positions(transactions)))
    summary = kpis.summary(pos_df, transactions)
    broker_df = kpis.by_broker(pos_df)

    fees_map = market_data.load_fees_map()
    perf = performance_by_asset.build_asset_performance(transactions, pos_df)
    perf["ter_pct"] = perf["asset_key"].map(fees_map)
    is_open = perf["quantity"] > 1e-9
    perf["annual_fee_eur"] = (perf["current_value"] * perf["ter_pct"] / 100).where(is_open)

    columns = [
        "asset_key", "name", "broker", "quantity", "avg_cost", "cost_basis",
        "current_price", "current_value", "unrealized_pnl", "unrealized_pnl_pct",
        "realized_pnl", "dividends", "fees_paid", "total_bought", "total_sold",
        "total_gain", "total_return_pct", "first_buy_date", "months_held",
        "monthly_avg_pct", "monthly_avg_eur", "ter_pct", "annual_fee_eur",
    ]
    assets = perf[columns].sort_values("current_value", ascending=False).to_dict("records")

    # Month-end points of the value-over-time chart, plus the snapshot day:
    # enough to check the line without shipping every day of it twice.
    hist = performance.build_history(transactions, pos_df).set_index("date")
    checkpoints = hist[hist.index.is_month_end | (hist.index == hist.index.max())]

    open_pos = pos_df[pos_df["quantity"] > 1e-9]
    diversification = exposure.build_diversification([
        {"asset_key": r["asset_key"], "name": r["name"], "value": r["current_value"]}
        for r in open_pos.to_dict("records")
    ])["portfolio"]

    section = {
        "summary": {k: summary[k] for k in (
            "total_value", "total_cost", "unrealized_pnl", "unrealized_pnl_pct",
            "realized_pnl", "dividends", "fees", "deposits", "withdrawals",
            "nb_positions", "nb_transactions")},
        "annual_fund_fees_eur": float(perf["annual_fee_eur"].sum()),
        "by_broker": [{"broker": r["broker"], "value": r["current_value"]}
                      for r in broker_df.to_dict("records")],
        "assets": assets,
        "value_over_time": [
            {"date": day, "invested_capital": row["invested_capital"],
             "portfolio_value": row["portfolio_value"]}
            for day, row in checkpoints.iterrows()
        ],
        "diversification": {
            dim: dict(sorted(values.items(), key=lambda kv: -kv[1]))
            for dim, values in diversification.items()
        },
    }
    return section, pos_df


def net_worth_section(pos_df: pd.DataFrame, transactions: pd.DataFrame) -> dict:
    open_pos = pos_df[pos_df["quantity"] > 1e-9]
    by_broker = kpis.by_broker(pos_df)
    by_broker_raw = {r["broker"]: r["current_value"] for r in by_broker.to_dict("records")}
    data = patrimoine.build_patrimoine(
        float(open_pos["current_value"].sum()),
        {BROKER_LABELS.get(b, b): v for b, v in by_broker_raw.items()},
        [{"asset_key": r["asset_key"], "value": r["current_value"]}
         for r in open_pos.to_dict("records")],
    )
    envelopes = patrimoine.build_investment_accounts(by_broker_raw, BROKER_LABELS, transactions)
    return {
        "total": data["total"],
        "investments": data["bourse_value"],
        "savings": data["epargne_total"],
        "by_class": [
            {"class": c["category"], "label": CATEGORY_LABELS.get(c["category"], c["category"]),
             "value": c["value"], "pct": c["actual_pct"]}
            for c in data["comparison"]
        ],
        "by_bank": data["bank_slices"],
        "accounts": [
            {k: a.get(k) for k in ("id", "label", "bank", "category", "balance",
                                   "rate_pct", "ceiling", "maturity_date")}
            for a in data["accounts"] + envelopes
        ],
    }


def strategy_section(pos_df: pd.DataFrame, transactions: pd.DataFrame) -> tuple[dict, dict | None]:
    policy = strategy.load_policy()
    analytics = strategy.load_analytics()
    positions = [
        {"asset_key": r["asset_key"], "name": r["name"], "value": r["current_value"],
         "broker": r["broker"]}
        for r in pos_df[pos_df["quantity"] > 1e-9].to_dict("records")
    ]
    accounts = [a for a in patrimoine.load_accounts() if a.get("visible", True)]
    cash_total = sum(a["balance"] for a in accounts)
    total = sum(p["value"] for p in positions) + cash_total

    data = strategy.build(policy, positions, accounts, cash_total, total, analytics, transactions)
    weights = strategy.current_weights(policy, positions, total)
    current_risk = strategy.portfolio_risk(analytics, weights) if analytics else None

    section = {
        "profile": data["profile"],
        "total": data["total"],
        "invested_now_pct": data["invested_now_pct"],
        "invested_target_pct": data["invested_target_pct"],
        "cash_now_eur": data["cash_now_eur"],
        "to_deploy_eur": data["to_deploy_eur"],
        "targets": [
            {k: t[k] for k in ("key", "label", "envelope", "target_pct", "band_pt",
                               "current_eur", "current_pct", "target_eur", "drift_eur",
                               "drift_pt", "status")}
            for t in data["targets"]
        ],
        "sleeve": {k: data["sleeve"][k] for k in (
            "cap_pct", "cap_eur", "used_eur", "used_pct", "headroom_eur")},
        "envelopes": [
            {k: e[k] for k in ("name", "label", "ceiling_eur", "contributed_eur",
                               "room_eur", "current_eur", "fill_pct")}
            for e in data["envelopes"]
        ],
        "weights": weights,
        "current_risk": current_risk,
        "target_risk": (analytics or {}).get("target_portfolio"),
        "stress": strategy.stress_losses(analytics, policy, weights) if analytics else [],
    }
    return section, current_risk


def forecast_section(pos_df: pd.DataFrame, current_risk: dict | None) -> dict:
    positions = [{"asset_key": r["asset_key"], "value": r["current_value"]}
                 for r in pos_df[pos_df["quantity"] > 1e-9].to_dict("records")]
    accounts = [a for a in patrimoine.load_accounts() if a.get("visible", True)]
    analytics = strategy.load_analytics()
    return {
        "capital": projection.starting_capital(positions, accounts),
        "scenarios": [
            {k: s[k] for k in ("key", "label", "ret_pct", "vol_pct")}
            for s in projection.build_scenarios(analytics, current_risk)
        ],
        "inflation_pct": (analytics or {}).get("inflation_pct"),
        "risk_free_net_pct": (analytics or {}).get("risk_free_net_pct"),
    }


# ------------------------------------------------------- reference tables
def write_reference_tables() -> list[str]:
    """Labels and colours the app keeps in code: Power BI reads them as dimensions."""
    order = patrimoine.CATEGORY_ORDER
    classes = os.path.join(DATA_DIR, "asset_classes.csv")
    with open(classes, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["asset_class", "label", "sort_order", "color_dark", "color_light"])
        for i, key in enumerate(order, start=1):
            writer.writerow([key, CATEGORY_LABELS[key], i,
                             palette.ASSET_DARK[key], palette.ASSET_LIGHT[key]])

    # Broker colours are CSS variables in the app; resolve them to the hex each
    # theme assigns, since a Power BI colour has to be a literal.
    def resolve(css_var: str, data: dict) -> str:
        name = css_var.removeprefix("var(--data-").removesuffix(")")
        return data.get(name, palette.DIVERGING_MUTED)

    brokers = os.path.join(DATA_DIR, "brokers.csv")
    with open(brokers, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["broker", "label", "sort_order", "color_dark", "color_light"])
        for i, key in enumerate(BROKER_ORDER, start=1):
            writer.writerow([key, BROKER_LABELS[key], i,
                             resolve(BROKER_COLORS[key], palette.DATA_DARK),
                             resolve(BROKER_COLORS[key], palette.DATA_LIGHT)])
    return [classes, brokers]


# ------------------------------------------------------------------ themes
def _blend(rgba: str, ground: str) -> str:
    """rgba(r,g,b,a) laid over a hex ground: Power BI only takes opaque hex."""
    r, g, b, a = (float(x) for x in rgba.removeprefix("rgba(").removesuffix(")").split(","))
    gr, gg, gb = (int(ground[i:i + 2], 16) for i in (1, 3, 5))
    mix = [round(c * a + base * (1 - a)) for c, base in ((r, gr), (g, gg), (b, gb))]
    return "#" + "".join(f"{c:02x}" for c in mix)


def theme(name: str, tokens: dict, data: dict, good: str, critical: str) -> dict:
    solid = lambda color: {"solid": {"color": color}}  # noqa: E731
    surface, page = tokens["--surface-1"], tokens["--page"]
    border = _blend(tokens["--border"], surface)
    return {
        "name": name,
        "dataColors": [data[k] for k in
                       ("blue", "orange", "aqua", "yellow", "magenta", "green", "purple", "red")],
        "foreground": tokens["--text-primary"],
        "foregroundNeutralSecondary": tokens["--text-secondary"],
        "foregroundNeutralTertiary": tokens["--text-muted"],
        "background": surface,
        "backgroundLight": _blend(tokens["--chip-bg"], surface),
        "backgroundNeutral": tokens["--grid"],
        "tableAccent": tokens["--brand"],
        "hyperlink": tokens["--info"],
        "good": good, "neutral": tokens["--text-muted"], "bad": critical,
        # Default diverging scale (conditional formatting): the treemap's ramp.
        "maximum": palette.DIVERGING_GOOD, "center": palette.DIVERGING_MUTED,
        "minimum": palette.DIVERGING_CRITICAL,
        "textClasses": {
            # Fraunces can't travel inside a report; Georgia is the serif every
            # Windows machine has.
            "callout": {"fontFace": "Georgia", "fontSize": 28, "color": tokens["--text-primary"]},
            "title": {"fontFace": "Georgia", "fontSize": 12, "color": tokens["--text-primary"]},
            "header": {"fontFace": "Segoe UI Semibold", "fontSize": 11,
                       "color": tokens["--text-primary"]},
            "label": {"fontFace": "Segoe UI", "fontSize": 10, "color": tokens["--text-secondary"]},
        },
        "visualStyles": {
            "page": {"*": {
                "background": [{"color": solid(page), "transparency": 0}],
                "outspace": [{"color": solid(page), "transparency": 0}],
            }},
            "*": {"*": {
                "background": [{"show": True, "color": solid(surface), "transparency": 0}],
                "border": [{"show": True, "color": solid(border), "radius": 10}],
                "dropShadow": [{"show": False}],
                "valueAxis": [{"gridlineColor": solid(tokens["--grid"]), "gridlineStyle": "dotted"}],
                "categoryAxis": [{"gridlineShow": False}],
            }},
        },
    }


def write_themes() -> list[str]:
    paths = []
    for suffix, tokens, data, good, critical in (
        ("dark", palette.DARK, palette.DATA_DARK, palette.GOOD_DARK, palette.CRITICAL_DARK),
        ("light", palette.LIGHT, palette.DATA_LIGHT, palette.GOOD_LIGHT, palette.CRITICAL_LIGHT),
    ):
        path = os.path.join(THEME_DIR, f"portfolio-{suffix}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(theme(f"Portfolio Dashboard ({suffix})", tokens, data, good, critical),
                      f, indent=2)
            f.write("\n")
        paths.append(path)
    return paths


# -------------------------------------------------------------------- main
def main() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(THEME_DIR, exist_ok=True)

    transactions = normalize.load_all(data_root())
    snapshot, as_of = price_snapshot(transactions)
    written = [write_prices(snapshot)]

    with frozen_market(snapshot, as_of):
        investments, pos_df = investments_section(transactions)
        net_worth = net_worth_section(pos_df, transactions)
        strategy_data, current_risk = strategy_section(pos_df, transactions)
        forecast = forecast_section(pos_df, current_risk)

    key = {
        "_readme": ("Figures computed by the Python app (analytics/*) on the frozen prices in "
                    "prices_daily.csv, as of the date below. The Power BI report must reproduce "
                    "them. Regenerate with: python scripts/export_powerbi.py"),
        "as_of": as_of,
        "journal": {
            "rows": len(transactions),
            "by_type": transactions["type"].value_counts().sort_index().to_dict(),
            "by_broker": transactions["broker"].value_counts().sort_index().to_dict(),
        },
        "investments": investments,
        "net_worth": net_worth,
        "strategy": strategy_data,
        "forecast": forecast,
    }
    answer_key = os.path.join(DATA_DIR, "expected_values.json")
    with open(answer_key, "w", encoding="utf-8") as f:
        json.dump(_round(key), f, ensure_ascii=False, indent=2)
        f.write("\n")
    written.append(answer_key)

    written += write_reference_tables()
    written += write_themes()

    for path in written:
        print(f"wrote {os.path.relpath(path, REPO_ROOT)}")
    print(f"\nPrices frozen as of {as_of.date()} (demo data).")


if __name__ == "__main__":
    main()
