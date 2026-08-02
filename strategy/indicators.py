"""
Indicator math computed from the candle series already built by
core/candle_engine.py (both backfilled REST history and live candles).

These operate on plain Candle objects (see core/candle_engine.Candle),
using .open/.high/.low/.close/.volume — footprint detail isn't needed
here.
"""


def calculate_ema(values, period):
    """Exponential moving average. Returns a list aligned to `values`,
    with None for indices before there's enough data to seed it."""

    if len(values) < period:
        return [None] * len(values)

    ema = [None] * len(values)

    sma = sum(values[:period]) / period
    ema[period - 1] = sma

    multiplier = 2 / (period + 1)

    for i in range(period, len(values)):
        ema[i] = (values[i] - ema[i - 1]) * multiplier + ema[i - 1]

    return ema


def calculate_rsi(closes, period=14):
    """Simple (SMA-based) RSI. Returns None until enough candles exist."""

    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0))
        losses.append(max(-change, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return rsi


def calculate_atr(candles, period=14):
    """Average True Range over the last `period` candles."""

    if len(candles) < period + 1:
        return None

    true_ranges = []

    for i in range(1, len(candles)):
        high = candles[i].high
        low = candles[i].low
        prev_close = candles[i - 1].close

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

        true_ranges.append(tr)

    return sum(true_ranges[-period:]) / period


def calculate_vwap(candles):
    """
    Rolling VWAP over the candle series currently held in memory (not
    an exchange-reported session VWAP — resets whenever the chart's
    candle window rolls off older bars).
    """

    if not candles:
        return None

    cum_pv = 0.0
    cum_vol = 0.0

    for c in candles:
        if c.close is None:
            continue

        typical_price = (c.high + c.low + c.close) / 3
        cum_pv += typical_price * (c.volume or 0)
        cum_vol += (c.volume or 0)

    if cum_vol == 0:
        return None

    return cum_pv / cum_vol
