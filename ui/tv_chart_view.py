from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QStackedLayout, QSizePolicy
from PyQt6.QtCore import Qt
import os
import tempfile

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    from PyQt6.QtWebEngineCore import QWebEnginePage
    from PyQt6.QtCore import QUrl
    WEBENGINE_AVAILABLE = True
except Exception:
    WEBENGINE_AVAILABLE = False


# internal timeframe seconds -> TradingView "interval" code
_INTERVAL_MAP = {
    60: "1", 180: "3", 300: "5", 900: "15",
    3600: "60", 14400: "240", 86400: "D",
}

# TradingView's own "DELTA:" exchange-prefixed symbols aren't reliably
# resolvable on every TradingView plan/region, and a bad symbol here is
# exactly what produced the blank chart before, with zero error shown.
# BINANCE:BTCUSDT is virtually always valid, so it's the safe default.
# Change this if you have a TradingView account confirmed to resolve
# DELTA: symbols and want that instead.
DEFAULT_SYMBOL = "BINANCE:BTCUSDT"


def _tradingview_html(symbol, interval):
    return f"""
    <html>
    <head>
      <style>
        html, body {{ margin:0; padding:0; background:#0d0f14; height:100%; }}
        #tv_chart {{ height:100vh; }}
      </style>
    </head>
    <body>
      <div id="tv_chart"></div>
      <script src="https://s3.tradingview.com/tv.js"></script>
      <script>
        try {{
          new TradingView.widget({{
            "autosize": true,
            "symbol": "{symbol}",
            "interval": "{interval}",
            "timezone": "Etc/UTC",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "toolbar_bg": "#131722",
            "enable_publishing": false,
            "hide_top_toolbar": false,
            "hide_legend": false,
            "withdateranges": true,
            "allow_symbol_change": true,
            "studies": ["Volume@tv-basicstudies"],
            "save_image": false,
            "backgroundColor": "#0d0f14",
            "gridColor": "rgba(255, 255, 255, 0.06)",
            "container_id": "tv_chart"
          }});
          window.tv_ready = true;
        }} catch (e) {{
          document.body.innerHTML =
            '<div style="color:#ff5b5b; padding:20px; font-family:sans-serif;">' +
            'TradingView widget failed to initialize: ' + e + '</div>';
        }}
      </script>
    </body>
    </html>
    """


class DeltaLiveChart(QWidget):
    """
    Real TradingView Advanced Chart widget — all timeframes, indicators,
    drawing tools, candle types, exactly as on tradingview.com — shown
    as a second view alongside the native Footprint chart (which never
    depends on network/CDN and can't go blank).

    Unlike the first attempt at this, failures here are ALWAYS visible:
    if PyQt6-WebEngine isn't installed, if the page can't load (no
    internet, blocked CDN, etc.), or if it loads but the widget script
    itself errors, this shows a clear on-screen message instead of a
    quietly empty panel.
    """

    def __init__(self, symbol=DEFAULT_SYMBOL, interval_seconds=300):
        super().__init__()

        self._symbol = symbol
        self._interval_seconds = interval_seconds

        # Same stability fix as the native FootprintChart: this view's
        # size should only ever come from its container/splitter, never
        # from its own content (status text swapping in/out, etc.).
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # QStackedLayout so the status message can sit ON TOP of the
        # webview and be shown/hidden without recreating anything
        self._stack = QStackedLayout(self)
        self._stack.setStackingMode(QStackedLayout.StackingMode.StackAll)

        self.status = QLabel("")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status.setWordWrap(True)
        self.status.setStyleSheet(
            "color:#aaa; font-size:13px; background:#0d0f14; padding:40px;"
        )

        if not WEBENGINE_AVAILABLE:
            self.status.setText(
                "TradingView chart needs the optional PyQt6-WebEngine package.\n\n"
                "Install it with:\n"
                "pip install PyQt6-WebEngine\n\n"
                "then restart the app. The Footprint chart tab is unaffected."
            )
            self._stack.addWidget(self.status)
            self.view = None
            return

        self.view = QWebEngineView()
        self.view.setStyleSheet("background:#0d0f14;")
        self.view.loadFinished.connect(self._on_load_finished)

        # surfaces the widget's own JS console errors in your terminal,
        # instead of them disappearing silently inside the browser engine
        try:
            self.view.page().javaScriptConsoleMessage = self._on_js_console
        except Exception:
            pass

        self._stack.addWidget(self.view)
        self._stack.addWidget(self.status)

        self.status.setText("Loading TradingView chart...")
        self._stack.setCurrentWidget(self.status)

        self._load()

    def _on_js_console(self, level, message, line, source):
        print(f"[TradingView chart JS] {message} (line {line})")

    def _on_load_finished(self, ok):
        if ok:
            # give the widget script a moment to actually paint before
            # dropping the "loading" overlay
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1200, lambda: self._stack.setCurrentWidget(self.view))
        else:
            self.status.setText(
                "TradingView chart failed to load.\n\n"
                "This usually means no internet access, or a firewall/proxy "
                "blocking s3.tradingview.com. The Footprint chart tab does not "
                "depend on the network and is unaffected."
            )
            self._stack.setCurrentWidget(self.status)

    def _load(self):
        if self.view is None:
            return

        interval = _INTERVAL_MAP.get(self._interval_seconds, "5")
        html = _tradingview_html(self._symbol, interval)

        path = os.path.join(tempfile.gettempdir(), "ai_orderflow_delta_chart.html")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
            self.view.load(QUrl.fromLocalFile(path))
        except Exception as e:
            self.status.setText(f"TradingView chart load error: {e}")
            self._stack.setCurrentWidget(self.status)

    def set_timeframe(self, interval_seconds):
        """Keep this chart's timeframe in sync with the app's Timeframe
        selector (called by the dashboard controller)."""

        if interval_seconds == self._interval_seconds:
            return

        self._interval_seconds = interval_seconds

        if self.view is not None:
            self.status.setText("Loading TradingView chart...")
            self._stack.setCurrentWidget(self.status)
            self._load()