"""Récupération des prix de marché via yfinance, à partir du mapping config/tickers.json.

Le mapping associe une asset_key (ISIN Trade Republic, ou nom d'actif Fortuneo)
à un ticker Yahoo Finance. Tant qu'un actif n'est pas mappé, son prix "live"
n'est pas disponible : le dashboard retombe alors sur le prix de revient moyen
et l'indique explicitement (pas de prix inventé).
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

# Durées de vie du cache : les devises de cotation ne changent jamais, l'historique
# ne vaut la peine d'être rafraîchi qu'une fois par jour, seul le dernier prix
# (proche du live) doit rester frais à l'échelle de la session de travail.
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
    """{asset_key: TER en % par an}, actifs sans frais de gestion (actions) exclus."""
    if not os.path.exists(FEES_PATH):
        return {}
    with open(FEES_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {k: v for k, v in data.items() if v is not None and not k.startswith("_")}


def _ticker_currencies(tickers: list[str]) -> dict:
    """Devise de cotation de chaque ticker (ex. AUD pour DRO.AX, USD pour TTWO).

    Le portefeuille est comptabilisé en euros (montants convertis par les courtiers) ;
    un prix récupéré dans sa devise native doit être reconverti en EUR avant toute
    comparaison avec le coût d'acquisition, sous peine de fausser la valorisation.

    Mise en cache par ticker individuel (durée longue, une devise de cotation ne
    change quasiment jamais) et récupération en parallèle des tickers manquants —
    un appel réseau séquentiel par ticker était le principal goulet d'étranglement
    du chargement de la page.
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
    """Retourne {devise: pandas.Series de taux EUR->devise} pour convertir un prix natif en EUR."""
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
    """Retourne {asset_key: (dernier_prix_en_eur, date_de_cotation)} pour les actifs mappés.

    La date est celle de la dernière clôture réellement disponible chez le fournisseur :
    Yahoo Finance publie parfois la séance la plus récente avec un Close vide (encore non
    consolidé), auquel cas on retombe silencieusement sur une clôture plus ancienne. On la
    retourne pour que l'appelant l'affiche, plutôt que de faire passer un prix obsolète
    pour un prix du jour.
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
    """Retourne {asset_key: pandas.Series en EUR, indexée par date} pour les actifs mappés."""
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
