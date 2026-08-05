"""
strategy/analytics.py

AnalyticsEngine
---------------
Reads data/orders_history.csv (the single source of truth for closed
trades — trade_journal.csv carries the same closes plus notes/strategy
metadata) and computes the dashboard's performance metrics:

    Win Rate (%), Total Realized PnL ($), Profit Factor, Max Drawdown
    (%), Average Risk/Reward Ratio, Total Trades (Long vs Short)

Call `recompute()` any time a position closes (the controller does
this from the same close-listener that feeds Orders/Journal) — it
overwrites data/analytics_summary.csv with the latest snapshot.
"""

from pathlib import Path

import pandas as pd

from trading.orders import OrdersManager

from core.runtime_paths import DATA_DIR
ANALYTICS_CSV_PATH = DATA_DIR / "analytics_summary.csv"

EMPTY_METRICS = {
    "win_rate_pct": 0.0,
    "total_realized_pnl": 0.0,
    "profit_factor": 0.0,
    "max_drawdown_pct": 0.0,
    "avg_risk_reward": 0.0,
    "total_trades": 0,
    "long_trades": 0,
    "short_trades": 0,
    "win_count": 0,
    "loss_count": 0,
    "updated_at": "",
}


class AnalyticsEngine:

    def __init__(self, orders_manager: OrdersManager = None, path: Path = ANALYTICS_CSV_PATH):
        self.orders_manager = orders_manager or OrdersManager()
        self.path = Path(path)

    def compute(self) -> dict:
        df = self.orders_manager.load_all()

        if df.empty:
            return dict(EMPTY_METRICS, updated_at=pd.Timestamp.now().isoformat(sep=" ", timespec="seconds"))

        df["pnl_usd"] = pd.to_numeric(df["pnl_usd"], errors="coerce").fillna(0.0)

        wins = df[df["pnl_usd"] > 0]
        losses = df[df["pnl_usd"] < 0]

        total_trades = len(df)
        win_rate = (len(wins) / total_trades * 100) if total_trades else 0.0

        gross_profit = wins["pnl_usd"].sum()
        gross_loss = abs(losses["pnl_usd"].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (
            float("inf") if gross_profit > 0 else 0.0
        )

        total_realized_pnl = df["pnl_usd"].sum()

        # Max drawdown off the cumulative realized-PnL equity curve,
        # ordered by close time (the only ordering that's meaningful).
        ordered = df.sort_values("closed_at")
        equity_curve = ordered["pnl_usd"].cumsum()
        running_peak = equity_curve.cummax()
        drawdown = running_peak - equity_curve
        # express as % of peak equity reached so far (avoid div-by-zero
        # before any profit has accrued). Use float NaN, not pd.NA —
        # pd.NA is pandas' newer nullable-dtype sentinel and doesn't
        # always coerce cleanly through arithmetic + float(); NaN does.
        safe_peak = running_peak.replace(0, float("nan"))
        drawdown_pct = (drawdown / safe_peak).astype(float)
        drawdown_pct = drawdown_pct.replace([float("inf"), float("-inf")], 0).fillna(0) * 100
        max_drawdown_pct = float(drawdown_pct.max()) if not drawdown_pct.empty else 0.0
        if pd.isna(max_drawdown_pct):
            max_drawdown_pct = 0.0

        # Average Risk/Reward realized: |take_profit - entry| / |entry - stop_loss|
        rr_df = df.dropna(subset=["entry_price", "stop_loss", "take_profit"])
        if not rr_df.empty:
            risk = (rr_df["entry_price"] - rr_df["stop_loss"]).abs()
            reward = (rr_df["take_profit"] - rr_df["entry_price"]).abs()
            valid = risk > 0
            avg_rr = float((reward[valid] / risk[valid]).mean()) if valid.any() else 0.0
        else:
            avg_rr = 0.0

        long_trades = int((df["side"] == "LONG").sum())
        short_trades = int((df["side"] == "SHORT").sum())
        win_count = int(len(wins))
        loss_count = int(len(losses))

        return {
            "win_rate_pct": round(win_rate, 2),
            "total_realized_pnl": round(float(total_realized_pnl), 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else "inf",
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "avg_risk_reward": round(avg_rr, 2),
            "total_trades": total_trades,
            "long_trades": long_trades,
            "short_trades": short_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "updated_at": pd.Timestamp.now().isoformat(sep=" ", timespec="seconds"),
        }

    def recompute(self) -> dict:
        """Compute metrics and persist the summary row to
        data/analytics_summary.csv (appends one row per recompute, so
        the file also doubles as a metrics-over-time log)."""

        metrics = self.compute()

        self.path.parent.mkdir(parents=True, exist_ok=True)
        row_df = pd.DataFrame([metrics])

        if self.path.exists() and self.path.stat().st_size > 0:
            row_df.to_csv(self.path, mode="a", header=False, index=False)
        else:
            row_df.to_csv(self.path, index=False)

        return metrics

    def latest_saved(self) -> dict:
        if not self.path.exists():
            return dict(EMPTY_METRICS)
        try:
            df = pd.read_csv(self.path)
        except pd.errors.EmptyDataError:
            return dict(EMPTY_METRICS)
        if df.empty:
            return dict(EMPTY_METRICS)
        return df.iloc[-1].to_dict()
