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

`evaluate()` takes `side` directly (from orderflow_engine.action_side,
itself derived from confirmed_signal — not the raw per-tick signal),
rather than re-deriving LONG/SHORT from a display string. This is the
single source of truth that ui/ai_panel.py's Signal Factor Breakdown
also renders from, so what the panel shows as "TRADING" is guaranteed
to be exactly what this method evaluates — no second, independently
re-parsed signal that can silently disagree with the screen.

PHASE 1 (audit baseline: 87/99 trades closed via ai_signal_flip, median
hold 4.27 min, fee drag = 76.5% of total loss): opposite-signal
flip-closes are no longer unconditional. Every flip is routed through
trading.exit_manager.ExitManager, which enforces a minimum hold time
and a flip-confidence buffer before an existing AI_AUTO position is
allowed to be closed in favor of a new opposite-direction one. A
blocked flip leaves the existing position open and untouched — its
Stop Loss / Take Profit continue to be enforced independently by
PaperTradingEngine.mark_to_market() every tick, regardless of this
class's decisions.

PHASE 2 (follow-up audit on the 117-trade legacy cohort: Sideways EMA
trend accounted for 62% of total loss at a 0% win rate; average gross
move per trade, 0.027%, was smaller than the 0.118% round-trip fee
cost; no daily loss limit or consecutive-loss circuit breaker existed
anywhere in the codebase). Three additions, all entry-quality /
risk-management gates rather than exit-timing changes (Phase 1 already
handles exit timing):

    1. Regime filter — entries and flips are blocked outright while
       the EMA 20/50 trend reads "Sideways" (see
       block_sideways_regime / _regime_permits_entry).
    2. Fee-edge filter — entries require the current ATR to imply a
       typical move at least `min_atr_fee_multiple` times the
       round-trip fee cost, so a trade has structural room to profit
       net of fees before it's even opened (see _edge_clears_fees).
    3. trading.risk_governor.RiskGovernor — a daily loss limit and a
       max-consecutive-losses circuit breaker, checked at the top of
       evaluate() before any other gate.

