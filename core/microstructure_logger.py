"""
core/microstructure_logger.py

MicrostructureLogger
---------------------
CSV audit trail for the raw microstructure features that drive
OrderFlowFeaturePipeline's entry decisions (see core/orderflow_features.py,
core/orderbook_engine.py, core/trade_flow_engine.py,
core/price_reaction_engine.py) — order-book imbalance, executed-flow
delta, price-reaction confirmation/absorption, and spoof-risk, plus the
resulting EntryDecision.

This is a *diagnostics* log, not a trading-decision log (that's
trading/executor.py's auto_trades_log.csv, which only records what the
executor actually acted on) — this one exists so the raw features
feeding *every* entry/no-entry read can be reviewed after the fact,
the same way trade-level decisions already are audited via
auto_trades_log.csv / flip_decisions_log.csv / risk_governor_log.csv.

Written on a throttled interval (default 1s) rather than every tick,
since book/flow features can update many times per second on a busy
feed and a row-per-tick log would grow unmanageably large without
adding diagnostic value beyond what a 1-second sampling already
captures — same reasoning as WebSocketThread's 10s ticker poll.
"""

import csv
import time
from pathlib import Path

from core.runtime_paths import DATA_DIR

MICROSTRUCTURE_LOG_PATH = DATA_DIR / "microstructure_log.csv"

COLUMNS = [
    "timestamp", "price",
    # order book (core.orderbook_engine.BookFeatures)
    "obi_near", "obi_weighted",
    "bid_added", "bid_cancelled", "ask_added", "ask_cancelled",
    "bid_pull_score", "ask_pull_score",
    "bid_replenishment", "ask_replenishment",
    "bid_liquidity", "ask_liquidity",
    "spoof_risk_bid", "spoof_risk_ask",
    # trade flow (core.trade_flow_engine.TradeFlowFeatures)
    "delta_1s", "delta_5s", "delta_15s", "delta_30s", "delta_60s",
    "cvd", "buy_volume_60s", "sell_volume_60s",
    "buy_aggression", "sell_aggression",
    # price reaction (core.price_reaction_engine.PriceReaction)
    "return_1s", "return_5s",
    "buy_confirmed", "sell_confirmed",
    "buyer_absorption", "seller_absorption",
    # resulting entry decision (core.orderflow_features.EntryDecision)
    "decision_side", "decision_confidence", "decision_reason", "decision_confirmed",
]


class MicrostructureLogger:

    def __init__(self, path: Path = MICROSTRUCTURE_LOG_PATH, min_interval_seconds: float = 1.0):
        self.path = Path(path)
        self.min_interval_seconds = min_interval_seconds
        self._last_write = 0.0
        self._ensure_log_file()

    def _ensure_log_file(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            with open(self.path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(COLUMNS)

    def maybe_log(self, pipeline, price=None, decision=None, now: float = None) -> bool:
        """
        Throttled log — safe to call once per UI tick; only actually
        writes a row every `min_interval_seconds`.

        pipeline: a core.orderflow_features.OrderFlowFeaturePipeline
                  instance (exposes .book / .flow / .reaction, each
                  with a `.latest` dataclass).
        price:    latest traded price, for readability in the CSV —
                  purely cosmetic, no feature math depends on it here.
        decision: optional core.orderflow_features.EntryDecision to
                  record alongside the features that produced it.
                  Defaults to pipeline.decision when omitted.

        Returns True if a row was actually written, False if skipped
        (throttled, or the book hasn't produced a valid snapshot yet —
        e.g. before both bids and asks have been seen at least once).
        """

        now = now if now is not None else time.time()
        if now - self._last_write < self.min_interval_seconds:
            return False

        book = pipeline.book.latest
        if not book.valid:
            return False

        decision = decision if decision is not None else getattr(pipeline, "decision", None)

        self._last_write = now
        self._write_row(book, pipeline.flow.latest, pipeline.reaction.latest, price, decision)
        return True

    def _write_row(self, book, flow, reaction, price, decision):
        self._ensure_log_file()

        decision_side = getattr(decision, "side", "") or ""
        decision_confidence = getattr(decision, "confidence", "")
        decision_reason = getattr(decision, "reason", "")
        decision_confirmed = getattr(decision, "confirmed", "")

        with open(self.path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                round(book.timestamp, 3),
                price if price is not None else "",
                round(book.obi_near, 4), round(book.obi_weighted, 4),
                round(book.bid_added, 4), round(book.bid_cancelled, 4),
                round(book.ask_added, 4), round(book.ask_cancelled, 4),
                round(book.bid_pull_score, 4), round(book.ask_pull_score, 4),
                round(book.bid_replenishment, 4), round(book.ask_replenishment, 4),
                round(book.bid_liquidity, 4), round(book.ask_liquidity, 4),
                round(book.spoof_risk_bid, 4), round(book.spoof_risk_ask, 4),
                round(flow.delta_1s, 4), round(flow.delta_5s, 4), round(flow.delta_15s, 4),
                round(flow.delta_30s, 4), round(flow.delta_60s, 4),
                round(flow.cvd, 4), round(flow.buy_volume_60s, 4), round(flow.sell_volume_60s, 4),
                round(flow.buy_aggression, 4), round(flow.sell_aggression, 4),
                round(reaction.return_1s, 6), round(reaction.return_5s, 6),
                reaction.buy_confirmed, reaction.sell_confirmed,
                reaction.buyer_absorption, reaction.seller_absorption,
                decision_side, decision_confidence, decision_reason, decision_confirmed,
            ])


# Module-level singleton, same pattern as core.orderflow_engine.orderflow_engine
# and core.ai_state.ai_state — one shared instance for the whole app.
microstructure_logger = MicrostructureLogger()
