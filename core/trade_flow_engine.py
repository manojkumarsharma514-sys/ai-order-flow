"""Executed-aggression, multi-horizon delta, and session CVD."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class TradeFlowFeatures:
    timestamp: float
    last_price: float | None
    last_size: float
    last_side: str | None
    delta_1s: float
    delta_5s: float
    delta_15s: float
    delta_30s: float
    delta_60s: float
    cvd: float
    buy_volume_60s: float
    sell_volume_60s: float
    buy_aggression: float
    sell_aggression: float
    unknown_volume_60s: float


class TradeFlowEngine:
    def __init__(self, retention_seconds: float = 120.0):
        self.retention_seconds = retention_seconds
        self._trades = deque()
        self._cvd = 0.0
        self._last_price = None
        self._last = TradeFlowFeatures(0.0, None, 0.0, None, 0, 0, 0, 0, 0, 0, 0, 0, .5, .5, 0)

    @staticmethod
    def classify(buyer_role, seller_role):
        if buyer_role == "taker" and seller_role != "taker":
            return "buy"
        if seller_role == "taker" and buyer_role != "taker":
            return "sell"
        return None

    def update(self, price, size, buyer_role, seller_role, timestamp: float) -> TradeFlowFeatures:
        try:
            price, size = float(price), float(size)
        except (TypeError, ValueError):
            return self._last
        if price <= 0 or size <= 0:
            return self._last
        side = self.classify(buyer_role, seller_role)
        signed = size if side == "buy" else -size if side == "sell" else 0.0
        self._cvd += signed
        self._last_price = price
        self._trades.append((timestamp, price, size, side))
        cutoff = timestamp - self.retention_seconds
        while self._trades and self._trades[0][0] < cutoff:
            self._trades.popleft()
        deltas = {window: self._delta(window, timestamp) for window in (1, 5, 15, 30, 60)}
        buy60, sell60, unknown = self._volumes(60, timestamp)
        known = buy60 + sell60
        buy_aggression = buy60 / known if known else .5
        self._last = TradeFlowFeatures(timestamp, price, size, side, deltas[1], deltas[5], deltas[15],
                                       deltas[30], deltas[60], self._cvd, buy60, sell60,
                                       buy_aggression, 1.0 - buy_aggression, unknown)
        return self._last

    def _delta(self, window, now):
        return sum(size if side == "buy" else -size if side == "sell" else 0.0
                   for ts, _, size, side in self._trades if ts >= now - window)

    def _volumes(self, window, now):
        buy = sell = unknown = 0.0
        for ts, _, size, side in self._trades:
            if ts < now - window:
                continue
            if side == "buy": buy += size
            elif side == "sell": sell += size
            else: unknown += size
        return buy, sell, unknown

    @property
    def latest(self):
        return self._last
