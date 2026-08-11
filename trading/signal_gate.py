"""
trading/signal_gate.py

SignalGate — PHASE 3 gate
--------------------------
Requires the tick engine's confirmed, actionable signal to AGREE with
the fixed-timeframe regime (see strategy/regime_engine.py) before it's
allowed through to the rest of AutoTradeExecutor's gate chain.

Motivation: during a single clean ~465-point BTCUSD rally
(2026-08-11, 12:00-15:40), core.orderflow_engine's tick-based
OrderFlowEngine fired 1,937 STRONG BUY and 2,686 STRONG SELL
signal events — nearly as many fighting the move as following it —
because it only reads the last ~200 raw trades and has no concept of
trend. Every one of those was previously treated as equally
actionable, with only the Sideways-regime and fee-edge gates filtering
after the fact — which is why that afternoon produced 4,623 logged
signal events and exactly 1 execution: the OTHER gates were doing all
the real filtering work against what was mostly noise.

SignalGate inverts that: regime becomes the FIRST filter a tick signal
has to clear, not the last. A signal is only permitted through if its
direction agrees with the current fixed-timeframe trend:

    regime Uptrend    + LONG (STRONG BUY)   -> permitted
    regime Downtrend  + SHORT (STRONG SELL) -> permitted
    regime Sideways                         -> rejected outright
    regime unknown / not yet warmed up      -> permitted (fail-open,
                                                same as every other
                                                Phase 2 gate)
    regime disagrees with signal direction  -> rejected
        (Uptrend + STRONG SELL, or Downtrend + STRONG BUY — the tick
        engine reacting to a counter-trend wobble, not a real move)

This does NOT replace AutoTradeExecutor._regime_permits_entry (the
existing pure Sideways check) or _edge_clears_fees (the ATR/fee-edge
check) — it runs BEFORE both, as an earlier, independent gate. Both
of those still apply afterward exactly as before; a signal can clear
SignalGate and still be blocked downstream.
"""

from dataclasses import dataclass


@dataclass
class GateDecision:
    allowed: bool
    reason: str = ""


class SignalGate:
    """Injectable, same pattern as ExitManager / RiskGovernor — can be
    swapped out or disabled via Settings without touching
    AutoTradeExecutor itself."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def set_enabled(self, enabled: bool):
        self.enabled = bool(enabled)

    def evaluate(self, side: str, regime) -> GateDecision:
        """
        side:   "LONG" | "SHORT" — the tick engine's confirmed,
                actionable signal direction (already resolved by the
                caller via SIGNAL_SIDE_MAP before this is called).
        regime: "Uptrend" | "Downtrend" | "Sideways" | None — from
                strategy.regime_engine.RegimeEngine (a FIXED timeframe,
                independent of the chart's display timeframe).
        """

        if not self.enabled:
            return GateDecision(allowed=True, reason="signal_gate_disabled")

        if regime is None:
            # Fixed-timeframe feed hasn't backfilled / warmed up yet —
            # fail open, same warm-up behavior as every other Phase 2
            # gate (never block all trading just because history is
            # still loading).
            return GateDecision(allowed=True, reason="regime_not_ready")

        regime_norm = str(regime).strip().lower()

        if regime_norm == "sideways":
            return GateDecision(allowed=False, reason="regime_disagreement_sideways")

        if side == "LONG" and regime_norm == "uptrend":
            return GateDecision(allowed=True, reason="regime_aligned")

        if side == "SHORT" and regime_norm == "downtrend":
            return GateDecision(allowed=True, reason="regime_aligned")

        # side == LONG but regime == Downtrend, or side == SHORT but
        # regime == Uptrend: the tick engine is reacting to a
        # counter-trend wobble, not participating in the actual move.
        return GateDecision(allowed=False, reason="regime_disagreement")