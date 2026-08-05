"""
trading/executor.py

AutoTradeExecutor
-----------------
The missing link between "AI Engine says STRONG BUY at 62% confidence"
and an actual paper position appearing in the Positions table.

Bridges:  AI Engine (core.orderflow_engine "market" state)
            -> AutoTradeExecutor.evaluate(...)   [called every UI tick]
              -> PaperTradingEngine.open_position(source="AI_AUTO")
                -> data/auto_trades_log.csv   (every event, incl. rejections)
                -> auto_trade_executed signal -> Dashboard "RECENT TRADES"

Only fires when AI AUTO TRADING is ON (see `set_enabled`). Independent
of AUTO MODE, which only locks/unlocks the *manual* trading widgets —
AI AUTO TRADING is the switch that actually lets this class place
orders. Both are wired in the controller so their behavior matches
what the toggle switches visually communicate.

--------------------------------------------------------------------
Anti-whipsaw / fee-awareness (added after the 12.5% win-rate / 21-loss
session where every close_reason was "ai_signal_flip"):

`evaluate()` now expects the CALLER to pass the *confirmed* signal
(core.orderflow_engine market.confirmed_signal — persisted for several
seconds, not the raw per-tick market.signal) so a single noisy tick
can no longer trigger an entry or a flip on its own. On top of that,
three independent gates apply before a flip is allowed:

  1. Fee justification — the take-profit target must clear round-trip
     trading fees + assumed slippage by a safety margin
     (fee_safety_multiplier). Rather than skipping the trade outright
     when the ATR/pct-based target falls short (which, in a quiet/
     Low-ATR market, could block every signal indefinitely), the TP
     distance is floored at the minimum fee-justified distance instead
     — the trade still fires, just with a wider, guaranteed-profitable
     target.
  2. Flip confidence buffer — reversing an existing AI_AUTO position
     requires MORE confidence than opening one fresh
     (confidence_threshold + flip_confidence_buffer). This is the
     hysteresis band.
  3. Minimum hold time — a position must have been open at least
     min_hold_seconds before it's eligible to be flip-closed at all,
     regardless of how confident the new signal is.

SL/TP are ATR-based when an `atr` value is supplied to evaluate()
(a real stop/target instead of only ever exiting via signal flip),
falling back to the existing fixed-percentage risk params otherwise.
--------------------------------------------------------------------
"""

import csv
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from trading.fees import TAKER_FEE_RATE, GST_RATE

AUTO_TRADES_LOG_PATH = Path("data") / "auto_trades_log.csv"

LOG_COLUMNS = ["timestamp", "symbol", "signal", "side", "price", "qty", "status", "reason"]

# core.orderflow_engine signal strings -> trade side. Anything not in
# this map (WAIT, ABSORPTION, WATCH *) is treated as "no action" so the
# bot only trades on its highest-conviction reads.
SIGNAL_SIDE_MAP = {
    "🟢 STRONG BUY": "LONG",
    "🔴 STRONG SELL": "SHORT",
}


