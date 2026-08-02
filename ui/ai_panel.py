from PyQt6.QtWidgets import QWidget
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QProgressBar
from PyQt6.QtWidgets import QFrame


class AIPanel(QWidget):

    def __init__(self):
        super().__init__()

        # Minimum, not fixed: the dashboard now gives this panel 25% of
        # the top-row stretch (see ui/dashboard.py) so all AI Engine
        # parameters — including the Signal Factor Breakdown — have
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

        # Buyer Strength / Seller Strength used to have their own bars
        # here, directly under the title — now redundant, since the
        # Signal Factor Breakdown section below already reports the
        # same numbers as its "Buyer vs. Seller Strength" factor row.
        # The QProgressBar objects are kept (unattached to any layout)
        # purely so update_ai() below doesn't need touching every call
        # site that still passes buyers/sellers values.
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
        # Signal Factor Breakdown (spec section 5): shows *why* the AI
        # took/suggested a trade — each contributing factor, its fixed
        # weight, and how bullish/bearish that factor currently reads.
        # -------------------------

        layout.addSpacing(14)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("background:#232936; max-height:1px; border:none;")
        layout.addWidget(divider)

        breakdown_title = QLabel("📊 Signal Factor Breakdown")
        breakdown_title.setStyleSheet("""
        QLabel{
            font-size:13px;
            font-weight:bold;
            color:#00FF88;
            padding-top:8px;
        }
        """)
        layout.addWidget(breakdown_title)

        self.factor_container = QVBoxLayout()
        self.factor_container.setSpacing(10)
        layout.addLayout(self.factor_container)
        self.factor_rows = []  # populated lazily by update_factor_breakdown

        self.final_confidence_label = QLabel("AI Confidence : --")
        self.final_confidence_label.setStyleSheet("""
        QLabel{
            font-size:13px;
            font-weight:bold;
            color:#ffffff;
            padding-top:6px;
        }
        """)
        layout.addWidget(self.final_confidence_label)

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

        # `confidence` stays a parameter (callers already pass it) but
        # is no longer rendered here — the single "AI Confidence : NN%
        # BUY/SELL/WAIT" figure now lives only in the Signal Factor
        # Breakdown footer (update_factor_breakdown), so there's one
        # confidence number on screen instead of two.

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

    def update_indicators(self, vwap_status, ema_trend, rsi, atr_level):

        self.vwap_label.setText(f"VWAP : {vwap_status}")

        self.ema_trend_label.setText(f"Trend (EMA 20/50) : {ema_trend}")

        rsi_text = f"{rsi:.1f}" if rsi is not None else "--"
        self.rsi_label.setText(f"Momentum (RSI 14) : {rsi_text}")

        self.atr_label.setText(f"Volatility (ATR) : {atr_level}")

    def update_factor_breakdown(self, breakdown: dict):
        """breakdown: the dict returned by strategy.ai_engine.compute_factor_breakdown —
        {"factors": [{"name","weight","score","detail"}, ...], "weighted_confidence", "side"}."""

        factors = breakdown.get("factors", [])

        # Build the row widgets once; every call after that just
        # updates values in place instead of rebuilding the layout.
        if not self.factor_rows:
            for f in factors:
                row = QVBoxLayout()
                row.setSpacing(3)

                header = QHBoxLayout()
                name_label = QLabel(f["name"])
                name_label.setStyleSheet("QLabel{font-size:11px; color:#c7cbd6; font-weight:600;}")
                weight_label = QLabel(f"Weight {f['weight']}%")
                weight_label.setStyleSheet("QLabel{font-size:11px; color:#7b8191; font-weight:bold;}")
                header.addWidget(name_label)
                header.addStretch()
                header.addWidget(weight_label)
                row.addLayout(header)

                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setTextVisible(False)
                bar.setFixedHeight(8)
                row.addWidget(bar)

                detail_label = QLabel("")
                detail_label.setStyleSheet("QLabel{font-size:10px; color:#8b92a5;}")
                row.addWidget(detail_label)

                self.factor_container.addLayout(row)
                self.factor_rows.append((weight_label, bar, detail_label))

        for (weight_label, bar, detail_label), f in zip(self.factor_rows, factors):
            score = max(0, min(100, f.get("score", 0)))
            bullish = score >= 50

            bar.setValue(int(round(score)))
            bar.setStyleSheet(f"""
            QProgressBar{{
                border:1px solid #444;
                border-radius:4px;
                background:#2b2b2b;
            }}
            QProgressBar::chunk{{
                background:{"#00C853" if bullish else "#e74c3c"};
                border-radius:4px;
            }}
            """)
            weight_label.setText(f"Weight {f['weight']}%")
            detail_label.setText(
                f"Score: {f.get('detail', '--')} ({'Bullish' if bullish else 'Bearish'})"
            )

        conf = breakdown.get("weighted_confidence", 0)
        side = breakdown.get("side", "WAIT")
        color = "#00FF88" if side == "BUY" else "#ff5b5b"
        self.final_confidence_label.setText(f"AI Confidence : {conf:.0f}% {side}")
        self.final_confidence_label.setStyleSheet(f"""
        QLabel{{
            font-size:13px;
            font-weight:bold;
            color:{color};
            padding-top:6px;
        }}
        """)