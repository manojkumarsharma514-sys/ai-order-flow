"""
trading/orders.py

OrdersManager
-------------
Persists every *completed* order (a position that has been closed —
manually, by hitting SL/TP, or by the AI auto-trade executor) to
data/orders_history.csv, and reloads that history back into memory on
launch so the ORDERS tab is populated immediately at startup — not
just from positions closed during the current session.

This is intentionally decoupled from PaperTradingEngine: the
controller wires `paper_engine.add_close_listener(orders_manager.record_close)`
so this file never needs to import trading.paper_trading.
"""

import os
from datetime import datetime
from pathlib import Path

import pandas as pd

ORDERS_CSV_PATH = Path("data") / "orders_history.csv"

COLUMNS = [
    "order_id",
    "opened_at",
    "closed_at",
    "symbol",
    "side",
    "qty",
    "entry_price",
    "exit_price",
    "stop_loss",
    "take_profit",
    "pnl_usd",
    "pnl_pct",
    "total_fee",
    "status",       # "FILLED" / "CANCELED"
    "source",       # "MANUAL" / "AI_AUTO"
    "close_reason", # "manual" / "stop" / "target"
]


class OrdersManager:

    def __init__(self, path: Path = ORDERS_CSV_PATH):
        self.path = Path(path)
        self._ensure_file()

    # ------------------------------------------------------------
    # File bootstrap
    # ------------------------------------------------------------

    def _ensure_file(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            pd.DataFrame(columns=COLUMNS).to_csv(self.path, index=False)

    # ------------------------------------------------------------
    # Writing — called from a PaperTradingEngine close-listener
    # ------------------------------------------------------------

    def record_close(self, position, status="FILLED"):
        """position: a trading.positions.Position that has already had
        mark_closed() called on it (paper_engine.close_position does
        this before firing the close-listener)."""

        row = {
            "order_id": position.id,
            "opened_at": position.opened_at.isoformat(sep=" ", timespec="seconds"),
            "closed_at": (position.closed_at or datetime.now()).isoformat(sep=" ", timespec="seconds"),
            "symbol": position.symbol,
            "side": position.side,
            "qty": position.size,
            "entry_price": position.entry_price,
            "exit_price": position.exit_price,
            "stop_loss": position.stop_loss,
            "take_profit": position.take_profit,
            "pnl_usd": round(position.realized_pnl, 4) if position.realized_pnl is not None else "",
            "pnl_pct": round(position.unrealized_pnl_pct(), 4),
            "total_fee": round(position.total_fee, 4),
            "status": status,
            "source": position.source,
            "close_reason": position.close_reason,
        }

        self.append_row(row)
        return row

    def append_row(self, row: dict):
        self._ensure_file()
        pd.DataFrame([row], columns=COLUMNS).to_csv(
            self.path, mode="a", header=False, index=False
        )

    # ------------------------------------------------------------
    # Reading — used both by AnalyticsEngine and ui/orders.py at launch
    # ------------------------------------------------------------

    def load_all(self) -> pd.DataFrame:
        self._ensure_file()
        try:
            df = pd.read_csv(self.path)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame(columns=COLUMNS)

        for col in ("opened_at", "closed_at"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors="coerce")

        return df

    def load_records(self) -> list:
        """Return orders history as a list of dicts (newest first) —
        handy for feeding straight into a QTableWidget."""

        df = self.load_all().sort_values("closed_at", ascending=False)
        return df.to_dict(orient="records")
