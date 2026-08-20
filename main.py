"""Imports the Fortuneo/Trade Republic CSVs, normalizes them, and prints a summary.

Usage: python main.py
The dashboard is started separately with: python dashboard/app.py
"""

from analytics import kpis, positions as positions_mod
from importers import normalize
from paths import data_root

DATA_ROOT = data_root()


def _fmt(value: float, signed: bool = False) -> str:
    """Formats an amount with a space as the thousands separator (10 000, not 10,000)."""
    fmt = f"{{:{'+' if signed else ''},.0f}}"
    return fmt.format(value).replace(",", " ")


def main():
    transactions = normalize.load_all(DATA_ROOT)

    if transactions.empty:
        print("No CSV file found in data/fortuneo/ or data/trade_republic/.")
        return

    out_path = normalize.save_processed(transactions, DATA_ROOT)
    print(f"{len(transactions)} transactions imported -> {out_path}")

    pos_dict = positions_mod.build_positions(transactions)
    pos_df = positions_mod.positions_frame(pos_dict)
    pos_df = kpis.enrich_with_prices(pos_df)
    summary = kpis.summary(pos_df, transactions)

    print("\n--- Portfolio summary ---")
    print(f"Open positions              : {summary['nb_positions']} ({summary['nb_prix_live']} with a live price)")
    print(f"Cost of positions            : {_fmt(summary['total_cost'])} €")
    print(f"Current value                : {_fmt(summary['total_value'])} €")
    print(f"Unrealized gain/loss         : {_fmt(summary['unrealized_pnl'], signed=True)} € ({summary['unrealized_pnl_pct']:+.1f} %) [gain/loss on positions not yet sold]")
    print(f"Realized gain/loss           : {_fmt(summary['realized_pnl'], signed=True)} € [gain/loss already booked on sales]")
    print(f"Dividends received           : {_fmt(summary['dividends'])} € [excludes checking-account interest, unrelated to investments]")
    print(f"Total fees                   : {_fmt(summary['fees'])} €")
    print("\nStart the dashboard with: python dashboard/app.py")


if __name__ == "__main__":
    main()
