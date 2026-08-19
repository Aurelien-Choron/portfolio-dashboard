"""Calcul des positions ouvertes et du PnL réalisé par actif (coût moyen pondéré)."""

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Position:
    asset_key: str
    name: str
    isin: str | None
    broker: str
    currency: str
    quantity: float = 0.0
    cost_basis: float = 0.0  # coût total des titres actuellement détenus
    realized_pnl: float = 0.0
    dividends: float = 0.0
    fees_paid: float = 0.0
    trades: int = 0

    @property
    def avg_cost(self) -> float:
        return self.cost_basis / self.quantity if self.quantity > 1e-9 else 0.0


def build_positions(transactions: pd.DataFrame) -> dict[str, Position]:
    """Reconstruit les positions en rejouant les transactions dans l'ordre chronologique."""
    positions: dict[str, Position] = {}

    for _, row in transactions.sort_values("date").iterrows():
        key = row["asset_key"]
        if row["type"] not in {"BUY", "SELL", "DIVIDEND"} and pd.isna(row.get("quantity")):
            continue
        if key not in positions and row["type"] in {"BUY", "SELL", "DIVIDEND"}:
            positions[key] = Position(
                asset_key=key,
                name=row["name"] or key,
                isin=row["isin"],
                broker=row["broker"],
                currency=row["currency"] or "EUR",
            )

        pos = positions.get(key)
        if pos is None:
            continue

        fee = row["fee"] or 0.0
        pos.fees_paid += fee

        if row["type"] == "BUY":
            qty = row["quantity"] or 0.0
            cost = abs(row["amount"] or 0.0)  # inclut les frais déjà
            pos.quantity += qty
            pos.cost_basis += cost
            pos.trades += 1
        elif row["type"] == "SELL":
            # Trade Republic fournit une quantité déjà négative pour les ventes,
            # Fortuneo une quantité positive : on normalise avec abs() pour ne pas
            # additionner au lieu de soustraire selon le courtier.
            qty = abs(row["quantity"] or 0.0)
            proceeds = abs(row["amount"] or 0.0)
            avg_cost = pos.avg_cost
            cost_removed = avg_cost * qty
            pos.realized_pnl += proceeds - cost_removed
            pos.quantity -= qty
            pos.cost_basis -= cost_removed
            pos.trades += 1
            if pos.quantity < 1e-6:
                pos.quantity = 0.0
                pos.cost_basis = 0.0
        elif row["type"] == "DIVIDEND":
            pos.dividends += row["amount"] or 0.0

    return positions


def positions_frame(positions: dict[str, Position]) -> pd.DataFrame:
    if not positions:
        return pd.DataFrame(
            columns=[
                "asset_key", "name", "isin", "broker", "currency", "quantity",
                "avg_cost", "cost_basis", "realized_pnl", "dividends", "fees_paid", "trades",
            ]
        )
    rows = [
        {
            "asset_key": p.asset_key,
            "name": p.name,
            "isin": p.isin,
            "broker": p.broker,
            "currency": p.currency,
            "quantity": p.quantity,
            "avg_cost": p.avg_cost,
            "cost_basis": p.cost_basis,
            "realized_pnl": p.realized_pnl,
            "dividends": p.dividends,
            "fees_paid": p.fees_paid,
            "trades": p.trades,
        }
        for p in positions.values()
    ]
    return pd.DataFrame(rows)
