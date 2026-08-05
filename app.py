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

from core.runtime_paths import ensure_user_data_dir
from core.crash_handler import install as install_crash_handler

from ui.dashboard import Dashboard
from core.ws_bridge import WebSocketBridge
from core.websocket_thread import WebSocketThread


def main():

    # Create/seed the writable per-user config+data+logs folder BEFORE
    # anything else touches disk (ConfigManager, AppStateHandler,
    # OrdersManager, JournalManager, AnalyticsEngine all read/write
    # under this the moment the Dashboard/Controller construct).
    ensure_user_data_dir()

    app = QApplication(sys.argv)

    # Installed as early as possible so literally nothing that follows
    # can crash to a bare terminal traceback (or, worse, a silent exit)
    # under a --windowed build with no console attached.
    install_crash_handler()

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
