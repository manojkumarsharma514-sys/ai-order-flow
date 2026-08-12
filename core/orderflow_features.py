"""Combines book, executed-flow and price-reaction evidence into entry features."""

from __future__ import annotations

from dataclasses import dataclass

from core.orderbook_engine import OrderBookEngine
from core.price_reaction_engine import PriceReactionEngine
from core.trade_flow_engine import TradeFlowEngine


@dataclass(frozen=True)
class EntryDecision:
    side: str | None
    confidence: float
    reason: str
    confirmed: bool


class OrderFlowFeaturePipeline:
    """One stateful source of microstructure features and entry decisions.

    It deliberately does not know higher-timeframe regime, balance, or order
    execution. Those remain the responsibility of the existing strategy and
    trading layers.
    """

    def __init__(self):
        self.book = OrderBookEngine()
        self.flow = TradeFlowEngine()
        self.reaction = PriceReactionEngine()
        self._candidate_side = None
        self._candidate_hits = 0
        self._decision = EntryDecision(None, 0.0, "warming_up", False)

    def on_orderbook(self, data):
        timestamp = float(data.get("timestamp", 0.0))
        self.book.update(data.get("bids", []), data.get("asks", []), timestamp)
        return self._evaluate()

    def on_trade(self, data):
        timestamp = float(data.get("timestamp", 0.0))
        flow = self.flow.update(data.get("price"), data.get("size"), data.get("buyer_role"), data.get("seller_role"), timestamp)
        self.reaction.update(flow.last_price, timestamp, flow.delta_5s,
                             self.book.latest.bid_replenishment, self.book.latest.ask_replenishment)
        return self._evaluate()

    def _evaluate(self):
        book, flow, reaction = self.book.latest, self.flow.latest, self.reaction.latest
        if not book.valid or flow.last_price is None:
            self._decision = EntryDecision(None, 0.0, "waiting_for_book_and_trades", False)
            return self._decision

        long_score = short_score = 0.0
        # Near-book state (not static 50-level size alone).
        if book.obi_near >= .15: long_score += 14
        if book.obi_near <= -.15: short_score += 14
        if book.obi_weighted >= .12: long_score += 8
        if book.obi_weighted <= -.12: short_score += 8
        if book.bid_added > book.bid_cancelled: long_score += 8
        if book.ask_added > book.ask_cancelled: short_score += 8
        if book.ask_pull_score >= .20: long_score += 8
        if book.bid_pull_score >= .20: short_score += 8

        # Executed aggression must agree across fast and slower horizons.
        if flow.delta_1s > 0 and flow.delta_5s > 0: long_score += 18
        if flow.delta_1s < 0 and flow.delta_5s < 0: short_score += 18
        if flow.delta_15s > 0 and flow.delta_60s >= 0: long_score += 10
        if flow.delta_15s < 0 and flow.delta_60s <= 0: short_score += 10

        # Absorption is directional evidence only when passive liquidity is
        # observed replenishing while aggressive flow cannot move price.
        if reaction.buyer_absorption: long_score += 22
        if reaction.seller_absorption: short_score += 22
        if reaction.buy_confirmed: long_score += 16
        if reaction.sell_confirmed: short_score += 16

        # Suspected ephemeral liquidity cannot create a trade; it only removes
        # confidence from the side it was advertising.
        long_score -= book.spoof_risk_bid * 20
        short_score -= book.spoof_risk_ask * 20
        long_score = max(0.0, min(100.0, long_score))
        short_score = max(0.0, min(100.0, short_score))
        side, confidence = ("LONG", long_score) if long_score > short_score else ("SHORT", short_score)
        if confidence < 62.0:
            side, reason = None, "insufficient_confluence"
        else:
            reason = "microstructure_confluence"

        if side and side == self._candidate_side:
            self._candidate_hits += 1
        elif side:
            self._candidate_side, self._candidate_hits = side, 1
        else:
            self._candidate_side, self._candidate_hits = None, 0
        self._decision = EntryDecision(side, confidence, reason, self._candidate_hits >= 3)
        return self._decision

    @property
    def decision(self): return self._decision
