import itertools
from datetime import datetime


class Position:

    _id_counter = itertools.count(1)

    def __init__(self, symbol, side, size, entry_price, stop_loss=None,
                 take_profit=None, opened_at=None, source="MANUAL"):

        self.id = next(Position._id_counter)
        self.symbol = symbol
        self.side = side  # "LONG" or "SHORT"
        self.size = size
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.mark_price = entry_price

        # "MANUAL" (clicked Buy/Sell) or "AI_AUTO" (auto-trade executor)
        self.source = source

        self.opened_at = opened_at or datetime.now()
        self.closed_at = None
        self.close_reason = None   # "manual", "stop", "target", None
        self.exit_price = None
        self.realized_pnl = None

        # Fees (spec: Delta Exchange fee + 18% GST, charged on both the
        # entry fill and the exit fill). entry_fee is set immediately by
        # PaperTradingEngine.open_position(); exit_fee/total_fee are set
        # by mark_closed() at close time.
        self.entry_fee = 0.0
        self.exit_fee = 0.0
        self.total_fee = 0.0

    def update_mark(self, price):
        self.mark_price = float(price)

    def unrealized_pnl(self):
        if self.side == "LONG":
            return (self.mark_price - self.entry_price) * self.size
        return (self.entry_price - self.mark_price) * self.size

    def unrealized_pnl_pct(self):
        if not self.entry_price:
            return 0.0

        change = (self.mark_price - self.entry_price) / self.entry_price

        if self.side == "SHORT":
            change = -change

        return change * 100

    def hit_stop_or_target(self):
        """Returns 'stop', 'target', or None based on the current mark price."""

        if self.side == "LONG":
            if self.stop_loss and self.mark_price <= self.stop_loss:
                return "stop"
            if self.take_profit and self.mark_price >= self.take_profit:
                return "target"
        else:
            if self.stop_loss and self.mark_price >= self.stop_loss:
                return "stop"
            if self.take_profit and self.mark_price <= self.take_profit:
                return "target"

        return None

    def is_open_today(self, reference_date=None):
        reference_date = reference_date or datetime.now().date()
        return self.opened_at.date() == reference_date

    def mark_closed(self, exit_price, reason="manual", exit_fee=0.0):
        """Freeze the position's final numbers at the moment it's closed
        (called by PaperTradingEngine.close_position before it removes
        the position from the live `positions` list) so history/CSV
        consumers get a stable snapshot instead of a live-mutating mark.

        realized_pnl is NET of fees: gross P&L minus entry_fee (already
        charged at open) minus exit_fee — matching how a real exchange
        fill actually affects your balance."""

        self.exit_price = exit_price
        self.closed_at = datetime.now()
        self.close_reason = reason
        self.exit_fee = exit_fee
        self.total_fee = round(self.entry_fee + self.exit_fee, 4)
        self.realized_pnl = self.unrealized_pnl() - self.total_fee

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "size": self.size,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price if self.exit_price is not None else self.mark_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "source": self.source,
            "opened_at": self.opened_at,
            "closed_at": self.closed_at,
            "close_reason": self.close_reason,
            "pnl_usd": self.realized_pnl if self.realized_pnl is not None else self.unrealized_pnl(),
            "pnl_pct": self.unrealized_pnl_pct(),
            "entry_fee": self.entry_fee,
            "exit_fee": self.exit_fee,
            "total_fee": self.total_fee,
        }
