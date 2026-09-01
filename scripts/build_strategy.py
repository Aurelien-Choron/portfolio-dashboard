"""Computes the risk analytics behind the Strategy page.

Reads the hand-edited policy (config/strategy.json) and writes the measured
figures to config/strategy_analytics.json: per-line volatility, beta, correlation
and covariance, the constrained efficient frontier, the tangency portfolio, and
the stress scenarios. The Flask app only reads that output — nothing here runs at
page load.

This is the only part of the project that needs scipy:
    pip install -r requirements-strategy.txt

Usage: python scripts/build_strategy.py
"""
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import market_data
from analytics import strategy as strategy_mod
from paths import config_root

try:
    from scipy.optimize import minimize
except ImportError:
    sys.exit(
        "scipy is required by this script (and by nothing else in the project).\n"
        "Install it with:  pip install -r requirements-strategy.txt"
    )

OUT_PATH = os.path.join(config_root(), "strategy_analytics.json")
WEEKS = 52
TRADING_KEY = "__TRADING__"
CASH_KEY = "__CASH__"


def _weekly_returns(series_by_key: dict, start: str) -> pd.DataFrame:
    """Weekly (Friday) returns in EUR, over the window every line shares."""
    frame = pd.DataFrame(series_by_key).sort_index().loc[start:]
    weekly = frame.resample("W-FRI").last().ffill(limit=2)
    return weekly.pct_change().dropna(how="any")


def _shrink(corr: np.ndarray, delta: float) -> np.ndarray:
    """Ledoit-Wolf style shrinkage toward the average correlation.

    Raw sample correlations push a mean-variance optimiser into corner solutions:
    a tenth of a point of expected return can swing a weight from 0 % to its cap.
    Pulling every pair toward the mean keeps the frontier stable.
    """
    n = corr.shape[0]
    off_diag = corr[~np.eye(n, dtype=bool)]
    target = np.full((n, n), off_diag.mean())
    np.fill_diagonal(target, 1.0)
    return (1 - delta) * corr + delta * target


def _resolve_series(policy: dict) -> tuple:
    """Downloads every line's EUR history, substituting the configured proxies.

    Returns (series_by_key, meta_by_key). A line too recent to carry a statistic
    borrows a long-history index that was validated by correlation against it —
    see the 'proxies' block in config/strategy.json.
    """
    assumptions = policy["assumptions"]
    proxies = strategy_mod._strip_readme(assumptions.get("proxies") or {})
    benchmark = assumptions["benchmark_ticker"]

    lines = [t for t in policy["targets"] if t["key"] != CASH_KEY]
    sleeve_members = (policy.get("trading_sleeve") or {}).get("members") or []
    tickers_map = market_data.load_ticker_map()

    wanted, meta = {}, {}
    for t in lines:
        ticker = t.get("ticker")
        if not ticker:
            continue
        proxy, reason = proxies.get(ticker, (ticker, None))
        wanted[t["key"]] = proxy
        meta[t["key"]] = {
            "label": t.get("label", t["key"]), "ticker": ticker, "proxy": proxy,
            "proxy_reason": reason, "envelope": t.get("envelope"), "role": t.get("role"),
        }

    sleeve_tickers = [tickers_map[m] for m in sleeve_members if m in tickers_map]
    to_download = sorted(set(list(wanted.values()) + sleeve_tickers + [benchmark]))

    print(f"Downloading {len(to_download)} EUR price series...", flush=True)
    history = market_data.fetch_ticker_history(to_download, pd.Timestamp(assumptions["window_start"]))
    missing = [t for t in to_download if t not in history]
    if missing:
        print(f"  WARNING — no data for: {', '.join(missing)}", flush=True)

    series = {k: history[v] for k, v in wanted.items() if v in history}
    for k in list(meta):
        if k not in series:
            print(f"  WARNING — dropping '{meta[k]['label']}' (no price history)", flush=True)
            meta.pop(k)

    # The trading sleeve enters the risk model as one synthetic asset: an
    # equal-weight basket of its current members. It is a budget, not a target,
    # so it is never optimised — only measured.
    basket = [history[t] for t in sleeve_tickers if t in history]
    if basket:
        rets = pd.DataFrame({f"m{i}": s for i, s in enumerate(basket)}).sort_index()
        series[TRADING_KEY] = (1 + rets.pct_change().fillna(0).mean(axis=1)).cumprod()
        meta[TRADING_KEY] = {
            "label": "Trading sleeve", "ticker": "basket", "proxy": ", ".join(sleeve_tickers),
            "proxy_reason": f"Equal-weight basket of the {len(basket)} positions currently held",
            "envelope": (policy.get("trading_sleeve") or {}).get("preferred_envelope"),
            "role": "trading",
        }
    return series, meta, history.get(benchmark)


