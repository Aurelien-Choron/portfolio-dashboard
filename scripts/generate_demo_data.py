"""Generates a 100% fictional dataset in demo/, with the same layout as the
root data/ and config/, to power the dashboard's public demo.

No real data from the author is used: the portfolio and accounts are invented,
but built on real, publicly traded tickers (Apple, LVMH, Sanofi, Coca-Cola,
Amundi MSCI World / Vanguard FTSE All-World ETFs) so the demo shows credible
live prices via yfinance.

Usage: python scripts/generate_demo_data.py
"""
import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO_DATA = os.path.join(ROOT, "demo", "data")
DEMO_CONFIG = os.path.join(ROOT, "demo", "config")

# --- Fictional universe ---------------------------------------------------
# Fortuneo (French tax-advantaged account, "PEA"): identified by name (the
# Fortuneo export doesn't provide an ISIN).
FORTUNEO_ETF = "Amundi MSCI World UCITS ETF - EUR (C)"
FORTUNEO_STOCK = "Sanofi"

# Trade Republic (standard brokerage account): identified by ISIN.
TR_APPLE = ("US0378331005", "Apple Inc.")
TR_LVMH = ("FR0000121014", "LVMH")
TR_VWCE = ("IE00BK5BQT80", "Vanguard FTSE All-World UCITS ETF")
TR_KO = ("US1912161007", "Coca-Cola Co.")


def write_fortuneo_csv():
    path = os.path.join(DEMO_DATA, "fortuneo", "demo_historique_operations.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Column names and operation labels ("Achat comptant", "Versement", ...) are
    # kept in French on purpose: they must match Fortuneo's own real CSV export
    # format byte-for-byte (see importers/fortuneo.py's OPERATION_MAP) — this is
    # a broker file format, not app-facing text, so it isn't part of the "make
    # everything English" scope.
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
    print(f"wrote {path}")


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
    print(f"wrote {path}")


def write_accounts_json():
    path = os.path.join(DEMO_DATA, "accounts", "accounts.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # "category" values (Livrets, Fonds Euros, Autres) intentionally match the
    # French taxonomy used internally by analytics/patrimoine.py — see the note
    # at the top of that file for why it isn't translated.
    # Account "label" values: Livret A / LDDS are the actual French regulated
    # savings-account product names (comparable to keeping "Roth IRA" or "401(k)"
    # untranslated in an English portfolio piece) — kept as-is since there's no
    # direct English equivalent. Generic ones (checking account) are translated.
    data = {
        "_readme": "Fictional demo accounts — no real data.",
        "accounts": [
            {"label": "Livret A", "bank": "Demo Bank", "category": "Livrets", "balance": 8500, "rate_pct": 3.0, "ceiling": 22950},
            {"label": "LDDS", "bank": "Demo Bank", "category": "Livrets", "balance": 4200, "rate_pct": 3.0, "ceiling": 12000},
            {"label": "Life Insurance — Euro Fund", "bank": "Demo Insurer", "category": "Fonds Euros", "balance": 12000, "rate_pct": 2.6},
            {"label": "Checking Account", "bank": "Demo Bank", "category": "Autres", "balance": 1500},
        ],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"wrote {path}")


def write_config():
    os.makedirs(DEMO_CONFIG, exist_ok=True)

    tickers = {
        "_readme": "Mapping of asset_key -> Yahoo Finance ticker (demo).",
        FORTUNEO_ETF: "CW8.PA",
        FORTUNEO_STOCK: "SAN.PA",
        TR_APPLE[0]: "AAPL",
        TR_LVMH[0]: "MC.PA",
        TR_VWCE[0]: "VWCE.DE",
        TR_KO[0]: "KO",
    }

    fees = {
        "_readme": "Annual TER in % (demo). null = no management fee (individual stock).",
        FORTUNEO_ETF: 0.38,
        FORTUNEO_STOCK: None,
        TR_APPLE[0]: None,
        TR_LVMH[0]: None,
        TR_VWCE[0]: 0.22,
        TR_KO[0]: None,
    }

    # Values intentionally match the French taxonomy used internally (see the
    # note at the top of analytics/patrimoine.py) — "Actions" here means "Stocks".
    asset_classes = {
        "_readme": "Asset class per asset_key (demo).",
        FORTUNEO_ETF: "Actions",
        FORTUNEO_STOCK: "Actions",
        TR_APPLE[0]: "Actions",
        TR_LVMH[0]: "Actions",
        TR_VWCE[0]: "Actions",
        TR_KO[0]: "Actions",
    }

    target_allocation = {
        "_readme": "Target allocation of total net worth by asset class, in % (demo, example values).",
        "Actions": 45,
        "Obligations": 10,
        "Fonds Euros": 20,
        "Livrets": 20,
        "Autres": 5,
    }

    exposure = {
        "_readme": "Geographic/sector breakdown per asset_key (demo, approximated from public factsheets).",
        FORTUNEO_ETF: {
            "country": {
                "United States": 70.0, "Japan": 6.0, "United Kingdom": 4.0, "France": 3.0,
                "Germany": 2.5, "Switzerland": 2.5, "Canada": 3.0, "China": 3.0, "Other": 6.0,
            },
            "sector": {
                "Technology": 27.0, "Financials": 16.0, "Industrials": 11.0, "Healthcare": 10.0,
                "Consumer Discretionary": 10.0, "Communication": 8.0, "Consumer Staples": 6.0,
                "Energy": 4.0, "Materials": 3.0, "Utilities": 2.5, "Real Estate": 2.5,
            },
        },
        FORTUNEO_STOCK: {"country": {"France": 100}, "sector": {"Healthcare": 100}},
        TR_APPLE[0]: {"country": {"United States": 100}, "sector": {"Technology": 100}},
        TR_LVMH[0]: {"country": {"France": 100}, "sector": {"Consumer Discretionary": 100}},
        TR_KO[0]: {"country": {"United States": 100}, "sector": {"Consumer Staples": 100}},
        TR_VWCE[0]: {
            "country": {
                "United States": 62.0, "Japan": 5.5, "United Kingdom": 3.5, "China": 3.0, "France": 2.8,
                "Canada": 2.7, "Germany": 2.0, "India": 2.0, "Switzerland": 2.0, "Taiwan": 1.8, "Other": 12.7,
            },
            "sector": {
                "Technology": 24.0, "Financials": 17.0, "Industrials": 12.0, "Healthcare": 10.0,
                "Consumer Discretionary": 10.5, "Communication": 7.5, "Consumer Staples": 6.0,
                "Energy": 4.5, "Materials": 3.5, "Utilities": 2.5, "Real Estate": 2.5,
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
        print(f"wrote {path}")


if __name__ == "__main__":
    write_fortuneo_csv()
    write_trade_republic_csv()
    write_accounts_json()
    write_config()
    print("\nDemo dataset generated in demo/. To try it: "
          "$env:PORTFOLIO_ROOT = (Resolve-Path demo); python dashboard/app.py")
