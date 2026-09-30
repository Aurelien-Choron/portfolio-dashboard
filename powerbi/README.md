# Power BI version (work in progress)

A rebuild of this dashboard in Power BI Desktop, on the same fictional demo data.
Power Query does the ETL from the raw broker exports, the model is a star schema,
and DAX measures replace the Python in `analytics/`. Every figure is reconciled
against the Python app rather than eyeballed against a screenshot.

The report is saved as a **Power BI Project (PBIP)**: the semantic model is stored as
TMDL and the report as PBIR, both plain text. That makes the Power Query code and
every DAX measure readable and diffable right here on GitHub.

## What is here so far

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

## Opening the report

You need Power BI Desktop, which is free (Windows). Open `PortfolioDashboard.pbip`,
then go to *Transform data → Edit parameters* and set `RepoPath` to your clone of this
repository. `DataSet` stays `demo`.

No Power BI licence is involved: the project is built and shared as files, not
published to the Power BI service.
