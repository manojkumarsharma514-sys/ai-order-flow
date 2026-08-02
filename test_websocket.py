from PyQt6.QtCore import QCoreApplication
from exchange.websocket_client import WebSocketClient
import sys


def on_market_update(market):
    print(
        f"Price: {market.last_price:.2f} | "
        f"Bid: {market.bid:.2f} | "
        f"Ask: {market.ask:.2f} | "
        f"Volume: {market.volume:.2f}"
    )


app = QCoreApplication(sys.argv)

ws = WebSocketClient()
ws.market_updated.connect(on_market_update)
ws.start()

sys.exit(app.exec())