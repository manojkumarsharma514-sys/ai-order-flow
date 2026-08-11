"""
strategy/regime_engine.py

RegimeEngine
------------
Classifies market regime (Uptrend / Downtrend / Sideways) and computes
ATR from a FIXED, dedicated timeframe — independent of whatever
timeframe the chart UI happens to be displaying.

Why this exists: both the Sideways-regime entry gate and the
ATR-based fee-edge gate / SL-TP sizing in trading/executor.py were
previously fed from a core.candle_engine.CandleManager instance SHARED
with the chart's own display timeframe (DashboardController.
candle_manager). Clicking the chart's TIMEFRAME buttons (1m/5m/.../
4H/1D) silently changed the ATR and trend reading the strategy was
acting on — a trade could pass or fail the fee-edge gate, and get
wildly different SL/TP distances, purely because of what the trader
happened to be looking at, with zero change in actual market
conditions. Documented case: data/auto_trades_log.csv around
2026-08-11 15:11 — an identical signal at an identical price flipped
from SKIPPED (expected_move_below_fee_floor) to EXECUTED within 8
seconds, coinciding exactly with a chart timeframe switch from 5m to
4H.

RegimeEngine owns its own CandleManager (constructed by the caller —
see DashboardController), fed the same live trade ticks as the
chart's, but always aggregated at STRATEGY_TIMEFRAME_SECONDS
regardless of the chart's current selection. It does not replace the
chart-tied indicators used for the AI Engine panel's own display
(those are fine as chart-relative "what does the tape look like on
what I'm currently viewing" numbers) — this is specifically for
values that DRIVE trading decisions, which must not move just because
someone clicked a timeframe button.
"""

from strategy.indicators import calculate_atr
from strategy.trend import ema_trend

# Fixed strategy timeframe — deliberately independent of the chart's
# TimeframeSelector. 1 hour is a reasonable starting point: coarse
# enough to filter tick-level noise (see the "4,623 signal events in
# 3.5 hours, 1 executed" case that motivated this module), fine enough
# not to lag entries by many hours. Change here (not in the UI) if a
# different strategy timeframe is wanted later.
STRATEGY_TIMEFRAME_SECONDS = 3600
STRATEGY_RESOLUTION = "1h"  # matches exchange.delta_api resolution codes

# Minimum candles needed before EMA 20/50 + ATR(14) are meaningful —
# mirrors DashboardController.update_indicators()'s own 15-candle
# warm-up guard for the chart-tied indicators.
MIN_CANDLES_FOR_REGIME = 15


class RegimeEngine:
    """
    Wraps a dedicated, fixed-timeframe candle series to answer two
    questions independently of the chart's display timeframe:

        regime  — "Uptrend" | "Downtrend" | "Sideways" | None
        atr     — current ATR(14) in price terms, or None

    None from either means "not enough data yet" (still backfilling /
    warming up) — callers should treat that as "unknown", never as
    Sideways/zero, exactly like the existing chart-tied indicators
    already degrade. This keeps the fail-open behavior of
    AutoTradeExecutor's _regime_permits_entry / _edge_clears_fees
    intact during warm-up instead of accidentally locking out all
    trading before the strategy feed has enough history.
    """

    def __init__(self, candle_manager, fast=20, slow=50, atr_period=14):
        self.candle_manager = candle_manager
        self.fast = fast
        self.slow = slow
        self.atr_period = atr_period

        self._last_regime = None
        self._last_atr = None

    def update(self):
        """Recompute regime + ATR from the current fixed-timeframe
        candle series. Call once per UI tick — same cost/shape as the
        existing chart-tied update_indicators() call it mirrors.
        Returns (regime, atr)."""

        candles = [c for c in self.candle_manager.get_candles() if c.close is not None]

        if len(candles) < MIN_CANDLES_FOR_REGIME:
            self._last_regime = None
            self._last_atr = None
            return self._last_regime, self._last_atr

        trend_data = ema_trend(candles, fast=self.fast, slow=self.slow)
        atr = calculate_atr(candles, period=self.atr_period)

        self._last_regime = trend_data["trend"]  # "Uptrend"/"Downtrend"/"Sideways"/None
        self._last_atr = atr

        return self._last_regime, self._last_atr

    @property
    def regime(self):
        return self._last_regime

    @property
    def atr(self):
        return self._last_atr

    def atr_pct(self, price):
        """ATR as a % of price — same shape as the chart's ATR-level
        bucketing in DashboardController.update_indicators(), for
        anyone who wants a Low/Medium/High readout off the fixed
        strategy feed instead of the chart-tied one."""
        if self._last_atr is None or not price or price <= 0:
            return None
        return (self._last_atr / price) * 100