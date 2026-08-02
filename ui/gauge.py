from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QFont, QPen
from PyQt6.QtCore import Qt, QRectF


class CircularGauge(QWidget):
    """Small circular percentage gauge (arc + centered %) with a title
    above and a status label below — e.g. 'AI SIGNAL' / 92% / 'BULLISH'."""

    def __init__(self, title, size=74):
        super().__init__()

        self.title = title
        self.value = 0.0
        self.label_text = "--"
        self.color = QColor("#2ecc71")

        self._diameter = size
        self.setFixedSize(size + 20, size + 36)

    def set_value(self, value, label_text=None, color=None):

        try:
            self.value = max(0.0, min(100.0, float(value)))
        except (TypeError, ValueError):
            self.value = 0.0

        if label_text is not None:
            self.label_text = label_text

        if color is not None:
            self.color = QColor(color)

        self.update()

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()

        # title
        painter.setPen(QColor("#999"))
        painter.setFont(QFont("Segoe UI", 8))
        painter.drawText(QRectF(0, 0, w, 14), Qt.AlignmentFlag.AlignHCenter, self.title)

        # arc
        d = self._diameter
        rect = QRectF((w - d) / 2, 16, d, d)

        bg_pen = QPen(QColor("#2b2b2b"), 6)
        bg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(bg_pen)
        painter.drawArc(rect, 0, 360 * 16)

        fg_pen = QPen(self.color, 6)
        fg_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(fg_pen)
        span = int(360 * (self.value / 100) * 16)
        painter.drawArc(rect, 90 * 16, -span)

        # % text, centered in the arc
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self.value:.0f}%")

        # status label below
        painter.setPen(self.color)
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(QRectF(0, 16 + d + 2, w, 16),
                          Qt.AlignmentFlag.AlignHCenter, self.label_text)
