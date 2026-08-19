"""Performance par actif depuis le premier achat : rendement total et mensualisé.

Méthode (volontairement simple, cohérente avec le reste du projet — pas de TRI/XIRR) :
- rendement total = (plus-value réalisée + plus-value latente + dividendes) / total investi
  (total investi = somme de tous les achats jamais faits sur cet actif, pas seulement
  le coût des titres encore détenus : un aller-retour soldé compte pour son capital engagé).
- rendement mensuel moyen = rendement total / nombre de mois écoulés depuis le premier achat
  (moyenne simple sur toute la période, pas un taux composé/annualisé).
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
    total_bought_safe = df["total_bought"].mask(df["total_bought"] == 0)  # NaN (pas pd.NA) pour rester comparable en Jinja
    df["total_return_pct"] = (df["total_gain"] / total_bought_safe) * 100

    months_held = (today - df["first_buy_date"]).dt.days / DAYS_PER_MONTH
    df["months_held"] = months_held.clip(lower=1 / DAYS_PER_MONTH)  # évite la division par ~0 le jour même
    df["monthly_avg_pct"] = df["total_return_pct"] / df["months_held"]
    df["monthly_avg_eur"] = df["total_gain"] / df["months_held"]

    return df
