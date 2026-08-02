from trading.positions import Position
from trading.fees import calculate_fee


class PaperTradingEngine:
    """
    Simulated (paper) trading only — this never sends real orders to
    Delta Exchange or any exchange. It exists purely to drive the
    dashboard's Positions + Trade Setup panels with a real, working
    simulation: a starting virtual balance, open positions, and
    realized/unrealized P&L tracked against live mark prices.

    Wiring this up to actually place real live orders is a separate,
    much bigger step (API keys, order routing, risk controls) that
    should be done deliberately later, not silently included here.

    `on_position_closed` hooks: any callable registered via
    `add_close_listener(fn)` is invoked as `fn(position)` right after a
    position is closed (manually, by SL/TP, or by the AI auto-trade
    executor). This is how Orders/Journal/Analytics CSV logging gets
    wired up without paper_trading.py needing to import them directly.
    """

    def __init__(self, starting_balance=10000.0, symbol="BTCUSD", max_leverage=20):
        self.symbol = symbol
        self.starting_balance = starting_balance
        self.balance = starting_balance
        self.realized_pnl = 0.0
        self.positions = []

        # simple margin guardrail: notional exposure of a new position
        # can't exceed equity * max_leverage. Without this, the size
        # field has no limit and P&L math (which is otherwise correct)
        # can spiral to absurd numbers on a fat-fingered size.
        self.max_leverage = max_leverage

        # last rejection reason (set by open_position when it returns None),
        # so the UI can show *why* an order was rejected instead of just
        # silently doing nothing.
        self.last_rejection = None

        self._close_listeners = []
        self._open_listeners = []

    # ------------------------------------------------------------
    # Listener registration (Orders / Journal / Analytics hook in here)
    # ------------------------------------------------------------

    def add_close_listener(self, fn):
        self._close_listeners.append(fn)

    def add_open_listener(self, fn):
        self._open_listeners.append(fn)

    def _notify_opened(self, position):
        for fn in self._open_listeners:
            try:
                fn(position)
            except Exception as e:
                print(f"open-listener error: {e}")

    def _notify_closed(self, position):
        for fn in self._close_listeners:
            try:
                fn(position)
            except Exception as e:
                print(f"close-listener error: {e}")

    # ------------------------------------------------------------
    # Order entry
    # ------------------------------------------------------------

    def open_position(self, side, size, entry_price, stop_loss=None,
                       take_profit=None, source="MANUAL"):

        if size <= 0 or entry_price <= 0:
            self.last_rejection = "Enter a valid size and entry price"
            print(f"⛔ Order rejected: {self.last_rejection}")
            return None

        notional = size * entry_price
        required_margin = notional / self.max_leverage if self.max_leverage else notional
        max_notional = self.equity() * self.max_leverage

        # Trading fee on this fill (spec section 4: Delta Exchange fee
        # structure + 18% GST). Every fill here is an instant market-
        # style execution (no resting limit order book), so this is a
        # Taker fill — see trading/fees.py.
        entry_fee_breakdown = calculate_fee(notional, is_maker=False)
        entry_fee = entry_fee_breakdown["total_fee"]

        # insufficient balance: the margin this order needs (plus the
        # entry fee it will immediately incur) is more than the free
        # balance actually available right now.
        if required_margin + entry_fee > self.balance:
            self.last_rejection = (
                f"Insufficient balance: needs {required_margin:,.2f} USDT margin + "
                f"{entry_fee:,.2f} USDT fee, only {self.balance:,.2f} USDT available"
            )
            print(f"⛔ Order rejected: {self.last_rejection}")
            return None

        if max_notional > 0 and notional > max_notional:
            self.last_rejection = (
                f"Order rejected: {size} @ {entry_price:,.1f} = "
                f"{notional:,.0f} notional exceeds {self.max_leverage}x "
                f"of equity ({max_notional:,.0f} max)"
            )
            print(f"⛔ {self.last_rejection}")
            return None

        self.last_rejection = None

        position = Position(
            symbol=self.symbol,
            side=side,
            size=size,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            source=source,
        )
        position.entry_fee = entry_fee

        # NOTE: entry_fee is computed and stored on the position now
        # (so it's known/reportable immediately), but not subtracted
        # from balance here — that happens once, atomically, at close
        # time (see close_position), together with exit_fee. Deducting
        # it twice — once here, once again as part of total_fee at
        # close — would double-charge every trade.

        self.positions.append(position)
        self._notify_opened(position)

        return position

    def reset(self):
        """Wipe all positions and restore the starting paper balance."""

        self.positions = []
        self.balance = self.starting_balance
        self.realized_pnl = 0.0

    def close_position(self, position_id, reason="manual"):

        for p in self.positions:
            if p.id == position_id:
                exit_notional = p.size * p.mark_price
                exit_fee = calculate_fee(exit_notional, is_maker=False)["total_fee"]

                p.mark_closed(exit_price=p.mark_price, reason=reason, exit_fee=exit_fee)
                pnl = p.realized_pnl  # already net of entry_fee + exit_fee
                self.realized_pnl += pnl
                self.balance += pnl
                self.positions.remove(p)
                self._notify_closed(p)
                return pnl

        return None

    def close_all(self, reason="manual"):

        closed_pnl = 0.0

        for p in list(self.positions):
            result = self.close_position(p.id, reason=reason)
            if result is not None:
                closed_pnl += result

        return closed_pnl

    def mark_to_market(self, price):
        """Update every open position's mark price and auto-close any
        that have hit their stop loss or take profit."""

        try:
            price = float(price)
        except (TypeError, ValueError):
            return

        for p in list(self.positions):
            p.update_mark(price)

            hit = p.hit_stop_or_target()
            if hit:
                self.close_position(p.id, reason=hit)

    def total_unrealized_pnl(self):
        return sum(p.unrealized_pnl() for p in self.positions)

    def equity(self):
        return self.balance + self.total_unrealized_pnl()
