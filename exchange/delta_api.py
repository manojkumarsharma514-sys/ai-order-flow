import time
import requests


BASE_URL = "https://api.india.delta.exchange"

# Single source of truth for the contracts->BTC conversion factor,
# shared by BOTH the live WebSocket trade/orderbook feed (exchange/
# websocket_client.py) and this module's REST candle history endpoint
# -- core.websocket_thread.WebSocketThread fetches the real value from
# fetch_contract_size() once at startup and calls set_contract_size()
# here so both pipelines agree, instead of each guessing separately.
# Starts at the same known-safe fallback used everywhere else in the
# app if the live fetch hasn't run yet or ever fails.
_CONTRACT_SIZE_BTC = 0.001


def set_contract_size(value: float) -> None:
    """Called once at startup (see core.websocket_thread.WebSocketThread.run())
    after fetch_contract_size() returns a real value from Delta's
    product spec. Ignored if `value` isn't a sane positive number, so
    a bad call can't zero out or invert every future volume figure."""

    global _CONTRACT_SIZE_BTC
    try:
        value = float(value)
    except (TypeError, ValueError):
        return
    if value > 0:
        _CONTRACT_SIZE_BTC = value


def get_contract_size() -> float:
    """Current contracts->BTC factor -- the live-fetched value if
    set_contract_size() has run successfully, otherwise the shared
    fallback. Lets other modules (e.g. DeltaWebSocketClient) stay in
    sync with this module's resolved value instead of each tracking
    it separately."""
    return _CONTRACT_SIZE_BTC


def fetch_historical_candles(symbol="BTCUSD", resolution="5m", count=150):
    """
    Fetch recent OHLC candles from Delta Exchange India's REST API,
    purely to backfill the chart on startup so it isn't empty.

    IMPORTANT: these backfilled bars are OHLC-only. Delta's REST candle
    endpoint does not return per-price-level buy/sell footprint data,
    so historical candles render as plain candlesticks (wick + body,
    no per-level rows). Real footprint detail only builds up from live
    trade ticks going forward, via core/candle_engine.py.

    Each row's `volume` is converted contracts -> BTC using the same
    factor the live trade/orderbook feed uses (see
    exchange/websocket_client.py's CONTRACT_SIZE_BTC_DEFAULT and
    _CONTRACT_SIZE_BTC above) -- confirmed necessary against a live
    screenshot where REST-backfilled candles showed volumes like
    "1.0K" / "749.48" next to live-tick candles correctly showing
    "0.124" / "8.76" for the same market, immediately after the
    live-feed conversion was fixed but before this REST endpoint was.
    This assumes Delta's candle history endpoint uses the SAME
    contract convention as its trade/orderbook feeds -- not
    independently confirmed against Delta's docs, since both feeds
    have agreed with observed live data so far, this is the most
    defensible default; revisit if historical volume ever looks wrong
    again after this fix.
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
        rows = payload.get("result", [])

        # NOTE (2026-08-19): REST-backfilled historical candle volume is
        # deliberately NOT converted here, by explicit request -- only
        # the live trade/orderbook feed (exchange/websocket_client.py)
        # and this session's Recent Trades / Live Order Book panels use
        # the corrected BTC units. REST-backfilled bars (shown on chart
        # load and after a timeframe switch) will display raw Delta
        # contract counts, same as before the contracts->BTC fix. This
        # means the chart will show a visible split -- older/left-hand
        # bars in contract-scale numbers, newer/right-hand live-tick
        # bars in correct BTC-scale numbers -- that reappears on every
        # app restart or timeframe switch (each re-fetches history) and
        # self-heals only as new live ticks accumulate. If this should
        # ever be converted again, re-apply the same pattern used in
        # exchange/websocket_client.py's _contracts_to_btc, multiplying
        # each row's "volume" by _CONTRACT_SIZE_BTC (or get_contract_size()).

        return rows
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


def fetch_contract_size(symbol="BTCUSD"):
    """
    Fetch the authoritative contract size (in the underlying asset —
    e.g. BTC per contract) for a product from Delta Exchange India's
    REST API, so trade-tick size conversion (raw contract count -> BTC,
    see exchange/websocket_client.py) is sourced from the exchange
    itself instead of a hardcoded, manually-inferred constant.

    Delta's product spec commonly exposes this as `contract_value` on
    GET /v2/products/{symbol}. Some Delta API versions/products have
    also used `contract_size` or `lot_size` for the same concept —
    checked in that order as a defensive fallback, since the exact
    field name isn't independently verified here against live docs.

    Returns a float (contract size in the base asset) on success, or
    None if the endpoint is unreachable, the symbol isn't found, or no
    recognizable field is present. Callers MUST treat None as "unknown"
    and fall back to a known-safe default rather than propagate it —
    see exchange/websocket_client.py's CONTRACT_SIZE_BTC_DEFAULT.
    """

    url = f"{BASE_URL}/v2/products/{symbol}"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
        result = payload.get("result", {})

        for key in ("contract_value", "contract_size", "lot_size"):
            if key in result and result[key] is not None:
                value = float(result[key])
                if value > 0:
                    return value

        print(f"⚠️ Contract size field not found in /v2/products/{symbol} response "
              f"(looked for contract_value/contract_size/lot_size) — using fallback default")
        return None
    except Exception as e:
        print("⚠️ Contract size fetch failed:", e, "— using fallback default")
        return None