def main():
    policy = strategy_mod.load_policy()
    if policy is None:
        sys.exit(f"No strategy found at {strategy_mod.POLICY_PATH} — nothing to compute.")

    assumptions = policy["assumptions"]
    rf_gross = assumptions["risk_free_gross_pct"] / 100
    rf_net = assumptions["risk_free_net_pct"] / 100
    erp = assumptions["equity_risk_premium_pct"] / 100
    tilts = strategy_mod._strip_readme(assumptions.get("valuation_tilt_pct") or {})
    absolutes = strategy_mod._strip_readme(assumptions.get("absolute_return_pct") or {})
    envelopes = policy.get("envelopes") or {}

    series, meta, bench = _resolve_series(policy)
    if bench is None or len(series) < 2:
        sys.exit("Not enough price history to compute anything — check the tickers.")

    bench_key = "__BENCH__"
    rets = _weekly_returns({**series, bench_key: bench}, assumptions["window_start"])
    keys = [k for k in series if k in rets.columns]
    market = rets[bench_key]
    var_m = market.var(ddof=1)

    print(f"{len(rets)} weekly observations, {rets.index[0].date()} -> {rets.index[-1].date()}", flush=True)

    vols, betas, cagrs, dds, corr_m = {}, {}, {}, {}, {}
    for k in keys:
        r = rets[k]
        vols[k] = float(r.std(ddof=1) * np.sqrt(WEEKS))
        betas[k] = float(r.cov(market) / var_m)
        cagrs[k] = float((1 + r).prod() ** (WEEKS / len(r)) - 1)
        cum = (1 + r).cumprod()
        dds[k] = float((cum / cum.cummax() - 1).min())
        corr_m[k] = float(r.corr(market))

    # Expected returns: CAPM plus an explicit valuation tilt, then net of the
    # envelope's tax rate — the only figure that reaches the investor.
    exp_gross, exp_net = {}, {}
    for k in keys:
        if k in absolutes:
            gross = absolutes[k] / 100
        else:
            gross = rf_gross + betas[k] * erp + tilts.get(k, 0.0) / 100
        exp_gross[k] = gross
        tax = (envelopes.get(meta[k].get("envelope") or "", {}) or {}).get("tax_pct")
        exp_net[k] = gross * (1 - (tax or 0.0) / 100)

    corr = rets[keys].corr()
    shrunk = _shrink(corr.values, assumptions.get("shrinkage", 0.15))
    vol_vec = np.array([vols[k] for k in keys])
    cov = pd.DataFrame(np.outer(vol_vec, vol_vec) * shrunk, index=keys, columns=keys)

    # ---- efficient frontier over the investable lines only ------------------
    inv = [k for k in keys if meta[k]["role"] in ("core", "diversifier")]
    S = cov.loc[inv, inv].values
    mu = np.array([exp_net[k] for k in inv])
    n = len(inv)
    gold = [i for i, k in enumerate(inv) if meta[k]["role"] == "diversifier"]
    pvol = lambda w: float(np.sqrt(w @ S @ w))

    def solve(target_vol=None, max_sharpe=False):
        cons = [{"type": "eq", "fun": lambda w: w.sum() - 1}]
        if gold:
            # Gold's 5 % floor is a robustness decision, not an optimiser output:
            # at a 0.09 beta it is the only real diversifier here, and mean-variance
            # drops it as soon as its expected return looks unexciting.
            cons.append({"type": "ineq", "fun": lambda w: sum(w[i] for i in gold) - 0.05})
        if target_vol is not None:
            cons.append({"type": "eq", "fun": lambda w, t=target_vol: pvol(w) - t})
            obj = lambda w: -float(w @ mu)
        elif max_sharpe:
            obj = lambda w: -(float(w @ mu) - rf_net) / pvol(w)
        else:
            obj = pvol
        best, best_val = None, np.inf
        for seed in range(8):
            rng = np.random.default_rng(seed)
            w0 = rng.dirichlet(np.ones(n)) if seed else np.full(n, 1 / n)
            res = minimize(obj, w0, method="SLSQP", bounds=[(0.0, 1.0)] * n,
                           constraints=cons, options={"maxiter": 800, "ftol": 1e-12})
            if res.success and res.fun < best_val:
                best_val, best = res.fun, res.x
        return None if best is None else np.where(best < 5e-4, 0, best)

    print("Solving the efficient frontier...", flush=True)
    w_min = solve()
    tangency_w = solve(max_sharpe=True)
    frontier = []
    if w_min is not None:
        for tv in np.linspace(pvol(w_min), max(vol_vec[[inv.index(k) for k in inv]]) * 0.99, 28):
            w = solve(target_vol=tv)
            if w is not None and abs(pvol(w) - tv) < 1e-3:
                frontier.append({"vol_pct": round(pvol(w) * 100, 3),
                                 "ret_pct": round(float(w @ mu) * 100, 3)})
    frontier = sorted({f["vol_pct"]: f for f in frontier}.values(), key=lambda f: f["vol_pct"])

    tangency = None
    if tangency_w is not None:
        tv, tr = pvol(tangency_w), float(tangency_w @ mu)
        tangency = {
            "vol_pct": round(tv * 100, 3), "ret_pct": round(tr * 100, 3),
            "sharpe": round((tr - rf_net) / tv, 3),
            "beta": round(float(sum(tangency_w[i] * betas[k] for i, k in enumerate(inv))), 3),
            "weights": {meta[k]["label"]: round(float(tangency_w[i]) * 100, 2)
                        for i, k in enumerate(inv) if tangency_w[i] > 0.001},
        }

    # ---- the target portfolio, as defined by the policy ---------------------
    sleeve_cap = float((policy.get("trading_sleeve") or {}).get("cap_pct") or 0.0)
    target_w = {t["key"]: float(t.get("target_pct") or 0.0) / 100
                for t in policy["targets"] if t["key"] != CASH_KEY}
    if sleeve_cap and TRADING_KEY in keys:
        target_w[TRADING_KEY] = sleeve_cap / 100
    cash_w = 1.0 - sum(target_w.values())

    def portfolio_stats(weights: dict) -> dict:
        ks = [k for k in keys if weights.get(k, 0) > 0]
        w = np.array([weights[k] for k in ks])
        sub = cov.loc[ks, ks].values
        vol = float(np.sqrt(w @ sub @ w))
        cash = 1.0 - float(w.sum())
        ret = float(sum(weights[k] * exp_net[k] for k in ks)) + cash * rf_net
        return {
            "vol_pct": round(vol * 100, 3), "ret_pct": round(ret * 100, 3),
            "beta": round(float(sum(weights[k] * betas[k] for k in ks)), 3),
            "sharpe": round((ret - rf_net) / vol, 3) if vol else None,
            "invested_pct": round(float(w.sum()) * 100, 2),
            "cash_pct": round(cash * 100, 2),
        }

    target_stats = portfolio_stats(target_w)

    # ---- stress scenarios ---------------------------------------------------
    scenarios = strategy_mod._strip_readme(policy.get("stress_scenarios") or {})
    stress = []
    for name, shocks in scenarios.items():
        loss = sum(target_w.get(k, 0.0) * (shocks.get(k, 0.0) / 100) for k in target_w)
        loss += cash_w * (shocks.get(CASH_KEY, 0.0) / 100)
        stress.append({"scenario": name, "target_pct": round(loss * 100, 2),
                       "shocks": {meta[k]["label"]: shocks.get(k) for k in keys if k in shocks}})

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window": {
            "start": str(rets.index[0].date()), "end": str(rets.index[-1].date()),
            "observations": int(len(rets)), "frequency": "weekly", "currency": "EUR",
        },
        "benchmark": {"ticker": assumptions["benchmark_ticker"],
                      "label": assumptions["benchmark_label"]},
        "risk_free_net_pct": assumptions["risk_free_net_pct"],
        "risk_free_gross_pct": assumptions["risk_free_gross_pct"],
        "equity_risk_premium_pct": assumptions["equity_risk_premium_pct"],
        "inflation_pct": assumptions["inflation_pct"],
        "assets": [
            {
                "key": k, "label": meta[k]["label"], "ticker": meta[k]["ticker"],
                "proxy": meta[k]["proxy"] if meta[k]["proxy"] != meta[k]["ticker"] else None,
                "proxy_reason": meta[k]["proxy_reason"], "role": meta[k]["role"],
                "envelope": meta[k]["envelope"],
                "vol_pct": round(vols[k] * 100, 2), "beta": round(betas[k], 3),
                "corr_market": round(corr_m[k], 3),
                "cagr_hist_pct": round(cagrs[k] * 100, 2),
                "max_dd_pct": round(dds[k] * 100, 1),
                "expected_gross_pct": round(exp_gross[k] * 100, 2),
                "expected_net_pct": round(exp_net[k] * 100, 2),
                "sharpe_net": round((exp_net[k] - rf_net) / vols[k], 3) if vols[k] else None,
            }
            for k in keys
        ],
        "correlation": {
            "labels": [meta[k]["label"] for k in keys],
            "keys": keys,
            "matrix": [[round(float(corr.loc[a, b]) * 100) for b in keys] for a in keys],
        },
        "covariance": {
            "keys": keys,
            "matrix": [[float(cov.loc[a, b]) for b in keys] for a in keys],
        },
        "frontier": frontier,
        "tangency": tangency,
        "target_portfolio": target_stats,
        "stress": stress,
    }

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)

    print(f"\nWritten -> {OUT_PATH}")
    print(f"  Target portfolio : {target_stats['ret_pct']:.2f} % net | "
          f"vol {target_stats['vol_pct']:.2f} % | beta {target_stats['beta']:.3f} | "
          f"Sharpe {target_stats['sharpe']}")
    if tangency:
        print(f"  Tangency         : {tangency['ret_pct']:.2f} % net | "
              f"vol {tangency['vol_pct']:.2f} % | Sharpe {tangency['sharpe']}")
    for s in stress:
        print(f"  {s['scenario']:<38} {s['target_pct']:+.1f} %")


if __name__ == "__main__":
    main()
