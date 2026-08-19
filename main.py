"""Import les CSV Fortuneo/Trade Republic, normalise et affiche un résumé.

Usage : python main.py
Le dashboard se lance séparément avec : python dashboard/app.py
"""

from analytics import kpis, positions as positions_mod
from importers import normalize
from paths import data_root

DATA_ROOT = data_root()


def _fr(value: float, signed: bool = False) -> str:
    """Formate un montant à la française : espace comme séparateur de milliers (10 000 et non 10,000)."""
    fmt = f"{{:{'+' if signed else ''},.0f}}"
    return fmt.format(value).replace(",", " ")


def main():
    transactions = normalize.load_all(DATA_ROOT)

    if transactions.empty:
        print("Aucun fichier CSV trouvé dans data/fortuneo/ ou data/trade_republic/.")
        return

    out_path = normalize.save_processed(transactions, DATA_ROOT)
    print(f"{len(transactions)} transactions importées -> {out_path}")

    pos_dict = positions_mod.build_positions(transactions)
    pos_df = positions_mod.positions_frame(pos_dict)
    pos_df = kpis.enrich_with_prices(pos_df)
    summary = kpis.summary(pos_df, transactions)

    print("\n--- Résumé du portefeuille ---")
    print(f"Positions ouvertes         : {summary['nb_positions']} ({summary['nb_prix_live']} avec prix live)")
    print(f"Coût des positions         : {_fr(summary['total_cost'])} €")
    print(f"Valeur actuelle            : {_fr(summary['total_value'])} €")
    print(f"Plus-value latente         : {_fr(summary['unrealized_pnl'], signed=True)} € ({summary['unrealized_pnl_pct']:+.1f} %) [gain/perte sur les positions non vendues]")
    print(f"Plus-value réalisée        : {_fr(summary['realized_pnl'], signed=True)} € [gain/perte déjà encaissé sur les ventes]")
    print(f"Dividendes perçus          : {_fr(summary['dividends'])} € [hors intérêts du compte courant, sans lien avec la bourse]")
    print(f"Frais totaux               : {_fr(summary['fees'])} €")
    print("\nLance le dashboard avec : python dashboard/app.py")


if __name__ == "__main__":
    main()
