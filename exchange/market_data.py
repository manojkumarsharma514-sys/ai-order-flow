from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class MarketData:

    symbol: str = "BTCUSD"

    last_price: float = 0.0

    bid: float = 0.0

    ask: float = 0.0

    spread: float = 0.0

    volume: float = 0.0

    high: float = 0.0

    low: float = 0.0

    change: float = 0.0

    change_percent: float = 0.0

    timestamp: datetime = field(default_factory=datetime.now)

    bids: list = field(default_factory=list)

    asks: list = field(default_factory=list)

    trades: list = field(default_factory=list)

    connected: bool = False