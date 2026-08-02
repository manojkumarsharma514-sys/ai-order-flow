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
"""

import csv
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

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

    # ------------------------------------------------------------
    # Main entry point — called once per UI refresh tick from the
    # DashboardController, with the latest AI Engine readout.
    # ------------------------------------------------------------

    def evaluate(self, signal: str, confidence: float, price: float):

        if not self.enabled or self.trading_paused:
            return

        if price is None or price <= 0:
            return

        side = SIGNAL_SIDE_MAP.get(signal)
        if side is None:
            return  # WAIT / WATCH / ABSORPTION — not a high-conviction signal

        if confidence < self.confidence_threshold:
            self._log_event(signal, side, price, qty=0, status="SKIPPED", reason="confidence_below_threshold")
            return

        if self._in_cooldown():
            return

        # avoid stacking multiple auto positions in the same direction
        if any(p.source == "AI_AUTO" and p.side == side for p in self.paper_engine.positions):
            return

        # A STRONG BUY and STRONG SELL signal can both fire within a
        # session as the tape flips — without this, the bot would end
        # up holding a LONG and a SHORT on the same symbol at once
        # (self-hedging: real losses on both legs to spread/fees with
        # no net exposure). Flip: close the opposite-direction AI_AUTO
        # position first, then open the new one.
        opposite_side = "SHORT" if side == "LONG" else "LONG"
        for p in list(self.paper_engine.positions):
            if p.source == "AI_AUTO" and p.side == opposite_side:
                self.paper_engine.close_position(p.id, reason="ai_signal_flip")

        size = self.calculate_position_size(price)
        sl_pct = self._risk_params["stop_loss_pct"] / 100
        tp_pct = self._risk_params["take_profit_pct"] / 100

        # Keep the engine's margin-check cap in step with the leverage
        # this size was actually calculated against — otherwise a
        # dynamically-sized order at, say, 100x can get rejected by a
        # stale lower cap left over from a previous setting.
        self.paper_engine.max_leverage = self.leverage

        if side == "LONG":
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
        )

        self._last_trade_time = datetime.now()

        if position is None:
            self._log_event(
                signal, side, price, qty=size, status="REJECTED",
                reason=self.paper_engine.last_rejection or "unknown",
            )
            return

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
