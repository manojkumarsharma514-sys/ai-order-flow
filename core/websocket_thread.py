import asyncio

from PyQt6.QtCore import QThread, pyqtSignal

from exchange.websocket_client import DeltaWebSocketClient
from exchange.delta_api import (
    fetch_historical_candles, fetch_ticker, fetch_contract_size,
    set_contract_size, get_contract_size,
)


class HistoryFetchThread(QThread):
    """
    One-shot background fetch of historical OHLC candles for a given
    resolution — used when the user switches chart timeframe, so the
    REST call (network I/O) never runs on the GUI thread. Does not
    touch the live WebSocket feed at all; it only re-seeds the chart's
    backfill for the newly selected timeframe.
    """

    history_loaded = pyqtSignal(list)

    def __init__(self, symbol="BTCUSD", resolution="5m", count=150):
        super().__init__()
        self.symbol = symbol
        self.resolution = resolution
        self.count = count

    def run(self):
        try:
            rows = fetch_historical_candles(
                symbol=self.symbol, resolution=self.resolution, count=self.count
            )
            self.history_loaded.emit(rows or [])
        except Exception as e:
            print("Timeframe history fetch error:", e)
            self.history_loaded.emit([])


class WebSocketThread(QThread):
    """
    Runs the Delta Exchange WebSocket client on its own asyncio event
    loop inside a background QThread, so it never blocks the Qt GUI
    event loop. Emits every market event as a Qt signal rather than
    calling into the event bus directly, since that bus ends up
    touching Qt widgets — which is only safe from the GUI thread.

    Also polls the REST ticker endpoint every 10s (for 24h high/low/
    volume/funding) alongside the live trade/orderbook socket.
    """

    market_event = pyqtSignal(dict)
    history_loaded = pyqtSignal(list)
    ticker_loaded = pyqtSignal(dict)
    connection_changed = pyqtSignal(bool)

    def __init__(self, symbol="BTCUSD"):
        super().__init__()
        self.symbol = symbol
        self.client = None

    async def _poll_ticker(self):
        while True:
            try:
                data = await asyncio.to_thread(fetch_ticker, self.symbol)
                if data:
                    self.ticker_loaded.emit(data)
            except Exception as e:
                print("Ticker poll error:", e)

            await asyncio.sleep(10)

    def run(self):

        # Fetch the REAL contract size from Delta's own product spec
        # FIRST -- before the initial candle history backfill below AND
        # before the WebSocket client processes a single trade. This
        # must happen before fetch_historical_candles() so even the
        # very first chart render on app launch uses correctly-scaled
        # volume, not just everything from this point forward. A
        # failed/slow fetch just means the safe 0.001 fallback (already
        # set as exchange.delta_api's and DeltaWebSocketClient's
        # default) is used until the next app restart -- never blocks
        # or crashes startup.
        try:
            contract_size = fetch_contract_size(self.symbol)
            if contract_size:
                set_contract_size(contract_size)
                print(f"✅ Contract size for {self.symbol}: {contract_size} BTC/contract (from Delta API)")
            else:
                print(f"⚠️ Using fallback contract size for {self.symbol} "
                      f"(live fetch returned nothing)")
        except Exception as e:
            print("Contract size fetch error:", e, "— using fallback contract size")

        try:
            rows = fetch_historical_candles(symbol=self.symbol, resolution="5m", count=150)
            if rows:
                self.history_loaded.emit(rows)
        except Exception as e:
            print("History fetch error:", e)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        self.client = DeltaWebSocketClient()
        self.client.symbol = self.symbol
        self.client.on_event = self.market_event.emit
        self.client.on_connection_change = self.connection_changed.emit

        # Keep the live-feed client's own conversion factor in sync
        # with whatever was resolved above (live-fetched value, or the
        # shared fallback if that fetch failed).
        self.client.contract_size_btc = get_contract_size()

        try:
            loop.run_until_complete(
                asyncio.gather(
                    self.client.connect(),
                    self._poll_ticker(),
                )
            )
        except Exception as e:
            print("WebSocket thread error:", e)
