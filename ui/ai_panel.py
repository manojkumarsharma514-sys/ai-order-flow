from PyQt6.QtWidgets import QWidget
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QProgressBar


class AIPanel(QWidget):

    def __init__(self):
        super().__init__()

        # Minimum, not fixed: the dashboard gives this panel 25% of
        # the top-row stretch (see ui/dashboard.py) so its labels have
        # room to render without clipped text or scrollbars. A hard
        # setFixedWidth would have overridden that stretch and kept the
        # panel pinned to its old cramped size.
        self.setMinimumWidth(260)

        self.setStyleSheet("""
        QWidget{
            background:#131722;
            border-left:1px solid #1E222D;
        }

        QLabel{
            color:white;
            font-size:14px;
        }

        QProgressBar{
            border:1px solid #444;
            border-radius:5px;
            text-align:center;
            height:18px;
            background:#2b2b2b;
            color:white;
        }

        QProgressBar::chunk{
            background:#00C853;
        }
        """)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(14, 10, 14, 14)

        title = QLabel("🤖 AI ENGINE")

        title.setStyleSheet("""
        QLabel{
            font-size:15px;
            font-weight:bold;
            color:#00FF88;
            padding:10px;
        }
        """)

        layout.addWidget(title)

        # Buyer Strength / Seller Strength don't have their own bars
        # here — redundant now that they're no longer part of any
        # displayed breakdown either. The QProgressBar objects are
        # kept (unattached to any layout) purely so update_ai() below
        # doesn't need touching every call site that still passes
        # buyers/sellers values.
        self.buyers = QProgressBar()
        self.buyers.setRange(0, 100)
        self.sellers = QProgressBar()
        self.sellers.setRange(0, 100)

        # -------------------------

        self.trend = QLabel("Trend : WAIT")

        self.signal = QLabel("Signal : WAIT")

        self.delta = QLabel("Volume Delta : 0")

        self.liquidity = QLabel("Liquidity : None")

        layout.addWidget(self.trend)
        layout.addWidget(self.signal)
        layout.addWidget(self.delta)
        layout.addWidget(self.liquidity)

        # -------------------------
        # Extended indicators (VWAP / EMA trend / RSI / ATR)
        # -------------------------

        layout.addSpacing(10)

        self.vwap_label = QLabel("VWAP : --")
        self.ema_trend_label = QLabel("Trend (EMA 20/50) : --")
        self.rsi_label = QLabel("Momentum (RSI 14) : --")
        self.atr_label = QLabel("Volatility (ATR) : --")

        layout.addWidget(self.vwap_label)
        layout.addWidget(self.ema_trend_label)
        layout.addWidget(self.rsi_label)
        layout.addWidget(self.atr_label)

        # -------------------------
        # AI Confidence — the single authoritative number (same value
        # driving the AI SIGNAL gauge and the auto-trade executor).
        #
        # The "Signal Factor Breakdown" that used to live here has
        # been removed: it scored a decorative, disconnected set of
        # inputs (raw Delta / Buyer-Seller % / VWAP / RSI) that had
        # little to no relationship to what actually computes
        # market.confidence (core/orderflow_features.py's order-book +
        # multi-horizon-delta + absorption/confirmation confluence
        # score). That let the panel show several "bullish" bars next
        # to a low WAIT confidence with no visible explanation, since
        # half those bars weren't part of the real decision at all.
        # Rather than keep two separate, hard-to-keep-in-sync scoring
        # systems, this panel now just shows the one real number.
        # -------------------------

        layout.addSpacing(10)

        self.confidence_label = QLabel("AI Confidence : --")
        self.confidence_label.setStyleSheet("""
        QLabel{
            font-size:13px;
            font-weight:bold;
            color:#ffffff;
            padding-top:6px;
        }
        """)
        layout.addWidget(self.confidence_label)

        layout.addStretch()

    # -----------------------------

    def update_ai(
        self,
        confidence,
        buyers,
        sellers,
        trend,
        signal,
        delta,
        liquidity
    ):

        self.buyers.setValue(buyers)

        self.sellers.setValue(sellers)

        self.trend.setText(
            f"Trend : {trend}"
        )

        self.signal.setText(
            f"Signal : {signal}"
        )

        self.delta.setText(
            f"Volume Delta : {delta}"
        )

        self.liquidity.setText(
            f"Liquidity : {liquidity}"
        )

        side = "BUY" if "BUY" in str(signal).upper() else (
            "SELL" if "SELL" in str(signal).upper() else "WAIT"
        )
        color = "#00FF88" if side == "BUY" else ("#ff5b5b" if side == "SELL" else "#c7cbd6")
        self.confidence_label.setText(f"AI Confidence : {confidence:.0f}% {side}")
        self.confidence_label.setStyleSheet(f"""
        QLabel{{
            font-size:13px;
            font-weight:bold;
            color:{color};
            padding-top:6px;
        }}
        """)

    def update_indicators(self, vwap_status, ema_trend, rsi, atr_level):

        self.vwap_label.setText(f"VWAP : {vwap_status}")

        self.ema_trend_label.setText(f"Trend (EMA 20/50) : {ema_trend}")

        rsi_text = f"{rsi:.1f}" if rsi is not None else "--"
        self.rsi_label.setText(f"Momentum (RSI 14) : {rsi_text}")

        self.atr_label.setText(f"Volatility (ATR) : {atr_level}")
