"""Measures whether executed pressure actually moves price."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class PriceReaction:
    return_1s: float
    return_5s: float
    buy_confirmed: bool
    sell_confirmed: bool
    buyer_absorption: bool
    seller_absorption: bool


class PriceReactionEngine:
    def __init__(self, retention_seconds: float = 20.0, min_move_bps: float = 1.0):
        self.retention_seconds = retention_seconds
        self.min_move_bps = min_move_bps
        self._prices = deque()
        self._last = PriceReaction(0, 0, False, False, False, False)

    def update(self, price, timestamp, delta_5s, bid_replenishment=0.0, ask_replenishment=0.0):
        try: price = float(price)
        except (TypeError, ValueError): return self._last
        self._prices.append((timestamp, price))
        while self._prices and self._prices[0][0] < timestamp - self.retention_seconds:
            self._prices.popleft()
        r1, r5 = self._return(1, timestamp, price), self._return(5, timestamp, price)
        threshold = self.min_move_bps / 10000.0
        buy_confirmed = delta_5s > 0 and r1 >= threshold
        sell_confirmed = delta_5s < 0 and r1 <= -threshold
        buyer_absorption = delta_5s < 0 and abs(r1) < threshold and bid_replenishment > 0
        seller_absorption = delta_5s > 0 and abs(r1) < threshold and ask_replenishment > 0
        self._last = PriceReaction(r1, r5, buy_confirmed, sell_confirmed, buyer_absorption, seller_absorption)
        return self._last

    def _return(self, seconds, now, current):
        base = next((price for ts, price in self._prices if ts >= now - seconds), current)
        return (current - base) / base if base else 0.0

    @property
    def latest(self): return self._last
