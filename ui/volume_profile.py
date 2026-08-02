from PyQt6.QtWidgets import QWidget
from PyQt6.QtGui import QPainter, QColor, QFont, QPen
from PyQt6.QtCore import Qt, QRectF

# Reserve sufficient fixed width so price labels fit cleanly — this
# column is drawn every paint regardless of how many price levels
# exist, so it never disappears the way the old per-row labels did.
PRICE_AXIS_WIDTH = 60


class VolumeProfile(QWidget):
    """
    VPVR — horizontal bars per traded price level, split buy (blue) vs
    sell (orange), like Pic 2's Volume Profile panel. Built from the
    same footprint data as the main chart (core.candle_engine.
    aggregate_volume_profile), so it only reflects live-tick activity,
    not REST-backfilled history (that endpoint has no per-level detail).
    """

    def __init__(self):
        super().__init__()

        self.setMinimumHeight(260)
        self.setStyleSheet("background:#131722; border:1px solid #1E222D; border-radius:8px;")

        self.profile = {}
        self.current_price = None

        # Optional external price range (min, max) — set by the
        # dashboard controller from the main chart's active Y-range so
        # this panel's price scale lines up horizontally with the
        # candles instead of drifting off on its own scale. Falls back
        # to the profile's own min/max price level when not provided.
        self._synced_range = None

    def set_profile(self, profile, current_price=None):
        self.profile = profile
        self.current_price = current_price
        self.update()

    def set_price_range(self, min_p, max_p):
        """Sync the VPVR's price axis to the main chart's visible
        price bounds so levels line up horizontally with the candles."""
        if min_p is None or max_p is None or max_p <= min_p:
            self._synced_range = None
        else:
            self._synced_range = (min_p, max_p)
        self.update()

    def _axis_range(self, levels):
        if self._synced_range is not None:
            return self._synced_range
        if not levels:
            return 0.0, 1.0
        lo, hi = min(levels), max(levels)
        if hi <= lo:
            pad = max(abs(hi) * 0.005, 0.5)
            return lo - pad, hi + pad
        return lo, hi

    def paintEvent(self, event):

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        painter.fillRect(self.rect(), QColor("#131722"))

        title_h = 26
        painter.setPen(QColor("#00FF88"))
        painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        painter.drawText(QRectF(10, 4, self.width() - 20, title_h - 4),
                          Qt.AlignmentFlag.AlignVCenter, "📊 VOLUME PROFILE (VPVR)")

        if not self.profile:
            painter.setPen(QColor("#666"))
            painter.setFont(QFont("Segoe UI", 9))
            painter.drawText(self.rect().adjusted(0, title_h, 0, 0),
                              Qt.AlignmentFlag.AlignCenter,
                              "Building profile from live trades...")
            painter.end()
            return

        levels = sorted(self.profile.keys(), reverse=True)

        top_margin = title_h + 6
        bottom_margin = 6
        usable_h = self.height() - top_margin - bottom_margin
        row_h = usable_h / max(len(levels), 1)

        max_total = max(
            (row["buy"] + row["sell"] for row in self.profile.values()),
            default=1
        ) or 1

        nearest_level = None
        if self.current_price is not None and levels:
            nearest_level = min(levels, key=lambda lvl: abs(lvl - self.current_price))

        # Bars start right after the dedicated price-axis column.
        bar_area_w = self.width() - PRICE_AXIS_WIDTH - 10
        bar_x = PRICE_AXIS_WIDTH + 6

        font = QFont("Consolas", 8)
        painter.setFont(font)

        for i, level in enumerate(levels):

            row = self.profile[level]
            buy = row["buy"]
            sell = row["sell"]
            total = buy + sell

            y = top_margin + i * row_h

            is_current = (nearest_level is not None and level == nearest_level)

            bar_w = (total / max_total) * bar_area_w
            buy_w = (buy / total * bar_w) if total else 0
            sell_w = bar_w - buy_w

            bar_h = max(row_h - 3, 2)

            if buy_w > 0:
                painter.fillRect(QRectF(bar_x, y + 1, buy_w, bar_h),
                                  QColor("#2f7ff2"))

            if sell_w > 0:
                painter.fillRect(QRectF(bar_x + buy_w, y + 1, sell_w, bar_h),
                                  QColor("#f2a92f"))

            if is_current:
                painter.setPen(QPen(QColor("#00FF88"), 1, Qt.PenStyle.DashLine))
                painter.drawLine(QRectF(bar_x, y, bar_area_w, row_h).topLeft(),
                                  QRectF(bar_x, y, bar_area_w, row_h).topRight())

        # --- Dedicated Price (Y) Axis — always drawn, fixed width ---
        # Explicitly enabled/styled and independent of how many price
        # levels exist, so it can never end up invisible/truncated the
        # way the old "skip a label if rows are too tight" logic did.
        axis_rect = QRectF(0, top_margin, PRICE_AXIS_WIDTH, usable_h)
        painter.setPen(QPen(QColor("#1E222D"), 1))
        painter.drawLine(int(PRICE_AXIS_WIDTH), int(top_margin),
                          int(PRICE_AXIS_WIDTH), int(top_margin + usable_h))

        min_p, max_p = self._axis_range(levels)
        if max_p > min_p and usable_h > 0:
            axis_font = QFont("Arial", 8)
            painter.setFont(axis_font)

            # Evenly spaced ticks (independent of row count/height) —
            # a fixed, readable number of labels regardless of how many
            # price levels are packed into the profile.
            tick_count = max(2, min(10, int(usable_h // 24)))
            price_range = max_p - min_p

            for t in range(tick_count + 1):
                frac = t / tick_count
                price = max_p - frac * price_range
                y = top_margin + frac * usable_h

                painter.setPen(QPen(QColor("#2A2E39"), 1))
                painter.drawLine(int(PRICE_AXIS_WIDTH - 4), int(y), int(PRICE_AXIS_WIDTH), int(y))

                is_current_tick = (
                    self.current_price is not None
                    and abs(price - self.current_price) <= (price_range / max(tick_count, 1)) / 2.0
                )
                painter.setPen(QColor("#00FF88") if is_current_tick else QColor("#B2B5BE"))
                painter.drawText(
                    QRectF(4, y - 8, PRICE_AXIS_WIDTH - 8, 16),
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                    f"{price:,.1f}",
                )

        painter.end()