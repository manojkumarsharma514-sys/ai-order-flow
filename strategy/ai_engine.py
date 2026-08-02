"""
strategy/ai_engine.py

Signal Factor Breakdown — explains *why* the AI Engine panel's
confidence/signal look the way they do, by decomposing it into the
same signal families already shown on the dashboard (order flow
delta, buyer vs seller strength, liquidity, VWAP/trend alignment,
momentum), each with a fixed weight:

    Order Flow Imbalance (Delta) ......... 35%
    Buyer vs. Seller Strength ............ 25%
    Liquidity / Depth .................... 15%
    VWAP & Trend Alignment (EMA 20/50) ... 15%
    Momentum (RSI 14) .................... 10%

This is a transparency layer on top of the existing OrderFlowEngine
(core/orderflow_engine.py) — it does not change what the bot trades,
only how the reasoning behind the AI Confidence % is displayed.
"""

FACTOR_WEIGHTS = {
    "order_flow_imbalance": 35,
    "buyer_seller_strength": 25,
    "liquidity_depth": 15,
    "trend_vwap_alignment": 15,
    "momentum_rsi": 10,
}


def _clamp(value, lo=0.0, hi=100.0):
    return max(lo, min(hi, value))


def compute_factor_breakdown(delta, buy_strength, sell_strength,
                              dom_pressure, vwap_status, ema_trend, rsi,
                              confidence=None, signal=None):
    """
    Returns {"factors": [...], "weighted_confidence": float, "side": str}.

    Each factor dict is {"name", "weight", "score" (0-100, how bullish
    that factor looks), "detail" (short human-readable value)} — the
    exact shape the "Signal Factor Breakdown" widget renders.

    `confidence` / `signal`, when provided, are the AI Engine's own
    authoritative readout (core.orderflow_engine market.confidence /
    market.signal — the same numbers driving the AI SIGNAL gauge and
    the auto-trade executor). Passing them makes the breakdown's final
    "AI Confidence" line always match the gauge exactly, since the
    breakdown is then an *explanation* of that number rather than a
    second, independently-computed estimate that can drift from it.
    When omitted, the weighted average of the five factors below is
    used as a standalone estimate instead.

    Every input degrades gracefully to a neutral reading when missing
    or invalid, so an incomplete tick never produces NaN or a
    fabricated extreme value.
    """

    factors = []

    # 1) Order Flow Imbalance (Delta) — 35%
    try:
        d = float(delta)
    except (TypeError, ValueError):
        d = 0.0

    try:
        buyers_raw = float(buy_strength)
        sellers_raw = float(sell_strength)
    except (TypeError, ValueError):
        buyers_raw, sellers_raw = 0.0, 0.0

    # Score as a fraction of the SAME buy/sell tape delta is drawn
    # from (buyers_raw - sellers_raw is already the +/-100% imbalance
    # that produced delta's sign), so it's naturally bounded to
    # [0, 100] with no scale constant to mistune. A fixed arbitrary
    # divisor (what this used to be) either clamps a large delta
    # completely flat/full or, if too large, barely moves the bar for
    # any raw delta a live market actually produces — this instead
    # always sits proportionally between the two extremes.
    delta_score = _clamp(50 + (buyers_raw - sellers_raw) / 2)
    factors.append({
        "name": "Order Flow Imbalance (Delta)",
        "weight": FACTOR_WEIGHTS["order_flow_imbalance"],
        "score": delta_score,
        "detail": f"{'Bullish' if d > 0 else ('Bearish' if d < 0 else 'Neutral')} (Δ {d:+.1f})",
    })

    # 2) Buyer vs. Seller Strength — 25%
    try:
        buyers = float(buy_strength)
        sellers = float(sell_strength)
    except (TypeError, ValueError):
        buyers, sellers = 50.0, 50.0
    factors.append({
        "name": "Buyer vs. Seller Strength",
        "weight": FACTOR_WEIGHTS["buyer_seller_strength"],
        "score": _clamp(buyers),
        "detail": f"Buyer {buyers:.0f}% / Seller {sellers:.0f}%",
    })

    # 3) Liquidity / Depth (order book DOM pressure) — 15%
    try:
        dom = float(dom_pressure)
    except (TypeError, ValueError):
        dom = 0.0
    factors.append({
        "name": "Liquidity / Depth",
        "weight": FACTOR_WEIGHTS["liquidity_depth"],
        "score": _clamp(50 + dom),
        "detail": f"{dom:+.1f}%",
    })

    # 4) VWAP & Trend Alignment (EMA 20/50) — 15%
    vwap_bull = str(vwap_status).lower() == "above"
    vwap_known = str(vwap_status) not in ("None", "--", "")
    trend_text = str(ema_trend or "")
    trend_lower = trend_text.lower()
    trend_bull = "up" in trend_lower or "bull" in trend_lower
    trend_bear = "down" in trend_lower or "bear" in trend_lower

    if vwap_bull and trend_bull:
        trend_score = 85.0
    elif vwap_known and not vwap_bull and trend_bear:
        trend_score = 15.0
    elif vwap_bull or trend_bull:
        trend_score = 65.0
    elif (vwap_known and not vwap_bull) or trend_bear:
        trend_score = 35.0
    else:
        trend_score = 50.0

    factors.append({
        "name": "VWAP & Trend Alignment (EMA 20/50)",
        "weight": FACTOR_WEIGHTS["trend_vwap_alignment"],
        "score": trend_score,
        "detail": trend_text or "--",
    })

    # 5) Momentum (RSI 14) — 10%
    try:
        rsi_val = float(rsi)
        momentum_score = _clamp(rsi_val)
        rsi_detail = f"{rsi_val:.1f}"
    except (TypeError, ValueError):
        momentum_score = 50.0
        rsi_detail = "--"

    factors.append({
        "name": "Momentum (RSI 14)",
        "weight": FACTOR_WEIGHTS["momentum_rsi"],
        "score": momentum_score,
        "detail": rsi_detail,
    })

    weighted = _clamp(sum(f["score"] * f["weight"] for f in factors) / 100.0)

    if confidence is not None and signal is not None:
        # Authoritative reading from the AI Engine itself — keeps this
        # panel's headline number identical to the AI SIGNAL gauge and
        # to what the auto-trade executor is actually acting on.
        final_confidence = _clamp(float(confidence))
        side = "BUY" if "BUY" in str(signal).upper() else (
            "SELL" if "SELL" in str(signal).upper() else "WAIT"
        )
    else:
        final_confidence = weighted
        side = "BUY" if weighted >= 50 else "SELL"

    return {"factors": factors, "weighted_confidence": final_confidence, "side": side}
