"""Génère un jeu de données 100% fictif dans demo/, avec la même structure que
data/ et config/ à la racine, pour alimenter la démo publique du dashboard.

Aucune donnée réelle de l'auteur n'est utilisée : portefeuille et comptes
inventés, mais construits sur de vrais tickers cotés (Apple, LVMH, Sanofi,
Coca-Cola, ETF Amundi MSCI World / Vanguard FTSE All-World) pour que la
démo affiche des prix live crédibles via yfinance.

Usage : python scripts/generate_demo_data.py
"""
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_DATA = os.path.join(ROOT, "demo", "data")
DEMO_CONFIG = os.path.join(ROOT, "demo", "config")

# --- Univers fictif ------------------------------------------------------
# Fortuneo (PEA) : identifié par nom (l'export Fortuneo ne donne pas l'ISIN).
FORTUNEO_ETF = "Amundi MSCI World UCITS ETF - EUR (C)"
FORTUNEO_STOCK = "Sanofi"

# Trade Republic (CTO) : identifié par ISIN.
TR_APPLE = ("US0378331005", "Apple Inc.")
TR_LVMH = ("FR0000121014", "LVMH")
TR_VWCE = ("IE00BK5BQT80", "Vanguard FTSE All-World UCITS ETF")
TR_KO = ("US1912161007", "Coca-Cola Co.")


