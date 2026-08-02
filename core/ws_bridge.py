from PyQt6.QtCore import QObject, pyqtSlot

from core import event_bus


class WebSocketBridge(QObject):
    """
    Lives on the main GUI thread. The background WebSocket thread emits
    market events and history as Qt signals (thread-safe, queued) to
    this bridge instead of touching Qt widgets directly. These slots
    then update the event bus / chart, only ever on the GUI thread.
    """

    def __init__(self, dashboard):
        super().__init__()
        self.dashboard = dashboard

    @pyqtSlot(dict)
    def handle_event(self, data):
        event_bus.market_update(data)

    @pyqtSlot(list)
    def handle_history(self, rows):
        try:
            manager = self.dashboard.controller.candle_manager
            manager.seed_history(rows)
            self.dashboard.chart.set_candles(manager.get_candles())
        except Exception as e:
            print("history backfill error:", e)

    @pyqtSlot(dict)
    def handle_ticker(self, data):
        try:
            self.dashboard.header.update_stats(data)
        except Exception as e:
            print("ticker update error:", e)

    @pyqtSlot(bool)
    def handle_connection_change(self, connected):
        try:
            self.dashboard.header.update_connection(connected)
            self.dashboard.statusbar.set_connection(connected)
        except Exception as e:
            print("connection status update error:", e)
