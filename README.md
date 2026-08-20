# 📊 Portfolio Dashboard

A stock portfolio analysis dashboard built from broker CSV exports (Fortuneo,
Trade Republic). Rebuilds positions and PnL from the raw transaction journal
(no broker API), computes dividends, management fees, geographic/sector
diversification, and compares total net worth (investments + savings) against
a target allocation.

**[➡ Live demo](https://à-compléter-après-déploiement.onrender.com)**
*(100% fictional data — see [Privacy](#privacy) below. The free-tier service
sleeps after 15 min of inactivity: the first load can take ~30s.)*

## Features

- **Position reconstruction** at weighted average cost from the raw journal
  (buys/sells/dividends), with no dependency on a broker API.
- **Live prices** via [yfinance](https://pypi.org/project/yfinance/) for
  mapped assets (`config/tickers.json`), with an explicit fallback to average
  purchase price for the rest — never an invented price.
- **Investments view**: performance over time, asset ranking, allocation by
  broker, geographic/sector diversification, annual management fees,
  transaction/dividend activity log.
- **Net Worth view**: investments + savings accounts (regulated savings,
  retirement plans, life insurance...), comparison against a target allocation
  with gaps highlighted.
- **Installable PWA** on a phone (home-screen icon, full screen), built
  mobile-first (tap-friendly lists, compact charts, tab navigation).

## Architecture

```
portfolio-dashboard/
├── data/                    # REAL data — never committed (.gitignore)
│   ├── fortuneo/             # Fortuneo "transaction history" exports
│   ├── trade_republic/       # Trade Republic "transactions_*.csv" exports
│   ├── accounts/accounts.json  # Savings accounts, entered by hand
│   └── processed/            # Normalized transactions.csv (generated)
├── config/                  # Personal mappings — never committed (.gitignore)
│   ├── tickers.json          # asset_key -> Yahoo Finance ticker
│   ├── fees.json              # asset_key -> annual TER (%)
│   ├── asset_classes.json     # asset_key -> asset class
│   ├── target_allocation.json # target net worth allocation (%)
│   └── exposure.json          # asset_key -> country/sector breakdown
├── demo/                    # 100% FICTIONAL equivalent of data/ + config/,
│   │                          committed for the public demo
│   └── ...                   # same layout as data/ and config/
├── scripts/
│   └── generate_demo_data.py # (Re)generates demo/ from scratch
├── importers/
│   ├── fortuneo.py            # Fortuneo parser (CSV ';', cp1252)
│   ├── trade_republic.py      # Trade Republic parser (CSV ',', UTF-8)
│   ├── corrections.py         # Manual corrective buys (incomplete history)
│   └── normalize.py           # Merges every source into one common journal
├── analytics/
│   ├── positions.py           # Weighted average cost + realized PnL
│   ├── kpis.py                 # Global KPI aggregation
│   ├── performance.py          # Portfolio value over time
│   ├── performance_by_asset.py # Per-asset performance
│   ├── patrimoine.py           # Net worth view (investments + savings)
│   └── exposure.py             # Geographic/sector diversification
├── market_data.py            # Live prices via yfinance (+ disk cache)
├── paths.py                  # data/config resolution, override via PORTFOLIO_ROOT
├── dashboard/
│   ├── app.py                  # Flask server + Plotly chart generation
│   └── templates/               # base.html, index.html (Investments), patrimoine.html
├── wsgi.py                    # gunicorn entry point (deployment)
├── main.py                    # CSV import + command-line summary
├── Procfile / render.yaml     # Render deployment
└── requirements.txt
```

## Setup (with your own data)

```bash
pip install -r requirements.txt
```

1. Drop your CSV exports into `data/fortuneo/` and `data/trade_republic/`
   (multiple files per folder are supported, deduplicated automatically).
2. Fill in `data/accounts/accounts.json` with your savings accounts (see
   `analytics/patrimoine.py` for the expected schema).
3. (Optional but recommended) Fill in `config/tickers.json` with the Yahoo
   Finance ticker of every asset you hold, to get live prices instead of the
   average purchase price. Check each ticker on
   [finance.yahoo.com](https://finance.yahoo.com) before entering it — a wrong
   ticker would skew the valuation.
4. Fill in `config/asset_classes.json`, `config/fees.json`,
   `config/target_allocation.json`, and `config/exposure.json` using the same keys.
5. Run the command-line summary:
   ```bash
   python main.py
   ```
6. Start the dashboard:
   ```bash
   python dashboard/app.py
   ```
   Then open **http://localhost:5050** (also reachable from the same Wi-Fi
   via the IP printed at startup — handy for testing on a phone).

## Demo mode (no personal data)

The app can run entirely on a fictional dataset, via the `PORTFOLIO_ROOT`
environment variable, which redirects `data/` and `config/` to another
directory with the same layout:

```bash
# Windows PowerShell
$env:PORTFOLIO_ROOT = "demo"; python dashboard/app.py
# macOS / Linux
PORTFOLIO_ROOT=demo python dashboard/app.py
```

The contents of `demo/` are generated by `scripts/generate_demo_data.py` — a
fully invented portfolio and set of accounts, built on real, publicly traded
tickers (Apple, LVMH, Sanofi, Coca-Cola, world-equity ETFs) so live prices stay
credible. This is the folder that powers the public deployment.

## Deployment (Render)

The repo includes a ready-to-use `render.yaml`:

1. Create a [Render](https://render.com) account and connect the GitHub repo.
2. **New +** → **Blueprint**, select this repo — Render reads `render.yaml`
   and configures the service automatically (`gunicorn wsgi:app`,
   `PORTFOLIO_ROOT=demo`).
3. Deploy. The free plan sleeps after 15 min of inactivity (slower first load
   after a pause).

The Flask dev server (`python dashboard/app.py`) is **not** used in
production — `wsgi.py` + `gunicorn` handle that.

## Supported CSV formats

### Fortuneo — "Historique des opérations bourse"
CSV `;`-separated, Windows-1252 encoding, columns: `libellé;Opération;Place;Date;Qté;Prix
d'éxé;Montant brut;Courtage/Prélèvement;Montant net;Devise`. (Column names are
in French because they mirror Fortuneo's own real export format.)

### Trade Republic — "Transactions" export
CSV `,`-separated with quotes, UTF-8, columns: `datetime,date,account_type,category,
type,asset_class,name,symbol,shares,price,amount,fee,tax,currency,...`. The
`symbol` field actually holds the ISIN.

## Calculation notes

- **Weighted average cost**: every buy increases the quantity and total cost
  held; every sell removes the sold quantity at the current average cost and
  triggers the corresponding realized PnL.
- **Fortuneo dividends**: only rows labeled `Encaissement coupons
  intérêt/dividende` count as a real dividend. Rows labeled `OST de création de
  coupons` / `ANNUL. OST...` (technical bookkeeping entries tied to optional
  coupon detachment) are kept in the journal but excluded from the totals,
  since their exact accounting treatment isn't certain — worth double-checking
  against the Fortuneo statement if cent-level precision is needed.
- **Net invested capital** (performance chart) = net cash flow into
  investments (purchases − sale proceeds), not the strict accounting cost
  basis of open positions.
- **Historical prices**: for assets without a mapped ticker, the price history
  is approximated by the current average purchase price (a flat line) — the
  performance curve is therefore only reliable for assets mapped in
  `config/tickers.json`.

## Privacy

No personal data is ever sent anywhere or committed to Git:

- `data/fortuneo/*.csv`, `data/trade_republic/*.csv`, `data/processed/*.csv`,
  `data/accounts/`, `data/corrections/*.csv`, and every file under
  `config/*.json` (tickers, fees, asset classes, target allocation, exposure —
  they reveal the exact composition of the real portfolio) are excluded via
  `.gitignore`.
- The public demo runs exclusively on `demo/`, a fictional dataset committed
  on purpose (see [Demo mode](#demo-mode-no-personal-data)).
- All computation runs locally (or on the deployment instance you control);
  the only outbound network call is to Yahoo Finance for prices.
