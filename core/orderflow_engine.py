"""Compatibility façade for the feature-based order-flow strategy.

Existing UI and executor consumers keep reading the historical attributes on
``orderflow_engine``.  New analytics live in focused engines under core/ and
are composed by ``OrderFlowFeaturePipeline`` instead of one static score.
"""

from __future__ import annotations

import time
from collections import deque

from core.orderflow_features import OrderFlowFeaturePipeline


SIGNAL_FOR_SIDE = {"LONG": "🟢 STRONG BUY", "SHORT": "🔴 STRONG SELL"}


class OrderFlowEngine:
    def __init__(self):
        self.pipeline = OrderFlowFeaturePipeline()
        self.trades = deque(maxlen=200)  # retained for existing diagnostics
        self.buy_volume = self.sell_volume = self.delta = 0.0
        self.last_price = self.price = 0.0
        self.price_change = 0.0
        self.bid_liquidity = self.ask_liquidity = self.dom_pressure = 0.0
        self.volume_spike = self.whale = self.absorption = False
        self.smart_money = "NORMAL"
        self.signal = self.confirmed_signal = "WAIT"
        self.confidence = self.confirmed_confidence = 0.0
        self.buy_strength = self.sell_strength = 50.0
        self.market_regime = "ORDER FLOW"
        self.signal_hold_seconds = 3.0
        self._last_actionable_signal_time = None

    def process(self, data):
        event = data.get("event")
        if event == "trade":
            self.process_trade(data)
        elif event == "orderbook":
            self.process_orderbook(data)

    def process_trade(self, data):
        timestamp = float(data.get("timestamp", time.time()))
        try:
            price, size = float(data["price"]), float(data["size"])
        except (KeyError, TypeError, ValueError):
            return
        self.price_change = price - self.last_price if self.last_price else 0.0
        self.last_price = self.price = price
        decision = self.pipeline.on_trade(data)
        side = self.pipeline.flow.latest.last_side
        self.trades.append({"price": price, "size": size, "time": timestamp, "side": side})
        self._sync(decision, timestamp)

    def process_orderbook(self, data):
        timestamp = float(data.get("timestamp", time.time()))
        decision = self.pipeline.on_orderbook(data)
        self._sync(decision, timestamp)

    def _sync(self, decision, timestamp):
        book, flow, reaction = self.pipeline.book.latest, self.pipeline.flow.latest, self.pipeline.reaction.latest
        self.bid_liquidity, self.ask_liquidity = book.bid_liquidity, book.ask_liquidity
        self.dom_pressure = book.obi_weighted * 100.0
        self.buy_volume, self.sell_volume = flow.buy_volume_60s, flow.sell_volume_60s
        self.delta = flow.delta_60s
        self.buy_strength, self.sell_strength = flow.buy_aggression * 100.0, flow.sell_aggression * 100.0
        self.absorption = reaction.buyer_absorption or reaction.seller_absorption
        self.whale = flow.last_size > max((self.buy_volume + self.sell_volume) / 40.0, 50.0)
        self.volume_spike = self.whale
        if reaction.buyer_absorption: self.smart_money = "BUYER ABSORPTION"
        elif reaction.seller_absorption: self.smart_money = "SELLER ABSORPTION"
        elif book.ask_pull_score >= .20: self.smart_money = "ASK LIQUIDITY PULL"
        elif book.bid_pull_score >= .20: self.smart_money = "BID LIQUIDITY PULL"
        else: self.smart_money = "NORMAL"
        self.market_regime = self.smart_money
        self.confidence = decision.confidence
        self.signal = SIGNAL_FOR_SIDE.get(decision.side, "WAIT") if decision.confirmed else "WATCH" if decision.side else "WAIT"

        if decision.confirmed and decision.side:
            self.confirmed_signal = SIGNAL_FOR_SIDE[decision.side]
            self.confirmed_confidence = decision.confidence
            self._last_actionable_signal_time = timestamp
        elif self._last_actionable_signal_time is None or timestamp - self._last_actionable_signal_time >= self.signal_hold_seconds:
            self.confirmed_signal, self.confirmed_confidence = "WAIT", 0.0
            self._last_actionable_signal_time = None


orderflow_engine = OrderFlowEngine()
