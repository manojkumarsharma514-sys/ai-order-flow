from PyQt6.QtWebEngineWidgets import QWebEngineView


class TradingViewChart(QWebEngineView):

    def __init__(self):
        super().__init__()

        html = """
        <!DOCTYPE html>
        <html>
        <body style="margin:0;background:#131722;">
        <iframe
            src="https://s.tradingview.com/widgetembed/?symbol=BITSTAMP:BTCUSD&interval=15&theme=dark"
            style="width:100%;height:100vh;border:none;">
        </iframe>
        </body>
        </html>
        """

        self.setHtml(html)