"""Stateful L2 order-book analytics.

The exchange currently supplies book snapshots.  This module compares each
snapshot with the previous canonical price map; it therefore reports observed
adds/removals, rather than claiming to know exchange order IDs or intent.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import isfinite
from typing import Dict, Iterable, Tuple


@dataclass(frozen=True)
class BookFeatures:
    timestamp: float
    best_bid: float | None
    best_ask: float | None
    spread: float | None
    obi_near: float
    obi_weighted: float
    bid_added: float
    bid_cancelled: float
    ask_added: float
    ask_cancelled: float
    bid_pull_score: float
    ask_pull_score: float
    bid_replenishment: float
    ask_replenishment: float
    bid_liquidity: float
    ask_liquidity: float
    spoof_risk_bid: float
    spoof_risk_ask: float
    valid: bool


class OrderBookEngine:
    """Canonicalises L2 snapshots and extracts *observed* liquidity changes."""

    def __init__(self, near_levels: int = 5, depth_levels: int = 50,
                 wall_multiple: float = 4.0, spoof_window_seconds: float = 5.0):
        self.near_levels = near_levels
        self.depth_levels = depth_levels
        self.wall_multiple = wall_multiple
        self.spoof_window_seconds = spoof_window_seconds
        self._bids: Dict[float, float] = {}
        self._asks: Dict[float, float] = {}
        self._large_adds = deque(maxlen=200)  # (side, price, size, timestamp)
        self._last = self._empty(0.0, valid=False)

    @staticmethod
    def _parse_levels(levels: Iterable) -> Dict[float, float]:
        result: Dict[float, float] = {}
        for item in levels or []:
            try:
                if isinstance(item, dict):
                    price = float(item.get("price", item.get("limit_price")))
                    size = float(item.get("size", item.get("quantity", 0)))
                else:
                    price, size = float(item[0]), float(item[1])
                if isfinite(price) and isfinite(size) and price > 0 and size > 0:
                    result[price] = result.get(price, 0.0) + size
            except (TypeError, ValueError, IndexError, KeyError):
                continue
        return result

    def _empty(self, timestamp: float, valid: bool) -> BookFeatures:
        return BookFeatures(
            timestamp=timestamp, best_bid=None, best_ask=None, spread=None,
            obi_near=0.0, obi_weighted=0.0, bid_added=0.0,
            bid_cancelled=0.0, ask_added=0.0, ask_cancelled=0.0,
            bid_pull_score=0.0, ask_pull_score=0.0,
            bid_replenishment=0.0, ask_replenishment=0.0,
            bid_liquidity=0.0, ask_liquidity=0.0,
            spoof_risk_bid=0.0, spoof_risk_ask=0.0, valid=valid,
        )

    @staticmethod
    def _diff(old: Dict[float, float], new: Dict[float, float]) -> Tuple[float, float, Dict[float, float], Dict[float, float]]:
        added, removed, additions, removals = 0.0, 0.0, {}, {}
        for price in old.keys() | new.keys():
            delta = new.get(price, 0.0) - old.get(price, 0.0)
            if delta > 0:
                additions[price] = delta
                added += delta
            elif delta < 0:
                removals[price] = -delta
                removed += -delta
        return added, removed, additions, removals

    def _near_price_window(self, book: Dict[float, float], side: str, levels: int) -> Dict[float, float]:
        """Top `levels` price levels closest to the touch — bids sorted
        high-to-low (best bid first), asks sorted low-to-high (best ask
        first). Same ordering _weighted_obi already uses.

        Raw L2 snapshots from the exchange can carry 2,000+ distinct
        price levels stretching far from the touch (confirmed via
        console logs: 'Bids: 2202 Asks: 2151' on a live BTCUSD feed).
        Any metric summed over the FULL book rather than this near-
        price window gets dominated by whatever huge, mostly-static
        resting size happens to sit deep away from price on one side —
        which is exactly what was pinning bid_pull_score near 0 and
        ask_pull_score near 1 for two straight days of live data before
        this fix (see core.orderflow_features's confluence scoring,
        which reads these two fields asymmetrically as a result)."""

        if side == "bid":
            return dict(sorted(book.items(), key=lambda kv: kv[0], reverse=True)[:levels])
        return dict(sorted(book.items(), key=lambda kv: kv[0])[:levels])

    @staticmethod
    def _weighted_obi(bids: Dict[float, float], asks: Dict[float, float], levels: int) -> Tuple[float, float, float]:
        bid_rows = sorted(bids.items(), reverse=True)[:levels]
        ask_rows = sorted(asks.items())[:levels]
        bid_weighted = sum(size * (0.85 ** index) for index, (_, size) in enumerate(bid_rows))
        ask_weighted = sum(size * (0.85 ** index) for index, (_, size) in enumerate(ask_rows))
        total = bid_weighted + ask_weighted
        return ((bid_weighted - ask_weighted) / total if total else 0.0,
                sum(size for _, size in bid_rows), sum(size for _, size in ask_rows))

    def update(self, bids: Iterable, asks: Iterable, timestamp: float) -> BookFeatures:
        new_bids, new_asks = self._parse_levels(bids), self._parse_levels(asks)
        if not new_bids or not new_asks:
            self._last = self._empty(timestamp, valid=False)
            return self._last

        # Churn (added/cancelled) and the pull-score denominator are
        # measured over the SAME near-price window as bid_liquidity /
        # ask_liquidity / obi_weighted below (self.depth_levels) —
        # previously this diffed the entire raw book (self._bids /
        # self._asks, unbounded — 2,000+ levels on a live feed), which
        # let deep, mostly-static resting size swamp the ratio. See
        # _near_price_window's docstring for the full rationale.
        prev_bid_window = self._near_price_window(self._bids, "bid", self.depth_levels)
        prev_ask_window = self._near_price_window(self._asks, "ask", self.depth_levels)
        new_bid_window = self._near_price_window(new_bids, "bid", self.depth_levels)
        new_ask_window = self._near_price_window(new_asks, "ask", self.depth_levels)

        bid_added, bid_cancelled, bid_additions, _ = self._diff(prev_bid_window, new_bid_window)
        ask_added, ask_cancelled, ask_additions, _ = self._diff(prev_ask_window, new_ask_window)

        obi_near, near_bid, near_ask = self._weighted_obi(new_bids, new_asks, self.near_levels)
        obi_weighted, bid_liquidity, ask_liquidity = self._weighted_obi(new_bids, new_asks, self.depth_levels)

        old_bid_total = sum(prev_bid_window.values())
        old_ask_total = sum(prev_ask_window.values())
        bid_pull = min(1.0, bid_cancelled / max(old_bid_total, 1e-9))
        ask_pull = min(1.0, ask_cancelled / max(old_ask_total, 1e-9))

        # Replenishment means material displayed size was restored at a price
        # that was present in the prior snapshot's near-price window; execution
        # attribution still requires trade-flow confirmation in the coordinator.
        bid_replenish = sum(delta for price, delta in bid_additions.items() if price in prev_bid_window)
        ask_replenish = sum(delta for price, delta in ask_additions.items() if price in prev_ask_window)
        median_near = max((near_bid + near_ask) / max(self.near_levels * 2, 1), 1e-9)
        spoof_bid, spoof_ask = self._spoof_risk(new_bids, new_asks, bid_additions, ask_additions, median_near, timestamp)
        self._bids, self._asks = new_bids, new_asks
        best_bid, best_ask = max(new_bids), min(new_asks)
        self._last = BookFeatures(timestamp, best_bid, best_ask, max(best_ask - best_bid, 0.0),
                                  obi_near, obi_weighted, bid_added, bid_cancelled,
                                  ask_added, ask_cancelled, bid_pull, ask_pull,
                                  bid_replenish, ask_replenish, bid_liquidity,
                                  ask_liquidity, spoof_bid, spoof_ask, True)
        return self._last

    def _spoof_risk(self, bids, asks, bid_additions, ask_additions, typical_size, timestamp):
        while self._large_adds and timestamp - self._large_adds[0][3] > self.spoof_window_seconds:
            self._large_adds.popleft()
        for side, additions in (("bid", bid_additions), ("ask", ask_additions)):
            for price, size in additions.items():
                if size >= typical_size * self.wall_multiple:
                    self._large_adds.append((side, price, size, timestamp))
        bid_risk = ask_risk = 0.0
        for side, price, original, added_at in self._large_adds:
            current = (bids if side == "bid" else asks).get(price, 0.0)
            removed_fraction = max(0.0, 1.0 - current / original)
            if removed_fraction >= 0.8 and timestamp > added_at:
                if side == "bid":
                    bid_risk = max(bid_risk, removed_fraction)
                else:
                    ask_risk = max(ask_risk, removed_fraction)
        return bid_risk, ask_risk

    @property
    def latest(self) -> BookFeatures:
        return self._last