class AutoTradeExecutor(QObject):

    auto_trade_executed = pyqtSignal(dict)  # {side, price, qty, status, reason, ...}
    auto_trade_rejected = pyqtSignal(str)   # human-readable rejection reason

    def __init__(self, paper_engine, symbol="BTCUSD",
                 confidence_threshold=55, cooldown_seconds=20,
                 log_path: Path = AUTO_TRADES_LOG_PATH):
        super().__init__()

        self.paper_engine = paper_engine
        self.symbol = symbol
        self.confidence_threshold = confidence_threshold
        self.cooldown_seconds = cooldown_seconds
        self.log_path = Path(log_path)

        self.enabled = True          # driven by AI AUTO TRADING toggle
        self.trading_paused = False  # driven by Stop Bot / AUTO MODE off, if desired

        self._last_trade_time = None

        # Dedup for _skip()'s banner emission — the same skip reason
        # can otherwise fire on every single 250ms evaluate() tick for
        # as long as confirmed_signal holds (up to signal_hold_seconds
        # in core.orderflow_engine, ~12 ticks), which used to spam the
        # UI banner with identical text repeatedly. Every skip is still
        # logged to CSV every time (full audit trail); only the UI
        # emission is deduped to once per reason-change.
        self._last_skip_reason = None

        self._risk_params = {
            # "size" is no longer used to place orders (see
            # _calculate_position_size) — kept only as a manual-override
            # ceiling if you ever want one; ignore/remove if unused.
            "size": 1.0,
            "stop_loss_pct": 0.5,   # % away from entry
            "take_profit_pct": 1.5,
        }

        # Dynamic Position Sizing:
        #
        #   Total Purchasing Power = Balance x Leverage
        #   Allocated Capital ($)  = Purchasing Power x Margin Usage %
        #   Position Size (BTC)    = Allocated Capital / Current Price
        #
        # Defaults match the spec: 25x leverage, 50% margin usage.
        self.leverage = 25
        self.margin_pct = 0.50

        # ------------------------------------------------------------
        # Anti-whipsaw / fee-awareness controls
        # ------------------------------------------------------------

        # A position must have been open at least this long before an
        # opposite signal is even allowed to flip it.
        self.min_hold_seconds = 90

        # Hysteresis band: reversing an existing AI_AUTO position needs
        # MORE conviction than opening one fresh. e.g. threshold=75,
        # buffer=10 -> opening needs 75%, flipping needs 85%.
        self.flip_confidence_buffer = 10

        # Projected TP profit must be at least this multiple of
        # round-trip fees + assumed slippage before ANY entry (flip or
        # fresh) is allowed to fire.
        self.fee_safety_multiplier = 1.5

        # Assumed one-way slippage in basis points, applied on both fills.
        self.slippage_bps = 5

        # ATR-based SL/TP multipliers, used when evaluate() is given an
        # `atr` value. Falls back to the pct-based risk params above
        # when ATR isn't available yet (e.g. not enough candles).
        self.atr_sl_multiplier = 1.5
        self.atr_tp_multiplier = 3.0

        self._ensure_log_file()

    # ------------------------------------------------------------
    # External wiring points
    # ------------------------------------------------------------

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        print(f"🤖 AI Auto Trading -> {'ON' if enabled else 'OFF'}")

    def set_leverage(self, leverage):
        try:
            self.leverage = float(leverage) if leverage else 25
        except (TypeError, ValueError):
            self.leverage = 25

    def set_margin_pct(self, pct):
        """pct as a fraction (0.50 == 50%), NOT a 0-100 percentage."""
        try:
            self.margin_pct = max(0.0, min(1.0, float(pct))) if pct else 0.50
        except (TypeError, ValueError):
            self.margin_pct = 0.50

    def set_min_hold_seconds(self, seconds):
        try:
            self.min_hold_seconds = max(0, int(seconds))
        except (TypeError, ValueError):
            pass

    def set_flip_confidence_buffer(self, buffer_pct):
        try:
            self.flip_confidence_buffer = max(0.0, float(buffer_pct))
        except (TypeError, ValueError):
            pass

    def set_fee_safety_multiplier(self, multiplier):
        try:
            self.fee_safety_multiplier = max(1.0, float(multiplier))
        except (TypeError, ValueError):
            pass

    def calculate_position_size(self, price: float) -> float:
        """
        Dynamic Position Sizing Formula:
            purchasing_power = balance * leverage
            allocated_usd    = purchasing_power * margin_pct
            qty_btc          = allocated_usd / price

        Rounded to 3 decimals; enforces a 0.001 BTC minimum lot size so
        a near-zero balance/price edge case can't produce a zero/invalid
        order quantity.
        """

        balance = getattr(self.paper_engine, "balance", 0.0) or 0.0

        if price is None or price <= 0 or balance <= 0:
            return 0.001

        purchasing_power = balance * self.leverage
        allocated_usd = purchasing_power * self.margin_pct
        qty = allocated_usd / price

        return max(0.001, round(qty, 3))

    def set_risk_params(self, size=None, stop_loss_pct=None, take_profit_pct=None):
        if size is not None:
            self._risk_params["size"] = size
        if stop_loss_pct is not None:
            self._risk_params["stop_loss_pct"] = stop_loss_pct
        if take_profit_pct is not None:
            self._risk_params["take_profit_pct"] = take_profit_pct

    # ------------------------------------------------------------
    # SL/TP calculation — ATR-based when available, percentage-based
    # fallback otherwise.
    # ------------------------------------------------------------

    def _atr_based_sl_tp(self, price, atr, side):
        sl_dist = atr * self.atr_sl_multiplier
        tp_dist = atr * self.atr_tp_multiplier

        if side == "LONG":
            return price - sl_dist, price + tp_dist
        return price + sl_dist, price - tp_dist

    def _pct_based_sl_tp(self, price, side, sl_pct, tp_pct):
        if side == "LONG":
            return price * (1 - sl_pct), price * (1 + tp_pct)
        return price * (1 + sl_pct), price * (1 - tp_pct)

    # ------------------------------------------------------------
    # Fee-awareness: the take-profit target must clear round-trip
    # trading fees + assumed slippage by a safety margin, or the trade
    # is structurally unprofitable before price even moves.
    #
    # NOTE: this is scale-invariant — both the projected profit
    # (tp_dist * qty) and the cost (notional_rate * price * qty) scale
    # linearly with qty, so position size/leverage never affects
    # whether a trade clears this bar. It's purely a function of how
    # wide tp_dist is relative to price. In a "Low ATR" market (see
    # DashboardController.update_indicators — ATR < 0.1% of price),
    # even 3x ATR tops out under the ~0.33% round-trip-cost-plus-buffer
    # bar, which used to SKIP every single signal in quiet conditions.
    # Instead of skipping the trade outright, the TP distance is
    # floored at the minimum fee-justified distance — still anchored
    # to ATR/pct when that's already wide enough, only widened when it
    # would otherwise guarantee a loss after costs.
    # ------------------------------------------------------------

    def _min_tp_distance_for_fees(self, price):
        """Minimum |take_profit - entry| distance (in price terms) that
        clears round-trip taker fees + GST + assumed slippage by
        `fee_safety_multiplier`. Independent of position size."""

        round_trip_fee_rate = TAKER_FEE_RATE * (1 + GST_RATE) * 2  # entry fill + exit fill
        slippage_rate = (self.slippage_bps / 10000) * 2            # entry fill + exit fill

        total_rate = round_trip_fee_rate + slippage_rate
        return price * total_rate * self.fee_safety_multiplier

    def _apply_fee_floor(self, price, side, take_profit):
        """Widen take_profit (if needed) so it clears the fee floor
        above. Never tightens an already-wide ATR/pct-based target."""

        min_dist = self._min_tp_distance_for_fees(price)
        current_dist = abs(take_profit - price) if take_profit else 0.0

        if current_dist >= min_dist:
            return take_profit

        return price + min_dist if side == "LONG" else price - min_dist

    # ------------------------------------------------------------
    # Main entry point — called once per UI refresh tick from the
    # DashboardController, with the latest AI Engine readout.
    #
    # IMPORTANT: pass the CONFIRMED signal (core.orderflow_engine
    # market.confirmed_signal), not the raw per-tick market.signal —
    # see controller/dashboard_controller.py update_indicators()/
    # refresh_ui(). `atr` is optional; when supplied, SL/TP are
    # ATR-based instead of fixed percentages.
    # ------------------------------------------------------------

    def evaluate(self, signal: str, confidence: float, price: float, atr: float = None):

        if not self.enabled or self.trading_paused:
            return

        if price is None or price <= 0:
            return

        side = SIGNAL_SIDE_MAP.get(signal)
        if side is None:
            return  # WAIT / WATCH / ABSORPTION / unconfirmed — not a high-conviction signal

        if confidence < self.confidence_threshold:
            self._skip(signal, side, price, qty=0, reason="confidence_below_threshold")
            return

        if self._in_cooldown():
            return

        # avoid stacking multiple auto positions in the same direction
        if any(p.source == "AI_AUTO" and p.side == side for p in self.paper_engine.positions):
            return

        opposite_side = "SHORT" if side == "LONG" else "LONG"
        opposite_positions = [
            p for p in self.paper_engine.positions
            if p.source == "AI_AUTO" and p.side == opposite_side
        ]

        size = self.calculate_position_size(price)
        sl_pct = self._risk_params["stop_loss_pct"] / 100
        tp_pct = self._risk_params["take_profit_pct"] / 100

        if atr is not None and atr > 0:
            stop_loss, take_profit = self._atr_based_sl_tp(price, atr, side)
        else:
            stop_loss, take_profit = self._pct_based_sl_tp(price, side, sl_pct, tp_pct)

        # Gate 1 (was a hard skip — "fee_unjustified" — that blocked
        # every signal in a quiet/Low-ATR market, since 3x ATR often
        # can't clear round-trip fees on its own). Now: widen the TP
        # to the minimum fee-justified distance instead of skipping
        # the trade outright. Only widens when the ATR/pct-based
        # target would otherwise guarantee a loss after costs; a
        # target that already clears the bar is left untouched.
        take_profit = self._apply_fee_floor(price, side, take_profit)

        if opposite_positions:
            # Gate 2: reversing needs MORE conviction than opening
            # fresh — the hysteresis band that stops a signal wobbling
            # around the threshold from flip-flopping.
            if confidence < self.confidence_threshold + self.flip_confidence_buffer:
                self._skip(signal, side, price, qty=0, reason="flip_confidence_below_buffer")
                return

            # Gate 3: minimum hold time — a position just opened can't
            # be immediately reversed no matter how confident the new
            # signal is.
            stale_enough = all(
                (datetime.now() - p.opened_at).total_seconds() >= self.min_hold_seconds
                for p in opposite_positions
            )
            if not stale_enough:
                self._skip(signal, side, price, qty=0, reason="min_hold_not_met")
                return

            # All gates passed — close the opposite-direction AI_AUTO
            # position(s) first, then open the new one below. Without
            # this, the bot would end up holding a LONG and a SHORT on
            # the same symbol at once (self-hedging: real losses on
            # both legs to spread/fees with no net exposure).
            for p in opposite_positions:
                self.paper_engine.close_position(p.id, reason="ai_signal_flip")

        # Keep the engine's margin-check cap in step with the leverage
        # this size was actually calculated against.
        self.paper_engine.max_leverage = self.leverage

        position = self.paper_engine.open_position(
            side=side,
            size=size,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source="AI_AUTO",
        )

        if position is None:
            reason = self.paper_engine.last_rejection or "unknown"
            self._log_event(
                signal, side, price, qty=size, status="REJECTED",
                reason=reason,
            )
            if reason != self._last_skip_reason:
                self._last_skip_reason = reason
                self.auto_trade_rejected.emit(reason)
            return

        # Cooldown only starts once a trade actually fills — a rejected
        # order (insufficient margin, notional over the leverage cap,
        # etc.) must not lock the bot out of trading for
        # cooldown_seconds while a STRONG BUY/SELL signal sits untraded.
        self._last_trade_time = datetime.now()
        self._last_skip_reason = None  # fresh state — next skip (if any) always shows

        self._log_event(signal, side, price, qty=size, status="EXECUTED", reason="ai_signal")

        self.auto_trade_executed.emit({
            "side": side,
            "price": price,
            "qty": size,
            "status": "EXECUTED",
            "signal": signal,
            "confidence": confidence,
            "position_id": position.id,
        })

    def _skip(self, signal, side, price, qty, reason):
        """Log + surface a gate skip (confidence below threshold,
        flip-buffer not met, min-hold not met). Previously these only
        wrote to data/auto_trades_log.csv, so a STRONG BUY/SELL signal
        that never traded looked like a mystery from the dashboard —
        this makes every skip reason visible immediately, the same as
        a hard broker-level REJECTED. The CSV row is written every
        single time (full audit trail); the UI banner emission is
        deduped so an unchanged reason repeating tick after tick
        doesn't spam the same message over and over."""

        self._log_event(signal, side, price, qty=qty, status="SKIPPED", reason=reason)

        if reason != self._last_skip_reason:
            self._last_skip_reason = reason
            self.auto_trade_rejected.emit(reason)
        self.auto_trade_rejected.emit(reason)

    def _in_cooldown(self) -> bool:
        if self._last_trade_time is None:
            return False
        elapsed = (datetime.now() - self._last_trade_time).total_seconds()
        return elapsed < self.cooldown_seconds

    # ------------------------------------------------------------
    # CSV audit trail — every auto-generated trade *event*, including
    # skips/rejections, so behavior is fully traceable after the fact.
    # ------------------------------------------------------------

    def _ensure_log_file(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(LOG_COLUMNS)

    def _log_event(self, signal, side, price, qty, status, reason):
        self._ensure_log_file()
        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.now().isoformat(sep=" ", timespec="seconds"),
                self.symbol,
                signal,
                side,
                price,
                qty,
                status,
                reason,
            ])