"""
trading/risk.py

Portfolio risk % calculation for the dashboard's RISK gauge.

    Risk % = (Position Size * |Entry Price - Stop Loss Price|)
             / Total Account Balance * 100

This is real dollars-at-risk (how much would actually be lost if every
open position's stop loss got hit), not raw notional exposure. Raw
notional exposure (size * price) is almost always many multiples of
account balance on a leveraged position, which is why the old
calculation pinned the gauge at a fabricated, permanent 100%.

A position with no stop loss set has unbounded downside, so it can't
be represented as a bounded dollar-risk number — it contributes 0
rather than inflating the gauge. An account with no open positions is
0% risk, never NaN and never 100%.
"""


def calculate_risk_percent(positions, balance):
    """
    positions: iterable of objects exposing .size, .entry_price, .stop_loss
    balance:   total account balance the risk is measured against

    Returns a float in [0, 100]. Never raises — degrades to 0.0 on any
    missing/invalid input instead of NaN or a fabricated 100%.
    """

    try:
        balance = float(balance)
    except (TypeError, ValueError):
        return 0.0

    if not balance or balance <= 0 or not positions:
        return 0.0

    dollars_at_risk = 0.0

    for p in positions:
        size = getattr(p, "size", None)
        entry = getattr(p, "entry_price", None)
        stop = getattr(p, "stop_loss", None)

        # No stop loss set on this position -> its downside isn't
        # bounded, so it can't be included in a $-at-risk figure.
        if not size or not entry or not stop:
            continue

        try:
            dollars_at_risk += float(size) * abs(float(entry) - float(stop))
        except (TypeError, ValueError):
            continue

    if dollars_at_risk <= 0:
        return 0.0

    return min(100.0, (dollars_at_risk / balance) * 100)


def risk_label(pct):
    """LOW / MEDIUM / HIGH bucket for a risk_pct produced above."""

    if pct < 20:
        return "LOW"
    elif pct < 50:
        return "MEDIUM"
    return "HIGH"
