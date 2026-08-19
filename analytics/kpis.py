"""Agrégation des KPIs de portefeuille à partir des positions et des prix de marché."""

import pandas as pd

import market_data


def enrich_with_prices(positions_df: pd.DataFrame) -> pd.DataFrame:
    """Ajoute current_price / price_source / current_value / unrealized_pnl."""
    df = positions_df.copy()
    if df.empty:
        df["current_price"] = []
        df["price_source"] = []
        df["current_value"] = []
        df["unrealized_pnl"] = []
        df["unrealized_pnl_pct"] = []
        return df

    open_keys = df.loc[df["quantity"] > 1e-9, "asset_key"].tolist()
    live_prices = market_data.fetch_last_prices(open_keys)

    current_price, price_source = [], []
    for _, row in df.iterrows():
        if row["asset_key"] in live_prices:
            price, price_date = live_prices[row["asset_key"]]
            current_price.append(price)
            price_source.append(f"live ({price_date:%d/%m})")
        else:
            current_price.append(row["avg_cost"])
            price_source.append("estimé (PRU)")

    df["current_price"] = current_price
    df["price_source"] = price_source
    df["current_value"] = df["quantity"] * df["current_price"]
    df["unrealized_pnl"] = df["current_value"] - df["cost_basis"]
    df["unrealized_pnl_pct"] = (df["unrealized_pnl"] / df["cost_basis"].replace(0, pd.NA)) * 100
    return df


def summary(df: pd.DataFrame, transactions: pd.DataFrame) -> dict:
    """Calcule les KPIs globaux du portefeuille."""
    open_positions = df[df["quantity"] > 1e-9]

    total_value = open_positions["current_value"].sum()
    total_cost = open_positions["cost_basis"].sum()
    unrealized_pnl = total_value - total_cost
    unrealized_pnl_pct = (unrealized_pnl / total_cost * 100) if total_cost > 1e-9 else 0.0

    realized_pnl = df["realized_pnl"].sum()
    dividends = df["dividends"].sum()
    fees = df["fees_paid"].sum()

    deposits = transactions.loc[transactions["type"] == "DEPOSIT", "amount"].sum()
    withdrawals = transactions.loc[transactions["type"] == "WITHDRAWAL", "amount"].abs().sum()
    interest = transactions.loc[transactions["type"] == "INTEREST", "amount"].sum()

    n_live = df["price_source"].str.startswith("live").sum() if "price_source" in df else 0
    n_total = len(open_positions)

    return {
        "total_value": total_value,
        "total_cost": total_cost,
        "unrealized_pnl": unrealized_pnl,
        "unrealized_pnl_pct": unrealized_pnl_pct,
        "realized_pnl": realized_pnl,
        "dividends": dividends,
        "interest": interest,
        "fees": fees,
        "deposits": deposits,
        "withdrawals": withdrawals,
        "nb_positions": int(n_total),
        "nb_prix_live": int(n_live),
        "nb_transactions": int(len(transactions)),
    }


def by_broker(df: pd.DataFrame) -> pd.DataFrame:
    open_positions = df[df["quantity"] > 1e-9]
    if open_positions.empty:
        return pd.DataFrame(columns=["broker", "current_value"])
    return (
        open_positions.groupby("broker", as_index=False)["current_value"]
        .sum()
        .sort_values("current_value", ascending=False)
    )
