"""Reconstructs the portfolio's value over time.

Assumed approximation: for assets without a ticker mapped in
config/tickers.json, the historical price is replaced by the current average
cost (a flat line). "Invested capital" is the net cash flow into investments
(purchases − sale proceeds), not the strict accounting cost basis of open positions.
"""

import pandas as pd

import market_data


def build_history(transactions: pd.DataFrame, positions_df: pd.DataFrame) -> pd.DataFrame:
    if transactions.empty:
        return pd.DataFrame(columns=["date", "invested_capital", "portfolio_value"])

    start = transactions["date"].min().normalize()
    today = pd.Timestamp.today().normalize()
    date_range = pd.date_range(start, today, freq="D")

    # --- Net invested capital (cash flow) ---
    buys = transactions.loc[transactions["type"] == "BUY", ["date", "amount"]].copy()
    buys["flow"] = buys["amount"].abs()
    sells = transactions.loc[transactions["type"] == "SELL", ["date", "amount"]].copy()
    sells["flow"] = -sells["amount"].abs()
    flows = pd.concat([buys[["date", "flow"]], sells[["date", "flow"]]])
    daily_flow = flows.groupby(flows["date"].dt.normalize())["flow"].sum()
    invested_capital = daily_flow.reindex(date_range, fill_value=0).cumsum()

    # --- Quantity held per asset over time ---
    trades = transactions[transactions["type"].isin(["BUY", "SELL"])].copy()
    trades["signed_qty"] = trades.apply(
        lambda r: r["quantity"] if r["type"] == "BUY" else -r["quantity"], axis=1
    )
    qty_by_asset = {}
    for asset_key, grp in trades.groupby("asset_key"):
        daily_qty = grp.groupby(grp["date"].dt.normalize())["signed_qty"].sum()
        qty_by_asset[asset_key] = daily_qty.reindex(date_range, fill_value=0).cumsum()

    asset_keys = list(qty_by_asset.keys())
    price_history = market_data.fetch_price_history(asset_keys, start=start)

    avg_cost_fallback = positions_df.set_index("asset_key")["avg_cost"].to_dict()

    portfolio_value = pd.Series(0.0, index=date_range)
    for asset_key, qty_series in qty_by_asset.items():
        if asset_key in price_history and not price_history[asset_key].empty:
            price_series = (
                price_history[asset_key]
                .reindex(date_range)
                .ffill()
                .bfill()
            )
        else:
            fallback = avg_cost_fallback.get(asset_key, 0.0)
            price_series = pd.Series(fallback, index=date_range)
        portfolio_value = portfolio_value.add(qty_series * price_series, fill_value=0)

    return pd.DataFrame(
        {
            "date": date_range,
            "invested_capital": invested_capital.values,
            "portfolio_value": portfolio_value.values,
        }
    )


def build_trade_events(transactions: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    """Buys/sells aggregated per day, with their position on the value curve —
    used to place a visual marker on the value-over-time chart."""
    trades = transactions[transactions["type"].isin(["BUY", "SELL"])].copy()
    if trades.empty or hist.empty:
        return pd.DataFrame(columns=["date", "type", "name", "amount", "y"])

    trades["day"] = trades["date"].dt.normalize()
    day_value = hist.set_index("date")["portfolio_value"]

    events = (
        trades.groupby(["day", "type"])
        .agg(
            amount=("amount", lambda s: s.abs().sum()),
            name=("name", lambda s: ", ".join(sorted({n for n in s if n}))),
        )
        .reset_index()
        .rename(columns={"day": "date"})
    )
    events["y"] = events["date"].map(day_value)
    return events
