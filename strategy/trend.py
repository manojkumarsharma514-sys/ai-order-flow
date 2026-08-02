"""EMA-crossover trend read, built on top of strategy/indicators.py."""

from strategy.indicators import calculate_ema


def ema_trend(candles, fast=20, slow=50):
    """
    Returns a dict: {"trend": "Uptrend"/"Downtrend"/"Sideways"/None,
    "ema_fast": float or None, "ema_slow": float or None}
    based on the last two EMA values crossing (fast vs slow).
    """

    closes = [c.close for c in candles if c.close is not None]

    if len(closes) < slow + 1:
        return {"trend": None, "ema_fast": None, "ema_slow": None}

    ema_fast_series = calculate_ema(closes, fast)
    ema_slow_series = calculate_ema(closes, slow)

    fast_now = ema_fast_series[-1]
    slow_now = ema_slow_series[-1]

    if fast_now is None or slow_now is None:
        return {"trend": None, "ema_fast": None, "ema_slow": None}

    spread_pct = (fast_now - slow_now) / slow_now * 100

    if spread_pct > 0.05:
        trend = "Uptrend"
    elif spread_pct < -0.05:
        trend = "Downtrend"
    else:
        trend = "Sideways"

    return {"trend": trend, "ema_fast": fast_now, "ema_slow": slow_now}