def write_fortuneo_csv():
    path = os.path.join(DEMO_DATA, "fortuneo", "demo_historique_operations.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = ["libellé", "Opération", "Place", "Date", "Qté", "Prix d'éxé", "Montant brut", "Courtage/Prélèvement", "Montant net", "Devise", ""]

    def row(libelle, operation, date, qte, prix, brut, courtage, net):
        return [libelle, operation, "Euronext Paris", date, qte, prix, brut, courtage, net, "EUR", ""]

    rows = [
        row("", "Versement", "01/02/2024", "", "", "", "", "3000.00"),
        row(FORTUNEO_ETF, "Achat comptant", "05/02/2024", "40", "68.50", "2740.00", "2.90", "-2742.90"),
        row("", "Versement", "03/06/2024", "", "", "", "", "1500.00"),
        row(FORTUNEO_STOCK, "Achat comptant", "10/06/2024", "15", "92.30", "1384.50", "2.90", "-1387.40"),
        row("", "Versement", "04/11/2024", "", "", "", "", "2000.00"),
        row(FORTUNEO_ETF, "Achat comptant", "08/11/2024", "25", "78.20", "1955.00", "2.90", "-1957.90"),
        row(FORTUNEO_STOCK, "Encaissement coupons intérêt/dividende", "15/03/2025", "", "", "", "", "47.25"),
        row("", "Versement", "02/05/2025", "", "", "", "", "2500.00"),
        row(FORTUNEO_ETF, "Achat comptant", "07/05/2025", "28", "85.10", "2382.80", "2.90", "-2385.70"),
        row(FORTUNEO_STOCK, "Vente comptant", "12/09/2025", "5", "98.40", "492.00", "2.90", "489.10"),
        row(FORTUNEO_STOCK, "Encaissement coupons intérêt/dividende", "01/10/2025", "", "", "", "", "32.10"),
        row("", "Versement", "06/01/2026", "", "", "", "", "1800.00"),
        row(FORTUNEO_ETF, "Achat comptant", "12/01/2026", "15", "91.40", "1371.00", "2.90", "-1373.90"),
        row(FORTUNEO_STOCK, "Encaissement coupons intérêt/dividende", "02/04/2026", "", "", "", "", "28.50"),
        row("", "Versement", "01/06/2026", "", "", "", "", "1200.00"),
        row(FORTUNEO_STOCK, "Achat comptant", "15/06/2026", "8", "96.75", "774.00", "2.90", "-776.90"),
    ]

    with open(path, "w", newline="", encoding="cp1252") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(header)
        writer.writerows(rows)
    print(f"écrit {path}")


def write_trade_republic_csv():
    path = os.path.join(DEMO_DATA, "trade_republic", "demo_transactions.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    header = [
        "transaction_id", "datetime", "date", "account_type", "category", "type",
        "asset_class", "name", "symbol", "shares", "price", "amount", "fee", "tax", "currency",
    ]

    def row(tx_id, date, tx_type, category, asset_class, name, symbol, shares, price, amount, fee=0, tax=0):
        return [tx_id, f"{date}T09:00:00", date, "securities", category, tx_type, asset_class, name, symbol, shares, price, amount, fee, tax, "EUR"]

    rows = [
        row("demo-0001", "2024-03-01", "TRANSFER_INBOUND", "transfer", "", "", "", "", "", "", "2000.00"),
        row("demo-0002", "2024-03-04", "BUY", "trading", "stock", TR_APPLE[1], TR_APPLE[0], "6", "165.20", "-991.20", 1.00),
        row("demo-0003", "2024-03-04", "BUY", "trading", "etf", TR_VWCE[1], TR_VWCE[0], "10", "98.40", "-984.00", 1.00),
        row("demo-0004", "2024-07-10", "TRANSFER_INBOUND", "transfer", "", "", "", "", "", "", "1500.00"),
        row("demo-0005", "2024-07-15", "BUY", "trading", "stock", TR_LVMH[1], TR_LVMH[0], "2", "720.00", "-1440.00", 1.00),
        row("demo-0006", "2024-09-20", "DIVIDEND", "trading", "stock", TR_APPLE[1], TR_APPLE[0], "6", "", "14.40"),
        row("demo-0007", "2025-01-08", "TRANSFER_INBOUND", "transfer", "", "", "", "", "", "", "1800.00"),
        row("demo-0008", "2025-01-12", "BUY", "trading", "stock", TR_KO[1], TR_KO[0], "12", "58.30", "-699.60", 1.00),
        row("demo-0009", "2025-01-12", "BUY", "trading", "etf", TR_VWCE[1], TR_VWCE[0], "8", "101.90", "-815.20", 1.00),
        row("demo-0010", "2025-06-05", "DIVIDEND", "trading", "stock", TR_KO[1], TR_KO[0], "12", "", "9.12", 0, 1.60),
        row("demo-0011", "2025-09-14", "SELL", "trading", "stock", TR_LVMH[1], TR_LVMH[0], "1", "680.00", "680.00", 1.00),
        row("demo-0012", "2025-11-02", "DIVIDEND", "trading", "stock", TR_APPLE[1], TR_APPLE[0], "6", "", "16.80"),
        row("demo-0013", "2026-02-10", "TRANSFER_INBOUND", "transfer", "", "", "", "", "", "", "1000.00"),
        row("demo-0014", "2026-02-14", "BUY", "trading", "stock", TR_APPLE[1], TR_APPLE[0], "4", "195.50", "-782.00", 1.00),
        row("demo-0015", "2026-06-20", "DIVIDEND", "trading", "stock", TR_KO[1], TR_KO[0], "12", "", "10.08", 0, 1.76),
        row("demo-0016", "2026-07-05", "DIVIDEND", "trading", "stock", TR_LVMH[1], TR_LVMH[0], "1", "", "12.50"),
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(header)
        writer.writerows(rows)
    print(f"écrit {path}")


def write_accounts_json():
    path = os.path.join(DEMO_DATA, "accounts", "accounts.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {
        "_readme": "Comptes fictifs de démonstration — aucune donnée réelle.",
        "accounts": [
            {"label": "Livret A", "bank": "Banque Demo", "category": "Livrets", "balance": 8500, "rate_pct": 3.0, "ceiling": 22950},
            {"label": "LDDS", "bank": "Banque Demo", "category": "Livrets", "balance": 4200, "rate_pct": 3.0, "ceiling": 12000},
            {"label": "Assurance-vie — Fonds Euro", "bank": "Assureur Demo", "category": "Fonds Euros", "balance": 12000, "rate_pct": 2.6},
            {"label": "Compte courant", "bank": "Banque Demo", "category": "Autres", "balance": 1500},
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"écrit {path}")


def write_config():
    os.makedirs(DEMO_CONFIG, exist_ok=True)

    tickers = {
        "_readme": "Mapping asset_key -> ticker Yahoo Finance (démo).",
        FORTUNEO_ETF: "CW8.PA",
        FORTUNEO_STOCK: "SAN.PA",
        TR_APPLE[0]: "AAPL",
        TR_LVMH[0]: "MC.PA",
        TR_VWCE[0]: "VWCE.DE",
        TR_KO[0]: "KO",
    }

    fees = {
        "_readme": "TER annuel en % (démo). null = pas de frais de gestion (action en direct).",
        FORTUNEO_ETF: 0.38,
        FORTUNEO_STOCK: None,
        TR_APPLE[0]: None,
        TR_LVMH[0]: None,
        TR_VWCE[0]: 0.22,
        TR_KO[0]: None,
    }

    asset_classes = {
        "_readme": "Classe d'actif par asset_key (démo).",
        FORTUNEO_ETF: "Actions",
        FORTUNEO_STOCK: "Actions",
        TR_APPLE[0]: "Actions",
        TR_LVMH[0]: "Actions",
        TR_VWCE[0]: "Actions",
        TR_KO[0]: "Actions",
    }

    target_allocation = {
        "_readme": "Répartition cible du patrimoine total par classe d'actif, en % (démo, valeurs d'exemple).",
        "Actions": 45,
        "Obligations": 10,
        "Fonds Euros": 20,
        "Livrets": 20,
        "Autres": 5,
    }

    exposure = {
        "_readme": "Ventilation géographique/sectorielle par asset_key (démo, approximée sur factsheets publics).",
        FORTUNEO_ETF: {
            "country": {
                "États-Unis": 70.0, "Japon": 6.0, "Royaume-Uni": 4.0, "France": 3.0,
                "Allemagne": 2.5, "Suisse": 2.5, "Canada": 3.0, "Chine": 3.0, "Autres": 6.0,
            },
            "sector": {
                "Technologie": 27.0, "Financières": 16.0, "Industrie": 11.0, "Santé": 10.0,
                "Consommation discrétionnaire": 10.0, "Communication": 8.0, "Consommation de base": 6.0,
                "Énergie": 4.0, "Matériaux": 3.0, "Services publics": 2.5, "Immobilier": 2.5,
            },
        },
        FORTUNEO_STOCK: {"country": {"France": 100}, "sector": {"Santé": 100}},
        TR_APPLE[0]: {"country": {"États-Unis": 100}, "sector": {"Technologie": 100}},
        TR_LVMH[0]: {"country": {"France": 100}, "sector": {"Consommation discrétionnaire": 100}},
        TR_KO[0]: {"country": {"États-Unis": 100}, "sector": {"Consommation de base": 100}},
        TR_VWCE[0]: {
            "country": {
                "États-Unis": 62.0, "Japon": 5.5, "Royaume-Uni": 3.5, "Chine": 3.0, "France": 2.8,
                "Canada": 2.7, "Allemagne": 2.0, "Inde": 2.0, "Suisse": 2.0, "Taïwan": 1.8, "Autres": 12.7,
            },
            "sector": {
                "Technologie": 24.0, "Financières": 17.0, "Industrie": 12.0, "Santé": 10.0,
                "Consommation discrétionnaire": 10.5, "Communication": 7.5, "Consommation de base": 6.0,
                "Énergie": 4.5, "Matériaux": 3.5, "Services publics": 2.5, "Immobilier": 2.5,
            },
        },
    }

    for name, data in [
        ("tickers.json", tickers), ("fees.json", fees), ("asset_classes.json", asset_classes),
        ("target_allocation.json", target_allocation), ("exposure.json", exposure),
    ]:
        path = os.path.join(DEMO_CONFIG, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"écrit {path}")


if __name__ == "__main__":
    write_fortuneo_csv()
    write_trade_republic_csv()
    write_accounts_json()
    write_config()
    print("\nJeu de données de démo généré dans demo/. Pour tester : "
          "$env:PORTFOLIO_ROOT = (Resolve-Path demo); python dashboard/app.py")
