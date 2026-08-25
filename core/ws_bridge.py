from PyQt6.QtCore import QObject, pyqtSlot

from core import event_bus


class WebSocketBridge(QObject):
    """
    Lives on the main GUI thread. The background WebSocket thread emits
    market events and history as Qt signals (thread-safe, queued) to
    this bridge instead of touching Qt widgets directly. These slots
    then update the event bus / chart, only ever on the GUI thread.

    RECONNECT RESYNC: DeltaWebSocketClient.connect() already retries
    the socket itself (5s backoff loop) after a drop, but nothing used
    to re-sync candle history once it came back — any time the feed
    was down (laptop sleep, wifi drop, VPN hiccup) was a silent gap in
    the chart, since candles only ever build from live ticks. Worse,
    strategy_candle_manager (the FIXED-timeframe feed that drives
    RegimeEngine's regime/ATR for the executor's trading gates) went
    stale for exactly as long as the outage, with no signal that it
    had. handle_connection_change below now tracks the True/False
    transition and, specifically on a reconnect AFTER a drop (never on
    the very first connect, which already gets a full backfill from
    WebSocketThread.run()), asks the controller to re-fetch REST OHLC
    history for both candle feeds — the same mechanism already used on
    startup and on every manual timeframe switch.
    """

    def __init__(self, dashboard):
        super().__init__()
        self.dashboard = dashboard

        # Connection-state tracking for reconnect resync (see class
        # docstring). `_has_connected_once` distinguishes "first ever
        # connect" (already backfilled by WebSocketThread.run(), no
        # resync needed) from a later reconnect. `_dropped` is only
        # set True while the feed is actually down, so a resync fires
        # exactly once per outage, right when it ends.
        self._has_connected_once = False
        self._dropped = False

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

        if connected:
            if self._dropped:
                # We were connected before, the feed went down for an
                # unknown amount of time (could be a few seconds, could
                # be hours if the machine slept), and we've just come
                # back. Anything that happened in between never arrived
                # as live ticks, so both candle_manager (chart) and
                # strategy_candle_manager (regime/ATR) have a real gap
                # right now. Re-fetch REST history to backfill it.
                print("🔄 WebSocket reconnected after a drop — resyncing candle history")
                try:
                    self.dashboard.controller.resync_after_reconnect()
                except Exception as e:
                    print("reconnect resync error:", e)
                self._dropped = False
            self._has_connected_once = True
        else:
            if self._has_connected_once:
                self._dropped = True
