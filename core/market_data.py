from collections import deque


class MarketData:

    def __init__(self):

        # -----------------------------
        # CONNECTION
        # -----------------------------

        self.connected = False
        self.latency = 0

        # -----------------------------
        # MARKET
        # -----------------------------

        self.symbol = "BTCUSD"

        self.price = 0

        self.last_price = 0

        self.price_change = 0

        # -----------------------------
        # ORDERBOOK
        # -----------------------------

        self.bids = []

        self.asks = []

        self.bid_volume = 0

        self.ask_volume = 0

        self.dom_pressure = 0

        self.buy_wall = False

        self.sell_wall = False

        # -----------------------------
        # TRADES
        # -----------------------------

        self.recent_trades = deque(maxlen=300)

        self.buy_volume = 0

        self.sell_volume = 0

        self.delta = 0

        self.cvd = 0

        # -----------------------------
        # FOOTPRINT
        # -----------------------------

        self.footprint = {}

        self.stacked_buy = False

        self.stacked_sell = False

        # -----------------------------
        # VOLUME PROFILE
        # -----------------------------

        self.poc = 0

        self.vah = 0

        self.val = 0

        # -----------------------------
        # SMART MONEY
        # -----------------------------

        self.absorption = False

        self.iceberg = False

        self.spoofing = False

        self.liquidity_grab = False

        self.whale_buy = False

        self.whale_sell = False

        # -----------------------------
        # AI
        # -----------------------------

        self.buy_strength = 0

        self.sell_strength = 0

        self.confidence = 0

        self.trend = "WAIT"

        self.signal = "WAIT"

        self.market_regime = "UNKNOWN"

        # -----------------------------
        # TRADING
        # -----------------------------

        self.position = None

        self.entry = 0

        self.stoploss = 0

        self.target = 0

        self.pnl = 0

        self.balance = 0

        self.risk = 0


market = MarketData()