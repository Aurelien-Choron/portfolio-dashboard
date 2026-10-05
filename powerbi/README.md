# Power BI version (work in progress)

A rebuild of this dashboard in Power BI Desktop, on the same fictional demo data.
Power Query does the ETL from the raw broker exports, the model is a star schema,
and DAX measures replace the Python in `analytics/`. Every figure is reconciled
against the Python app rather than eyeballed against a screenshot.

The report is saved as a **Power BI Project (PBIP)**: the semantic model is stored as
TMDL and the report as PBIR, both plain text. That makes the Power Query code and
every DAX measure readable and diffable right here on GitHub.

## Files

| Path | What it is |
|---|---|
| `data/prices_daily.csv` | Daily EUR closes for the six demo assets, frozen on one date. Calling Yahoo Finance from Power Query is fragile, so prices are the one input exported from Python. |
| `data/expected_values.json` | The answer key: what the Python app computes on those same frozen prices (KPIs, per-asset table, value over time, net worth, strategy, forecast inputs). |
| `data/asset_classes.csv`, `data/brokers.csv` | Labels and colours that the app keeps in code, exported as dimension tables. |
| `theme/portfolio-dark.json`, `theme/portfolio-light.json` | Report themes generated from `dashboard/palette.py`, the app's single colour source. |

Everything else Power BI reads comes straight from `demo/`:

- the Fortuneo CSV (`;`, Windows-1252, DD/MM/YYYY dates);
- the Trade Republic CSV (`,`, UTF-8);
- the JSON config files.

Regenerate the files above with:

```bash
python scripts/export_powerbi.py   # refuses to run on anything but demo/
```

Note that this re-freezes prices at today's date, so the answer key moves with it.

## The model

| Dimension (one side) | Filters (many side) |
|---|---|
| `Date` | `Transactions`, `Prices` |
| `Asset` | `Transactions`, `Prices`, `Exposure` |
| `Broker` | `Asset` |
| `AssetClass` | `Asset`, `Account` |
| `Institution` | `Broker`, `Account` |

- **Facts.** `Transactions` is the normalized journal. `Prices` holds the daily closes.
- **Dimensions.** `Asset`, `Broker`, `AssetClass`, `Institution`, `Account`,
  `StrategyTarget` and a DAX `Date` table.
- **Relationships.** All are one-to-many and filter in one direction only.
- **Bridge.** `Exposure` splits a fund over countries and sectors with weights,
  since one cell cannot hold ten countries.

**The weighted-average cost is computed in Power Query, not DAX.** A sale's realized
gain depends on the average cost at that moment, which depends on every earlier trade.
That is a running state, and a DAX calculated column cannot read the row before it.

`CostBasisReplay` therefore folds each asset's trades with `List.Accumulate`, and tags
every row with what it did to its position:

- `qty_delta`;
- `cost_delta`;
- `realized_pnl`.

From there, every measure is a sum:

- quantity held at a date = running sum of `qty_delta`;
- cost basis = running sum of `cost_delta`;
- market value = quantity × last close on or before that date.

**Stock or flow.** Measures that describe a position, such as market value, cost basis
or invested capital, are read at the last day of the current filter. Measures that
count events, such as dividends, fees or realized P&L, are summed over the period.
That way the same measures serve both a KPI card and a monthly chart.

### Reconciliation

On the frozen prices, the measures match `expected_values.json` to the cent:

| Figure | Python app | Power BI |
|---|---|---|
| Market value | 19,856.09 | 19,856.09 |
| Cost basis | 15,226.37 | 15,226.37 |
| Unrealized P&L | +4,629.72 (+30.41 %) | +4,629.72 (+30.41 %) |
| Realized P&L | −224.19 | −224.19 |
| Dividends | 119.17 | 119.17 |
| Annual fund fees (TER) | 49.35 | 49.35 |
| Net worth | 46,056.09 | 46,056.09 |

The same holds for:

- the per-asset table: quantity, average cost, total return, monthly average;
- the split by broker, by asset class, by institution and by country;
- the month-end value curve.

**Data-quality note.** On Fortuneo, the net amount of a purchase *includes* brokerage.
On Trade Republic, the 1 € fee sits *outside* the amount. The app keeps this asymmetry
in the cost basis, and so does the report, because the goal is parity. A silent fix
would make the two disagree without anyone knowing why.

## Opening the report

You need Power BI Desktop, which is free (Windows). Open `PortfolioDashboard.pbip`,
then go to *Transform data → Edit parameters* and set `RepoPath` to your clone of this
repository. `DataSet` stays `demo`.

No Power BI licence is involved: the project is built and shared as files, not
published to the Power BI service.