PHASE 3 (tick engine has no concept of trend — a single ~465-point
BTCUSD rally on 2026-08-11 produced 1,937 STRONG BUY and 2,686 STRONG
SELL signal events from core.orderflow_engine, nearly evenly split
fighting-vs-following the actual move, because it only reads the last
~200 raw trades). trading.signal_gate.SignalGate requires a tick
signal's direction to AGREE with the regime read from a completely
separate, FIXED-timeframe candle feed (strategy.regime_engine.
RegimeEngine — always 1H, never the chart's display timeframe) before
it's considered at all. Checked immediately after `side` is confirmed
actionable, ahead of confidence/cooldown/Sideways/fee-edge — regime
alignment is now the primary filter on tick-engine noise, not a
downstream cleanup gate.
"""

import csv
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from trading.exit_manager import ExitManager
from trading.risk_governor import RiskGovernor
from trading.signal_gate import SignalGate
from trading.fees import TAKER_FEE_RATE, GST_RATE

AUTO_TRADES_LOG_PATH = Path("data") / "auto_trades_log.csv"

# Round-trip cost as a % of notional: taker fee, doubled for entry +
# exit legs, with GST applied on top of each leg — matches
# trading/fees.py exactly (0.05% x 1.18 x 2 = 0.118%).
ROUND_TRIP_FEE_PCT = TAKER_FEE_RATE * (1 + GST_RATE) * 2 * 100

LOG_COLUMNS = ["timestamp", "symbol", "signal", "side", "price", "qty", "status", "reason"]

# Map the controller's confirmed display signal into the executor's
# normalized internal position side.
SIGNAL_SIDE_MAP = {
    "🟢 STRONG BUY": "LONG",
    "🔴 STRONG SELL": "SHORT",
}


class AutoTradeExecutor(QObject):

    auto_trade_executed = pyqtSignal(dict)  # {side, price, qty, status, reason, ...}
    # Lets the dashboard show why an otherwise valid auto-trade could
    # not be opened, rather than failing silently after a paper-engine
    # margin or validation rejection.
    auto_trade_rejected = pyqtSignal(str)

    def __init__(self, paper_engine, symbol="BTCUSD",
                 confidence_threshold=55, cooldown_seconds=20,
                 log_path: Path = AUTO_TRADES_LOG_PATH,
                 exit_manager: ExitManager = None,
                 risk_governor: RiskGovernor = None,
                 signal_gate: SignalGate = None,
                 min_atr_fee_multiple: float = 1.5,
                 block_sideways_regime: bool = True):
        super().__init__()

        self.paper_engine = paper_engine
        self.symbol = symbol
        self.confidence_threshold = confidence_threshold
        self.cooldown_seconds = cooldown_seconds
        self.log_path = Path(log_path)

        # Phase 1 gate — injectable so tests/config can supply a
        # pre-configured instance; otherwise builds one from
        # environment variables / class defaults (see
        # trading/exit_manager.py: MIN_HOLD_MINUTES, FLIP_CONFIDENCE_DELTA).
        self.exit_manager = exit_manager or ExitManager()

        # Phase 2 gate 3 — daily loss limit + consecutive-loss circuit
        # breaker (see trading/risk_governor.py). Wired directly to
        # PaperTradingEngine's close-listener list so it sees every
        # position close (manual, SL/TP, or AI_AUTO) the same way
        # Orders/Journal already do — no controller changes needed for
        # the closing side of this gate.
        self.risk_governor = risk_governor or RiskGovernor()
        self.paper_engine.add_close_listener(self.risk_governor.on_position_closed)

        # PHASE 3 gate — requires the tick engine's confirmed signal to
        # agree with the fixed-timeframe regime (see
        # trading/signal_gate.py + strategy/regime_engine.py) before
        # it's considered at all. Runs earliest of the entry-quality
        # gates, ahead of confidence/cooldown/Sideways/fee-edge — see
        # evaluate() below.
        self.signal_gate = signal_gate or SignalGate()

        # Phase 2 gates 1 & 2 — configurable via Settings (pushed in by
        # DashboardController._apply_settings_to_live_controls, same
        # pattern as leverage/margin_pct below) or the constructor
        # defaults here.
        self.min_atr_fee_multiple = min_atr_fee_multiple
        self.block_sideways_regime = block_sideways_regime

        self.enabled = True          # driven by AI AUTO TRADING toggle
        self.trading_paused = False  # driven by Stop Bot / AUTO MODE off, if desired

        self._last_trade_time = None
        self._risk_params = {
            # "size" is no longer used to place orders (see
            # _calculate_position_size) — kept only as a manual-override
            # ceiling if you ever want one; ignore/remove if unused.
            "size": 1.0,
            "stop_loss_pct": 0.5,   # % away from entry
            "take_profit_pct": 1.5,
        }

        # Dynamic Position Sizing (previously hardcoded to size=1.0 on
        # every auto-trade regardless of account balance):
        #
        #   Total Purchasing Power = Balance x Leverage
        #   Allocated Capital ($)  = Purchasing Power x Margin Usage %
        #   Position Size (BTC)    = Allocated Capital / Current Price
        #
        # Defaults match the spec: 25x leverage, 50% margin usage.
        self.leverage = 25
        self.margin_pct = 0.50

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

    def set_min_atr_fee_multiple(self, value: float):
        try:
            self.min_atr_fee_multiple = max(0.0, float(value))
        except (TypeError, ValueError):
            pass

    def set_block_sideways_regime(self, value: bool):
        self.block_sideways_regime = bool(value)

    def set_signal_gate_enabled(self, value: bool):
        self.signal_gate.set_enabled(value)

    # ------------------------------------------------------------
    # PHASE 2 gate helpers
    # ------------------------------------------------------------

    def _regime_permits_entry(self, ema_trend: str) -> bool:
        """Blocks both fresh entries and flip-driven re-entries while
        the EMA 20/50 trend reads Sideways — the audit found this
        regime accounted for 62% of legacy total loss at a 0% win
        rate. `ema_trend` degrades gracefully: None/"--"/unknown
        values are treated as "not confirmed Sideways" (permitted),
        since blocking on missing data would stop trading entirely
        before enough candles exist."""

        if not self.block_sideways_regime:
            return True
        return str(ema_trend or "").strip().lower() != "sideways"

    def _edge_clears_fees(self, atr: float, price: float) -> bool:
        """Requires the current ATR (as a % of price) to imply a
        typical move at least `min_atr_fee_multiple` x the round-trip
        fee cost. Audit finding: average gross move per trade (0.027%)
        was smaller than the round-trip fee (0.118%) — trades were
        structurally unable to clear their own costs regardless of
        directional accuracy. Fails OPEN (permits the trade) when ATR
        isn't yet available, consistent with how the ATR-based SL/TP
        below already degrades to the flat-percentage fallback rather
        than blocking all trading during candle warm-up."""

        if self.min_atr_fee_multiple <= 0:
            return True
        if not atr or not price or price <= 0:
            return True  # ATR not ready yet — fail open, not closed

        atr_pct = (atr / price) * 100
        return atr_pct >= (ROUND_TRIP_FEE_PCT * self.min_atr_fee_multiple)

    # ------------------------------------------------------------
    # Main entry point — called once per UI refresh tick from the
    # DashboardController, with the engine's canonical action decision.
    # ------------------------------------------------------------

    def evaluate(self, side: str = None, confidence: float = 0.0,
                 price: float = None, signal_label: str = "",
                 indicators_ready: bool = True, *, signal: str = None,
                 atr: float = None, ema_trend: str = None):
        """
        side:              "LONG" | "SHORT" | None — MUST come from
                            orderflow_engine.action_side (derived from
                            confirmed_signal, not the raw per-tick
                            signal). Never re-derive this from a
                            display string inside this method.
        confidence:        orderflow_engine.confidence (raw float, not
                            the UI's rounded/truncated display value).
        price:              latest traded price.
        signal_label:      human-readable signal string, used only for
                            the CSV audit log — never for decisions.
        indicators_ready:  EXPLICIT guard. orderflow_engine only sets
                            its own indicators_ready=True once it has
                            received at least one real VWAP/RSI/ATR
                            reading from the controller (which itself
                            waits for >=15 candles before calling in).
                            Checked explicitly here so the protection
                            can't be silently lost by a future refactor
                            that calls evaluate() from a different code
                            path.
        ema_trend:         PHASE 2 — "Uptrend" / "Downtrend" / "Sideways"
                            / None, from strategy.trend.ema_trend (the
                            controller passes its cached
                            self._latest_ema_trend). Used by the
                            Sideways-regime gate below.
        """

        # The controller currently passes signal=confirmed_signal. Keep
        # the executor compatible with that call while using LONG/SHORT
        # internally for all position decisions.
        if signal is not None:
            signal_label = signal
            side = SIGNAL_SIDE_MAP.get(str(signal).strip())

        if not indicators_ready:
            self._log_event(signal_label, side or "NONE", price, qty=0,
                             status="SKIPPED", reason="indicators_not_ready")
            return

        if not self.enabled or self.trading_paused:
            return

        # ------------------------------------------------------------
        # PHASE 2, gate 3: daily loss limit + consecutive-loss circuit
        # breaker. Checked before anything else that could open a new
        # position — a tripped breaker blocks ALL new AI_AUTO entries
        # and flips for the rest of the trading day, but never touches
        # already-open positions (their SL/TP keep running normally
        # via PaperTradingEngine.mark_to_market()).
        # ------------------------------------------------------------
        governor_decision = self.risk_governor.trading_allowed()
        if not governor_decision.allowed:
            self._log_event(signal_label, side or "NONE", price, qty=0,
                             status="SKIPPED", reason=governor_decision.reason)
            self.auto_trade_rejected.emit(
                f"{governor_decision.reason} (daily_pnl={governor_decision.daily_pnl_usd:.2f}, "
                f"consecutive_losses={governor_decision.consecutive_losses})"
            )
            return

        if price is None or price <= 0:
            return

        if side not in ("LONG", "SHORT"):
            return  # not a confirmed, actionable signal (WAIT / WATCH / ABSORPTION / None)

        # ------------------------------------------------------------
        # PHASE 3: SignalGate — regime is now the FIRST filter, not an
        # afterthought applied to the tick engine's raw output. See
        # trading/signal_gate.py. `ema_trend` here is sourced from
        # strategy.regime_engine.RegimeEngine via the controller — a
        # FIXED timeframe, independent of the chart's own display
        # timeframe and independent of the tick-based signal itself.
        # A signal fighting the higher-timeframe trend (or firing
        # during a Sideways regime) is rejected here, before it ever
        # reaches the confidence/cooldown/fee-edge gates below.
        # ------------------------------------------------------------
        gate_decision = self.signal_gate.evaluate(side=side, regime=ema_trend)
        if not gate_decision.allowed:
            self._log_event(signal_label, side, price, qty=0,
                             status="SKIPPED", reason=gate_decision.reason)
            self.auto_trade_rejected.emit(
                f"Entry blocked — {side} signal disagrees with regime "
                f"({ema_trend or 'unknown'})"
            )
            return

        if confidence < self.confidence_threshold:
            self._log_event(signal_label, side, price, qty=0, status="SKIPPED", reason="confidence_below_threshold")
            return

        if self._in_cooldown():
            return

        # ------------------------------------------------------------
        # PHASE 2, gates 1 & 2: regime filter + fee-edge filter.
        # Applied to ANY new-position-opening path below — a fresh
        # entry or a flip-driven re-entry — since both are the same
        # underlying decision ("is this a good place to be positioned
        # at all"), and the audit found this to be the actual
        # bottleneck once Phase 1 stopped the whipsaw churn: entries
        # were structurally fine on R:R but concentrated in a 0%-win
        # regime and priced without regard to whether a typical move
        # could even clear the round-trip fee.
        # ------------------------------------------------------------
        if not self._regime_permits_entry(ema_trend):
            self._log_event(signal_label, side, price, qty=0,
                             status="SKIPPED", reason="regime_sideways_blocked")
            self.auto_trade_rejected.emit(
                f"Entry blocked — EMA trend is Sideways (confidence {confidence:.0f}%)"
            )
            return

        if not self._edge_clears_fees(atr, price):
            self._log_event(signal_label, side, price, qty=0,
                             status="SKIPPED", reason="expected_move_below_fee_floor")
            self.auto_trade_rejected.emit(
                f"Entry blocked — ATR-implied move too small to clear round-trip fees "
                f"(need >={self.min_atr_fee_multiple:.1f}x {ROUND_TRIP_FEE_PCT:.3f}%)"
            )
            return

        # avoid stacking multiple auto positions in the same direction
        if any(p.source == "AI_AUTO" and p.side == side for p in self.paper_engine.positions):
            return

        # ------------------------------------------------------------
        # PHASE 1: opposite-direction flip gate
        # ------------------------------------------------------------
        # A STRONG BUY and STRONG SELL signal can both fire within a
        # session as the tape flips. Previously this loop closed the
        # opposite-side AI_AUTO position unconditionally and always
        # proceeded to open the new one — that unconditional flip is
        # exactly what produced 87/99 trades exiting via
        # ai_signal_flip at a 4.27-minute median hold (audit baseline).
        #
        # Now: every opposite-side AI_AUTO position is routed through
        # ExitManager.evaluate_flip(), which enforces a minimum hold
        # time and a flip-confidence buffer. If EITHER gate blocks the
        # flip, this method returns immediately WITHOUT closing the
        # existing position and WITHOUT opening the new one — the
        # reversal signal is ignored outright, per spec ("ignore the
        # reversal signal and retain the current open position").
        # Stop Loss / Take Profit on the retained position are
        # completely unaffected: they're enforced independently by
        # PaperTradingEngine.mark_to_market() on every tick regardless
        # of what happens here.
        opposite_side = "SHORT" if side == "LONG" else "LONG"
        blocking_position = next(
            (p for p in self.paper_engine.positions
             if p.source == "AI_AUTO" and p.side == opposite_side),
            None,
        )

        if blocking_position is not None:
            decision = self.exit_manager.evaluate_flip(
                position=blocking_position,
                new_side=side,
                new_confidence=confidence,
            )

            if not decision.allowed:
                self._log_event(signal_label, side, price, qty=0,
                                 status="SKIPPED", reason=decision.reason)
                self.auto_trade_rejected.emit(
                    f"Flip blocked ({decision.reason}) — keeping existing "
                    f"{blocking_position.side} position open"
                )
                return  # existing position stays open exactly as-is; SL/TP untouched

            # Gates cleared — proceed with the flip.
            self.paper_engine.close_position(blocking_position.id, reason="ai_signal_flip")

        size = self.calculate_position_size(price)
        sl_pct = self._risk_params["stop_loss_pct"] / 100
        tp_pct = self._risk_params["take_profit_pct"] / 100

        # Keep the engine's margin-check cap in step with the leverage
        # this size was actually calculated against — otherwise a
        # dynamically-sized order at, say, 100x can get rejected by a
        # stale lower cap left over from a previous setting.
        self.paper_engine.max_leverage = self.leverage

        # Use volatility-scaled exits where ATR is available. The fixed
        # percentage values remain the startup fallback before ATR exists.
        try:
            atr_value = float(atr) if atr is not None else 0.0
        except (TypeError, ValueError):
            atr_value = 0.0

        if atr_value > 0:
            stop_distance = atr_value * 1.5
            target_distance = atr_value * 3.0  # 1:2 gross R:R
            if side == "LONG":
                stop_loss = price - stop_distance
                take_profit = price + target_distance
            else:
                stop_loss = price + stop_distance
                take_profit = price - target_distance
        elif side == "LONG":
            stop_loss = price * (1 - sl_pct)
            take_profit = price * (1 + tp_pct)
        else:
            stop_loss = price * (1 + sl_pct)
            take_profit = price * (1 - tp_pct)

        position = self.paper_engine.open_position(
            side=side,
            size=size,
            entry_price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source="AI_AUTO",
            entry_confidence=confidence,  # baseline for this position's own future flip-confidence check
        )

        if position is None:
            reason = self.paper_engine.last_rejection or "unknown"
            self._log_event(
                signal_label, side, price, qty=size, status="REJECTED",
                reason=reason,
            )
            self.auto_trade_rejected.emit(reason)
            return

        # A rejected order must not consume the entry cooldown.
        self._last_trade_time = datetime.now()

        self._log_event(signal_label, side, price, qty=size, status="EXECUTED", reason="ai_signal")

        self.auto_trade_executed.emit({
            "side": side,
            "price": price,
            "qty": size,
            "status": "EXECUTED",
            "signal": signal_label,
            "confidence": confidence,
            "position_id": position.id,
        })

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