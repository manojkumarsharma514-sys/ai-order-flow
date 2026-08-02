from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import pyqtSignal


# label -> (Delta REST "resolution" string, seconds per candle)
TIMEFRAMES = [
    ("1m", "1m", 60),
    ("5m", "5m", 300),
    ("15m", "15m", 900),
    ("1H", "1h", 3600),
    ("4H", "4h", 14400),
    ("1D", "1d", 86400),
]


class TimeframeSelector(QWidget):
    """
    Chart timeframe switcher (1m / 5m / 15m / 1H / 4H / 1D). Purely a UI
    control — it just emits the chosen timeframe; the dashboard
    controller is responsible for rebuilding the candle series and
    re-seeding history for it.
    """

    timeframe_changed = pyqtSignal(str, int)  # (resolution, seconds)

    def __init__(self, default_label="5m"):
        super().__init__()

        self.setStyleSheet("""
        QWidget{
            background:#131722;
            border:1px solid #1E222D;
            border-radius:6px;
        }

        QLabel#tf_title{
            color:#888;
            font-size:11px;
            font-weight:bold;
        }

        QPushButton{
            background:transparent;
            color:#aaa;
            border:none;
            border-radius:4px;
            padding:4px 10px;
            font-size:12px;
            font-weight:bold;
        }

        QPushButton:hover{
            background:#1E222D;
            color:white;
        }

        QPushButton[active="true"]{
            background:#00FF88;
            color:#0B0E14;
        }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(4)

        title = QLabel("⏱ TIMEFRAME")
        title.setObjectName("tf_title")
        layout.addWidget(title)
        layout.addSpacing(8)

        self._buttons = {}

        for label, resolution, seconds in TIMEFRAMES:
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(
                lambda _checked, l=label, r=resolution, s=seconds: self._select(l, r, s)
            )
            layout.addWidget(btn)
            self._buttons[label] = btn

        layout.addStretch()

        self._active_label = None
        self._select(default_label, *self._lookup(default_label), emit=False)

    def _lookup(self, label):
        for l, resolution, seconds in TIMEFRAMES:
            if l == label:
                return resolution, seconds
        return TIMEFRAMES[1][1], TIMEFRAMES[1][2]  # fall back to 5m

    def _select(self, label, resolution, seconds, emit=True):

        if label == self._active_label:
            return

        self._active_label = label

        for l, btn in self._buttons.items():
            active = (l == label)
            btn.setChecked(active)
            btn.setProperty("active", "true" if active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if emit:
            self.timeframe_changed.emit(resolution, seconds)

    # ------------------------------------------------------------------
    # Public helpers used by AppStateHandler restore
    # ------------------------------------------------------------------

    @property
    def current_label(self):
        return self._active_label

    def set_timeframe_label(self, label, emit=True):
        """Programmatically select a timeframe button (used to restore
        the last-used timeframe on app launch)."""
        resolution, seconds = self._lookup(label)
        self._select(label, resolution, seconds, emit=emit)
