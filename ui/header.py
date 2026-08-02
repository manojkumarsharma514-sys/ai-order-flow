from PyQt6.QtWidgets import QWidget
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QHBoxLayout
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtCore import Qt
from PyQt6.QtCore import QTimer
from datetime import datetime, timezone

from ui.gauge import CircularGauge


def _stat_block(title_text):
    """A small 'label on top, value below' block, like Pic 2's header stats."""

    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)

    title = QLabel(title_text)
    title.setStyleSheet("color:#888; font-size:11px;")

    value = QLabel("--")
    value.setStyleSheet("color:white; font-size:14px; font-weight:600;")

    layout.addWidget(title)
    layout.addWidget(value)

    return box, value


class Header(QWidget):

    def __init__(self):
        super().__init__()

        self.setFixedHeight(96)

        self.setStyleSheet("""
        QWidget{
            background:#1b1b1b;
            border-bottom:1px solid #1E222D;
        }

        QLabel{
            color:white;
            font-size:14px;
        }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)

        self.title = QLabel("<b>AI OrderFlow Pro</b>")

        self.symbol = QLabel("BTCUSD")

        self.price = QLabel("$0.00")
        self.price.setStyleSheet("color:white; font-size:20px; font-weight:700;")

        self.connection = QLabel("🔴 Disconnected")

        self.balance = QLabel("Balance : $0.00")

        self.mode = QLabel("Paper Trading")
        self.mode.setObjectName("account_mode_badge")

        self.clock = QLabel()

        layout.addWidget(self.title)

        layout.addSpacing(20)
        layout.addWidget(self.symbol)

        layout.addSpacing(16)
        layout.addWidget(self.price)

        layout.addSpacing(24)

        high_box, self.high_value = _stat_block("24H High")
        layout.addWidget(high_box)

        layout.addSpacing(16)

        low_box, self.low_value = _stat_block("24H Low")
        layout.addWidget(low_box)

        layout.addSpacing(16)

        vol_box, self.volume_value = _stat_block("24H Volume")
        layout.addWidget(vol_box)

        layout.addSpacing(16)

        funding_box, self.funding_value = _stat_block("Funding / Countdown")
        layout.addWidget(funding_box)

        layout.addStretch()

        self.signal_gauge = CircularGauge("AI SIGNAL")
        layout.addWidget(self.signal_gauge, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addSpacing(8)

        self.risk_gauge = CircularGauge("RISK")
        layout.addWidget(self.risk_gauge, 0, Qt.AlignmentFlag.AlignVCenter)

        layout.addSpacing(16)

        layout.addWidget(self.connection)
        layout.addSpacing(20)
        layout.addWidget(self.balance)
        layout.addSpacing(20)
        layout.addWidget(self.mode)
        layout.addSpacing(20)
        layout.addWidget(self.clock)

        timer = QTimer(self)
        timer.timeout.connect(self.update_clock)
        timer.start(1000)

        # cache of last known funding rate so the countdown can keep
        # ticking every second between 10s ticker polls
        self._funding_rate = None

        self.update_clock()

    def update_clock(self):

        self.clock.setText(
            datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        )

        self._update_funding_countdown()

    def update_price(self, price):

        try:
            self.price.setText(f"${float(price):,.1f}")
        except (TypeError, ValueError):
            self.price.setText(f"${price}")

    def update_balance(self, equity):

        try:
            self.balance.setText(f"Balance : ${float(equity):,.2f}")
        except (TypeError, ValueError):
            pass

    def set_account_mode(self, mode):
        """mode: "paper" | "demo" | "live" — read dynamically from
        DashboardController.account_type (mirrors app_state's
        "trading_mode" / exchange_config). LIVE gets a highlighted pill
        badge so it's unmistakable that real orders are being routed."""

        mode = (mode or "paper").lower()

        if mode == "live":
            self.mode.setText("  LIVE Trading  ")
            self.mode.setStyleSheet(
                "background:#F23645; color:#FFFFFF; font-weight:bold; "
                "font-size:13px; border-radius:4px; padding:3px 8px;"
            )
        elif mode == "demo":
            self.mode.setText("Demo Trading")
            self.mode.setStyleSheet("color:#FFC107; font-weight:600; font-size:14px;")
        else:
            self.mode.setText("Paper Trading")
            self.mode.setStyleSheet("color:white; font-size:14px;")

    def update_connection(self, connected):

        if connected:
            self.connection.setText("🟢 Connected")
        else:
            self.connection.setText("🔴 Disconnected")

    def update_gauges(self, confidence, direction_label, risk_pct, risk_label):
        """
        confidence: 0-100, from the orderflow engine's real confidence score
        direction_label: e.g. 'BULLISH' / 'BEARISH' / 'NEUTRAL'
        risk_pct: 0-100, derived from real open-position exposure vs balance
        risk_label: 'LOW' / 'MEDIUM' / 'HIGH'
        """

        signal_color = "#2ecc71" if direction_label == "BULLISH" else (
            "#e74c3c" if direction_label == "BEARISH" else "#999"
        )
        self.signal_gauge.set_value(confidence, direction_label, signal_color)

        risk_color = {"LOW": "#2ecc71", "MEDIUM": "#e67e22", "HIGH": "#e74c3c"}.get(risk_label, "#999")
        self.risk_gauge.set_value(risk_pct, risk_label, risk_color)

    def update_stats(self, data):
        """
        data: the REST ticker payload from exchange.delta_api.fetch_ticker.
        Field names follow Delta's documented ticker response — if any
        show as '--' on your account, check the printed payload and
        I'll map the correct field name.
        """

        try:
            high = data.get("high")
            if high is not None:
                self.high_value.setText(f"{float(high):,.1f}")

            low = data.get("low")
            if low is not None:
                self.low_value.setText(f"{float(low):,.1f}")

            volume = data.get("volume")
            if volume is not None:
                self.volume_value.setText(f"{float(volume):,.2f}")

            funding_rate = data.get("funding_rate")
            if funding_rate is not None:
                self._funding_rate = float(funding_rate)

        except Exception as e:
            print("header stats parse error:", e)

    def _update_funding_countdown(self):
        """
        Delta perpetuals fund on a fixed schedule (assumed here to be
        every 8 hours, at 00:00/08:00/16:00 UTC — the common convention).
        This countdown is computed client-side rather than trusting an
        exact 'next funding time' field, since that field name wasn't
        verified against a live account. If your product funds on a
        different schedule, tell me and I'll adjust the interval.
        """

        now = datetime.now(timezone.utc)
        hours_into_cycle = now.hour % 8
        seconds_left = (
            (7 - hours_into_cycle) * 3600
            + (59 - now.minute) * 60
            + (60 - now.second)
        )

        hh = seconds_left // 3600
        mm = (seconds_left % 3600) // 60
        ss = seconds_left % 60

        rate_text = (
            f"{self._funding_rate * 100:.4f}%"
            if self._funding_rate is not None
            else "--"
        )

        self.funding_value.setText(f"{rate_text} / {hh:02d}:{mm:02d}:{ss:02d}")