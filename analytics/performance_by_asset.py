"""Per-asset performance since the first purchase: total and monthly return.

Method (deliberately simple, consistent with the rest of the project — no IRR/XIRR):
- total return = (realized gain + unrealized gain + dividends) / total invested
  (total invested = sum of every purchase ever made on this asset, not just the
  cost of the shares still held: a fully closed round trip still counts its
  committed capital).
- average monthly return = total return / number of months since the first purchase
  (simple average over the whole period, not a compounded/annualized rate).
"""

import pandas as pd

DAYS_PER_MONTH = 30.4368


def build_asset_performance(transactions: pd.DataFrame, positions_df: pd.DataFrame) -> pd.DataFrame:
    if positions_df.empty:
        return positions_df.assign(
            total_bought=[], total_sold=[], total_gain=[], total_return_pct=[],
            months_held=[], monthly_avg_pct=[], monthly_avg_eur=[], first_buy_date=[],
        )

    today = pd.Timestamp.today().normalize()
    trades = transactions[transactions["type"].isin(["BUY", "SELL"])]

    bought = (
        trades[trades["type"] == "BUY"]
        .groupby("asset_key")["amount"].apply(lambda s: s.abs().sum())
        .rename("total_bought")
    )
    sold = (
        trades[trades["type"] == "SELL"]
        .groupby("asset_key")["amount"].apply(lambda s: s.abs().sum())
        .rename("total_sold")
    )
    first_buy = (
        trades[trades["type"] == "BUY"]
        .groupby("asset_key")["date"].min()
        .rename("first_buy_date")
    )

    df = positions_df.merge(bought, on="asset_key", how="left")
    df = df.merge(sold, on="asset_key", how="left")
    df = df.merge(first_buy, on="asset_key", how="left")
    df["total_bought"] = df["total_bought"].fillna(0.0)
    df["total_sold"] = df["total_sold"].fillna(0.0)

    df["total_gain"] = df["realized_pnl"] + df["unrealized_pnl"] + df["dividends"]
    total_bought_safe = df["total_bought"].mask(df["total_bought"] == 0)  # NaN (not pd.NA), to stay comparable in Jinja
    df["total_return_pct"] = (df["total_gain"] / total_bought_safe) * 100

    months_held = (today - df["first_buy_date"]).dt.days / DAYS_PER_MONTH
    df["months_held"] = months_held.clip(lower=1 / DAYS_PER_MONTH)  # avoids dividing by ~0 on the purchase day itself
    df["monthly_avg_pct"] = df["total_return_pct"] / df["months_held"]
    df["monthly_avg_eur"] = df["total_gain"] / df["months_held"]

    return df
