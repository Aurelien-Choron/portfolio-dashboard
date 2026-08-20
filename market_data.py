"""Fetches market prices via yfinance, from the config/tickers.json mapping.

The mapping associates an asset_key (Trade Republic ISIN, or Fortuneo asset name)
with a Yahoo Finance ticker. As long as an asset isn't mapped, its "live" price
isn't available: the dashboard then falls back to the average purchase price
and states so explicitly (never an invented price).
"""

import hashlib
import json
import os
import pickle
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from paths import config_root, data_root

TICKERS_PATH = os.path.join(config_root(), "tickers.json")
FEES_PATH = os.path.join(config_root(), "fees.json")
CACHE_DIR = os.path.join(data_root(), "cache")

# Cache lifetimes: a ticker's quote currency essentially never changes, history
# is only worth refreshing once a day, only the last price (near-live) needs to
# stay fresh at the scale of a working session.
CURRENCY_TTL = 7 * 24 * 3600
HISTORY_TTL = 24 * 3600
LAST_PRICE_TTL = 15 * 60


def _cache_key(*parts) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _cache_get(key: str, ttl: int):
    path = os.path.join(CACHE_DIR, f"{key}.pkl")
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > ttl:
        return None
    try:
        with open(path, "rb") as f:
            return pickle.load(f)
    except Exception:
        return None


def _cache_set(key: str, value) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(os.path.join(CACHE_DIR, f"{key}.pkl"), "wb") as f:
        pickle.dump(value, f)


def load_ticker_map() -> dict:
    if not os.path.exists(TICKERS_PATH):
        return {}
    with open(TICKERS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if v and not k.startswith("_")}


def load_fees_map() -> dict:
    """{asset_key: TER in % per year}, assets with no management fee (stocks) excluded."""
    if not os.path.exists(FEES_PATH):
        return {}
    with open(FEES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if v is not None and not k.startswith("_")}


def _ticker_currencies(tickers: list[str]) -> dict:
    """Quote currency of each ticker (e.g. AUD for DRO.AX, USD for TTWO).

    The portfolio is accounted for in euros (amounts converted by the brokers);
    a price fetched in its native currency must be converted back to EUR before
    any comparison with the acquisition cost, or the valuation would be skewed.

    Cached per individual ticker (long TTL, a quote currency almost never
    changes) with parallel fetching of the missing tickers — one sequential
    network call per ticker used to be the page load's main bottleneck.
    """
    currencies = {}
    missing = []
    for ticker in tickers:
        cached = _cache_get(_cache_key("currency", ticker), CURRENCY_TTL)
        if cached is not None:
            currencies[ticker] = cached
        else:
            missing.append(ticker)

    if missing:
        import yfinance as yf

        def fetch_one(ticker):
            try:
                return ticker, yf.Ticker(ticker).fast_info["currency"]
            except Exception:
                return ticker, "EUR"

        with ThreadPoolExecutor(max_workers=min(8, len(missing))) as executor:
            for ticker, currency in executor.map(fetch_one, missing):
                currencies[ticker] = currency
                _cache_set(_cache_key("currency", ticker), currency)

    return currencies


def _fx_rates_to_eur(currencies: set[str], **download_kwargs) -> dict:
    """Returns {currency: pandas.Series of EUR->currency rates} to convert a native price to EUR."""
    import yfinance as yf

    non_eur = {c for c in currencies if c and c != "EUR"}
    if not non_eur:
        return {}

    pairs = {currency: f"EUR{currency}=X" for currency in non_eur}
    try:
        data = yf.download(list(pairs.values()), progress=False, auto_adjust=True, **download_kwargs)["Close"]
    except Exception:
        return {}

    rates = {}
    for currency, pair in pairs.items():
        try:
            series = data[pair] if len(pairs) > 1 else data
            series = series.dropna()
            if not series.empty:
                rates[currency] = series
        except Exception:
            continue
    return rates


def fetch_last_prices(asset_keys: list[str]) -> dict:
    """Returns {asset_key: (last_price_in_eur, quote_date)} for mapped assets.

    The date is that of the last close actually available from the provider:
    Yahoo Finance sometimes publishes the most recent session with an empty Close
    (not yet consolidated), in which case we silently fall back to an older
    close. It's returned so the caller can display it, rather than passing off a
    stale price as today's.
    """
    ticker_map = load_ticker_map()
    mapped = {k: ticker_map[k] for k in asset_keys if k in ticker_map}
    if not mapped:
        return {}

    tickers = sorted(set(mapped.values()))
    cache_key = _cache_key("last_prices", *tickers)
    cached = _cache_get(cache_key, LAST_PRICE_TTL)
    if cached is not None:
        return {k: v for k, v in cached.items() if k in mapped}

    try:
        import yfinance as yf
    except ImportError:
        return {}

    try:
        data = yf.download(tickers, period="5d", progress=False, auto_adjust=True)["Close"]
    except Exception:
        return {}

    currencies = _ticker_currencies(tickers)
    fx_rates = _fx_rates_to_eur(set(currencies.values()), period="5d")

    prices = {}
    for asset_key, ticker in mapped.items():
        try:
            series = data[ticker] if len(tickers) > 1 else data
            last_valid = series.dropna()
            if last_valid.empty:
                continue
            price = float(last_valid.iloc[-1])
            price_date = pd.Timestamp(last_valid.index[-1]).tz_localize(None).normalize()
            currency = currencies.get(ticker, "EUR")
            if currency != "EUR":
                fx_series = fx_rates.get(currency)
                if fx_series is None or fx_series.empty:
                    continue
                price = price / float(fx_series.iloc[-1])
            prices[asset_key] = (price, price_date)
        except Exception:
            continue

    _cache_set(cache_key, prices)
    return prices


def fetch_price_history(asset_keys: list[str], start: pd.Timestamp) -> dict:
    """Returns {asset_key: pandas.Series in EUR, indexed by date} for mapped assets."""
    ticker_map = load_ticker_map()
    mapped = {k: ticker_map[k] for k in asset_keys if k in ticker_map}
    if not mapped:
        return {}

    tickers = sorted(set(mapped.values()))
    cache_key = _cache_key("history", start.date().isoformat(), *tickers)
    cached = _cache_get(cache_key, HISTORY_TTL)
    if cached is not None:
        return {k: v for k, v in cached.items() if k in mapped}

    try:
        import yfinance as yf
    except ImportError:
        return {}

    try:
        data = yf.download(tickers, start=start, progress=False, auto_adjust=True)["Close"]
    except Exception:
        return {}

    currencies = _ticker_currencies(tickers)
    fx_rates = _fx_rates_to_eur(set(currencies.values()), start=start)

    histories = {}
    for asset_key, ticker in mapped.items():
        try:
            series = data[ticker] if len(tickers) > 1 else data
            series = series.dropna()
            if series.empty:
                continue
            currency = currencies.get(ticker, "EUR")
            if currency != "EUR":
                fx_series = fx_rates.get(currency)
                if fx_series is None or fx_series.empty:
                    continue
                series = (series / fx_series.reindex(series.index).ffill()).dropna()
            histories[asset_key] = series
        except Exception:
            continue

    _cache_set(cache_key, histories)
    return histories
