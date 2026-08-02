import time
from collections import OrderedDict


def calculate_dynamic_tick_size(timeframe_seconds: int) -> float:
    """Dynamically determine row step size based on timeframe to keep the price profile readable.
    
    Prevents higher timeframes from blowing up into thousands of empty price levels.
    """
    if timeframe_seconds <= 60:  # 1m
        return 1.0
    elif timeframe_seconds <= 300:  # 5m
        return 2.5
    elif timeframe_seconds <= 900:  # 15m
        return 5.0
    elif timeframe_seconds <= 3600:  # 1h
        return 20.0
    elif timeframe_seconds <= 14400:  # 4h
        return 50.0
    else:  # 1d or higher
        return 100.0


def round_price(price, tick_size):
    if not tick_size:
        return price
    return round(round(price / tick_size) * tick_size, 8)


class Candle:

    def __init__(self, start_time, timeframe, tick_size=1.0):

        self.start_time = start_time
        self.timeframe = timeframe
        self.end_time = start_time + timeframe
        self.tick_size = tick_size

        self.open = None
        self.high = None
        self.low = None
        self.close = None

        self.volume = 0.0

        self.buy_volume = 0.0
        self.sell_volume = 0.0

        self.delta = 0.0

        self.trade_count = 0
        self.max_trade = 0.0

        self.trades = []

        # price_level -> {"buy": float, "sell": float}
        self.footprint = OrderedDict()

    def update(self, price, size, side):

        if self.open is None:
            self.open = price
            self.high = price
            self.low = price

        self.close = price

        self.high = max(self.high, price)
        self.low = min(self.low, price)

        self.volume += size

        self.trade_count += 1

        self.max_trade = max(self.max_trade, size)

        self.trades.append((price, size, side))

        level = round_price(price, self.tick_size)
        row = self.footprint.setdefault(level, {"buy": 0.0, "sell": 0.0})

        if side.upper() == "BUY":
            self.buy_volume += size
            self.delta += size
            row["buy"] += size
        else:
            self.sell_volume += size
            self.delta -= size
            row["sell"] += size

    def calculate_order_flow_analytics(self, imbalance_ratio=3.0):
        """Calculates Point of Control (POC) and diagonal buy/sell order flow imbalances."""
        if not self.footprint:
            return {
                "poc_price": None,
                "buy_imbalances": set(),
                "sell_imbalances": set(),
            }

        sorted_prices = sorted(self.footprint.keys(), reverse=True)

        # 1. Point of Control (POC)
        poc_price = max(
            self.footprint.keys(),
            key=lambda p: self.footprint[p]["buy"] + self.footprint[p]["sell"],
        )

        # 2. Diagonal Imbalance Detection (Ask vs Bid one tick lower / Bid vs Ask one tick higher)
        buy_imbalances = set()
        sell_imbalances = set()

        for p in sorted_prices:
            lower_p = round_price(p - self.tick_size, self.tick_size)
            higher_p = round_price(p + self.tick_size, self.tick_size)

            # Diagonal Buy Imbalance: Ask[P] vs Bid[P - tick]
            if lower_p in self.footprint:
                bid_below = self.footprint[lower_p]["sell"]
                ask_here = self.footprint[p]["buy"]
                if bid_below > 0 and (ask_here / bid_below) >= imbalance_ratio:
                    buy_imbalances.add(p)

            # Diagonal Sell Imbalance: Bid[P] vs Ask[P + tick]
            if higher_p in self.footprint:
                ask_above = self.footprint[higher_p]["buy"]
                bid_here = self.footprint[p]["sell"]
                if ask_above > 0 and (bid_here / ask_above) >= imbalance_ratio:
                    sell_imbalances.add(p)

        return {
            "poc_price": poc_price,
            "buy_imbalances": buy_imbalances,
            "sell_imbalances": sell_imbalances,
        }


def _synthesize_footprint(c, tick_size):
    """Approximate a per-price-level footprint for a REST-backfilled OHLC candle."""
    if c.volume <= 0 or c.high is None or c.low is None or c.high <= c.low:
        return

    tick = tick_size or 1.0
    lo = round_price(c.low, tick)
    hi = round_price(c.high, tick)

    levels = []
    lvl = lo
    while lvl <= hi + 1e-9:
        levels.append(round(lvl, 8))
        lvl += tick

    if not levels:
        levels = [lo]

    span = max(hi - lo, tick)
    weights = [max(1.0 - abs(lvl - c.close) / span, 0.05) for lvl in levels]
    total_w = sum(weights)

    bullish = c.close >= c.open
    buy_share = 0.58 if bullish else 0.42

    for lvl, w in zip(levels, weights):
        vol = c.volume * (w / total_w)
        row = c.footprint.setdefault(lvl, {"buy": 0.0, "sell": 0.0})
        row["buy"] += vol * buy_share
        row["sell"] += vol * (1.0 - buy_share)

    c.buy_volume = c.volume * buy_share
    c.sell_volume = c.volume * (1.0 - buy_share)
    c.delta = c.buy_volume - c.sell_volume


class CandleManager:
    """Builds a rolling series of footprint candles for a single timeframe directly from a live trade stream."""

    def __init__(self, timeframe_seconds=300, tick_size=None, max_candles=150):

        self.timeframe = timeframe_seconds
        self.tick_size = (
            tick_size
            if tick_size is not None
            else calculate_dynamic_tick_size(timeframe_seconds)
        )
        self.max_candles = max_candles
        self.candles = []  # oldest -> newest

    def _bucket_start(self, ts):
        return int(ts // self.timeframe) * self.timeframe

    def on_trade(self, price, size, side, ts=None):

        if price is None or size is None:
            return

        ts = ts if ts is not None else time.time()
        bucket = self._bucket_start(ts)

        if not self.candles or self.candles[-1].start_time != bucket:
            self.candles.append(Candle(bucket, self.timeframe, self.tick_size))
            if len(self.candles) > self.max_candles:
                self.candles.pop(0)

        self.candles[-1].update(float(price), float(size), side)

    def set_timeframe(self, timeframe_seconds, tick_size=None):
        """Switch timeframe, update dynamic tick size, and reset series."""
        self.timeframe = timeframe_seconds
        self.tick_size = (
            tick_size
            if tick_size is not None
            else calculate_dynamic_tick_size(timeframe_seconds)
        )
        self.candles = []

    def seed_history(self, rows):
        """Seeds historical candles and synthesizes order flow profiles."""
        candles = []

        for row in rows:
            try:
                start_time = int(row.get("time"))
                c = Candle(start_time, self.timeframe, self.tick_size)
                c.open = float(row["open"])
                c.high = float(row["high"])
                c.low = float(row["low"])
                c.close = float(row["close"])
                c.volume = float(row.get("volume", 0))
                _synthesize_footprint(c, self.tick_size)
                candles.append(c)
            except Exception:
                continue

        candles.sort(key=lambda c: c.start_time)

        if candles:
            self.candles = candles[-self.max_candles :]

    def get_candles(self):
        return self.candles


def aggregate_volume_profile(candles):
    """Sums per-level buy/sell footprint volume across a list of candles."""
    profile = {}

    for c in candles:
        for level, row in c.footprint.items():
            agg = profile.setdefault(level, {"buy": 0.0, "sell": 0.0})
            agg["buy"] += row["buy"]
            agg["sell"] += row["sell"]

    return profile