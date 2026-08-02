import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

# Must happen before QApplication is constructed, and only if the
# optional PyQt6-WebEngine package is installed. This is what lets the
# TradingView chart tab (ui/tv_chart_view.py) use a QWebEngineView
# without Qt raising "AA_ShareOpenGLContexts must be set before a
# QCoreApplication instance is created". If WebEngine isn't installed,
# this is skipped — the rest of the app (including the always-working
# Footprint chart) runs exactly as before; only the TradingView tab
# shows a "package not installed" notice.
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView  # noqa: F401
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
except Exception:
    pass

from ui.dashboard import Dashboard
from core.ws_bridge import WebSocketBridge
from core.websocket_thread import WebSocketThread


def main():

    app = QApplication(sys.argv)

    window = Dashboard()
    window.show()

    # ---------------------------------------------------------
    # Backfill historical candles + start the live market data
    # feed in the background, routed to the GUI thread safely.
    # ---------------------------------------------------------

    bridge = WebSocketBridge(window)

    ws_thread = WebSocketThread(symbol="BTCUSD")
    ws_thread.market_event.connect(bridge.handle_event)
    ws_thread.history_loaded.connect(bridge.handle_history)
    ws_thread.ticker_loaded.connect(bridge.handle_ticker)
    ws_thread.connection_changed.connect(bridge.handle_connection_change)
    ws_thread.start()

    # keep references alive for the lifetime of the window
    window._ws_thread = ws_thread
    window._ws_bridge = bridge

    sys.exit(
        app.exec()
    )


if __name__ == "__main__":

    main()
