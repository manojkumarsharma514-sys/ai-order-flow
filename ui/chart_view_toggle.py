from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton
from PyQt6.QtCore import pyqtSignal


class ChartViewToggle(QWidget):
    """Switches the chart area's QStackedWidget between the native
    Footprint chart (index 0, always works, no network needed) and the
    real TradingView widget (index 1, needs internet/CDN access).
    Neither chart is created, destroyed, or altered by this — both stay
    alive underneath the whole time, so switching back is instant."""

    view_changed = pyqtSignal(int)  # stacked-widget page index

    def __init__(self):
        super().__init__()

        self.setStyleSheet("""
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
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.footprint_btn = QPushButton("📊 Footprint")
        self.live_btn = QPushButton("📈 TradingView")

        for btn in (self.footprint_btn, self.live_btn):
            btn.setCheckable(True)
            layout.addWidget(btn)

        self.footprint_btn.clicked.connect(lambda: self._select(0))
        self.live_btn.clicked.connect(lambda: self._select(1))

        self._select(0, emit=False)

    def _select(self, index, emit=True):

        self.footprint_btn.setChecked(index == 0)
        self.live_btn.setChecked(index == 1)

        for btn, active in (
            (self.footprint_btn, index == 0),
            (self.live_btn, index == 1),
        ):
            btn.setProperty("active", "true" if active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

        if emit:
            self.view_changed.emit(index)
