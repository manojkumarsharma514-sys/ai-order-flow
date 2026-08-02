import time
import requests


BASE_URL = "https://api.india.delta.exchange"


def fetch_historical_candles(symbol="BTCUSD", resolution="5m", count=150):
    """
    Fetch recent OHLC candles from Delta Exchange India's REST API,
    purely to backfill the chart on startup so it isn't empty.

    IMPORTANT: these backfilled bars are OHLC-only. Delta's REST candle
    endpoint does not return per-price-level buy/sell footprint data,
    so historical candles render as plain candlesticks (wick + body,
    no per-level rows). Real footprint detail only builds up from live
    trade ticks going forward, via core/candle_engine.py.
    """

    resolution_seconds = {
        "1m": 60, "3m": 180, "5m": 300, "15m": 900,
        "1h": 3600, "4h": 14400, "1d": 86400,
    }.get(resolution, 300)

    end = int(time.time())
    start = end - resolution_seconds * count

    url = f"{BASE_URL}/v2/history/candles"

    params = {
        "resolution": resolution,
        "symbol": symbol,
        "start": start,
        "end": end,
    }

    try:
        resp = requests.get(url, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("result", [])
    except Exception as e:
        print("⚠️ Historical candle fetch failed:", e)
        return []


def fetch_ticker(symbol="BTCUSD"):
    """
    Fetch the 24h ticker snapshot (high/low/volume/funding rate) for a
    symbol from Delta Exchange India's REST API. Field names follow
    Delta's documented ticker response (high, low, volume, funding_rate) —
    verify against your account/product if any come back missing.
    """

    url = f"{BASE_URL}/v2/tickers/{symbol}"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        return payload.get("result", {})
    except Exception as e:
        print("⚠️ Ticker fetch failed:", e)
        return {}
