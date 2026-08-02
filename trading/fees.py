"""
trading/fees.py

Delta Exchange fee structure, applied to every order fill (entry AND
exit — a real position pays trading fees twice, once opening and once
closing) across both manual trades and the AI auto-trader:

    Maker Fee Rate = 0.02% (0.0002) of Notional Order Value
    Taker Fee Rate = 0.05% (0.0005) of Notional Order Value
    GST Rate       = 18% applied on top of the calculated trading fee

    Notional Value ($) = Quantity (BTC) x Execution Price
    Base Fee            = Notional Value x Fee Rate
    GST Amount           = Base Fee x 0.18
    Total Fee ($)        = Base Fee + GST Amount

Every fill in this app (manual Buy/Sell click, AI auto-trade, or an
SL/TP auto-close) executes instantly at the quoted price — there's no
resting limit-order book here — so these are economically Taker fills.
`is_maker` is exposed for completeness / future limit-order support,
defaulting to False (Taker) everywhere it's called.
"""

MAKER_FEE_RATE = 0.0002   # 0.02%
TAKER_FEE_RATE = 0.0005   # 0.05%
GST_RATE = 0.18           # 18%


def calculate_fee(notional_value: float, is_maker: bool = False) -> dict:
    """Returns {"base_fee", "gst_amount", "total_fee"} for one fill."""

    if not notional_value or notional_value <= 0:
        return {"base_fee": 0.0, "gst_amount": 0.0, "total_fee": 0.0}

    fee_rate = MAKER_FEE_RATE if is_maker else TAKER_FEE_RATE

    base_fee = notional_value * fee_rate
    gst_amount = base_fee * GST_RATE
    total_fee = base_fee + gst_amount

    return {
        "base_fee": round(base_fee, 4),
        "gst_amount": round(gst_amount, 4),
        "total_fee": round(total_fee, 4),
    }
