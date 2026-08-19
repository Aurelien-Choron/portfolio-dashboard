"""Reconstruction de l'évolution du portefeuille dans le temps.

Approximation assumée : pour les actifs sans ticker mappé dans
config/tickers.json, le prix historique est remplacé par le prix de revient
moyen actuel (ligne plate). Le "capital investi" est le flux net de
trésorerie vers les investissements (achats - produits de vente), pas le
coût de revient comptable strict des positions ouvertes.
"""

import pandas as pd

import market_data


def build_history(transactions: pd.DataFrame, positions_df: pd.DataFrame) -> pd.DataFrame:
    if transactions.empty:
        return pd.DataFrame(columns=["date", "invested_capital", "portfolio_value"])

    start = transactions["date"].min().normalize()
    today = pd.Timestamp.today().normalize()
    date_range = pd.date_range(start, today, freq="D")

    # --- Capital net investi (flux de trésorerie) ---
    buys = transactions.loc[transactions["type"] == "BUY", ["date", "amount"]].copy()
    buys["flow"] = buys["amount"].abs()
    sells = transactions.loc[transactions["type"] == "SELL", ["date", "amount"]].copy()
    sells["flow"] = -sells["amount"].abs()
    flows = pd.concat([buys[["date", "flow"]], sells[["date", "flow"]]])
    daily_flow = flows.groupby(flows["date"].dt.normalize())["flow"].sum()
    invested_capital = daily_flow.reindex(date_range, fill_value=0).cumsum()

    # --- Quantité détenue par actif au fil du temps ---
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
    """Achats/ventes agrégés par jour, avec leur position sur la courbe de valeur —
    pour poser un repère visuel sur le graphe d'évolution."""
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
