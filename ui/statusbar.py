from pathlib import Path

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QPixmap

DELTA_LOGO_PATH = Path("assets") / "images" / "delta_logo.png"


class StatusBar(QWidget):
    """
    Footer status bar. Every value here reflects real state:
    - Connection: actual WebSocket connect/reconnect/disconnect events
    - Latency: time since the last market message actually arrived
      (a genuine feed-freshness measurement — not a fabricated number)
    - API Status: derived from whether the feed is currently fresh
    - System: RUNNING / PAUSED, toggled by the Stop Bot button, which
      pauses new paper trades — it does not kill the data feed
    """

    stop_clicked = pyqtSignal()

    def __init__(self):
        super().__init__()

        self.setFixedHeight(34)

        self.setStyleSheet("""
        QWidget{
            background:#131722;
            border-top:1px solid #1E222D;
        }

        QLabel{
            color:#999;
            font-size:12px;
        }

        QPushButton{
            background:#c0392b;
            color:white;
            border:none;
            border-radius:4px;
            padding:4px 14px;
            font-weight:bold;
            font-size:12px;
        }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 0, 14, 0)

        self.connection_label = QLabel("🔴 Disconnected")
        layout.addWidget(self.connection_label)

        layout.addSpacing(20)

        self.logo_label = QLabel()
        self._load_logo()
        layout.addWidget(self.logo_label)
        layout.addSpacing(6)

        self.exchange_label = QLabel("Delta Exchange (India) — BTCUSD")
        layout.addWidget(self.exchange_label)

        layout.addStretch()

        self.latency_label = QLabel("Latency: -- ms")
        layout.addWidget(self.latency_label)

        layout.addSpacing(20)

        self.api_label = QLabel("API STATUS: --")
        layout.addWidget(self.api_label)

        layout.addSpacing(20)

        self.system_label = QLabel("SYSTEM: RUNNING")
        layout.addWidget(self.system_label)

        layout.addSpacing(20)

        self.stop_btn = QPushButton("Stop Bot")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        layout.addWidget(self.stop_btn)

        self._paused = False

    def _load_logo(self):
        """Loads assets/images/delta_logo.png at a fixed 20px-tall size
        next to the connection status. Falls back to a plain 'Δ' text
        label if the asset is missing, so a packaging mistake can't
        crash the status bar."""

        if DELTA_LOGO_PATH.exists():
            pixmap = QPixmap(str(DELTA_LOGO_PATH))
            if not pixmap.isNull():
                scaled = pixmap.scaledToHeight(20, Qt.TransformationMode.SmoothTransformation)
                self.logo_label.setPixmap(scaled)
                return

        self.logo_label.setText("Δ")
        self.logo_label.setStyleSheet("color:#00FF88; font-weight:bold; font-size:14px;")

    def set_connection(self, connected):

        if connected:
            self.connection_label.setText("🟢 Connected")
        else:
            self.connection_label.setText("🔴 Disconnected")

    def set_symbol(self, symbol: str):
        """Keeps the '[Delta Logo] Delta Exchange (India) — SYMBOL'
        label current if the traded symbol ever changes."""
        self.exchange_label.setText(f"Delta Exchange (India) — {symbol}")

    def set_latency(self, ms):

        if ms is None:
            self.latency_label.setText("Latency: -- ms")
            self.api_label.setText("API STATUS: --")
            return

        self.latency_label.setText(f"Latency: {ms:.0f} ms")

        # "fresh" if we've heard from the feed in the last 5 seconds
        if ms < 5000:
            self.api_label.setText("API STATUS: OK")
            self.api_label.setStyleSheet("color:#2ecc71;")
        else:
            self.api_label.setText("API STATUS: STALE")
            self.api_label.setStyleSheet("color:#e67e22;")

    def set_paused(self, paused):

        self._paused = paused

        if paused:
            self.system_label.setText("SYSTEM: PAUSED")
            self.system_label.setStyleSheet("color:#e67e22;")
            self.stop_btn.setText("Resume Bot")
            self.stop_btn.setStyleSheet(
                "background:#1b8a4a; color:white; border:none; border-radius:4px; padding:4px 14px; font-weight:bold; font-size:12px;"
            )
        else:
            self.system_label.setText("SYSTEM: RUNNING")
            self.system_label.setStyleSheet("color:#2ecc71;")
            self.stop_btn.setText("Stop Bot")
            self.stop_btn.setStyleSheet(
                "background:#c0392b; color:white; border:none; border-radius:4px; padding:4px 14px; font-weight:bold; font-size:12px;"
            )
