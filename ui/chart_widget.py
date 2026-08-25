from datetime import datetime, timedelta, timezone
import math
import time
from PyQt6.QtCore import QPointF, QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.candle_engine import CandleManager, calculate_dynamic_tick_size

# UI Metric Constants
PRICE_AXIS_WIDTH = 75
TIME_AXIS_HEIGHT = 28
FUTURE_MARGIN_BARS = 3  # empty bars of future time reserved on the right, TradingView-style


def price_to_y(price, min_p, max_p, height, is_log=False):
    """Map price values directly to pixel Y positions safely."""
    if max_p <= min_p or height <= 0:
        return height / 2.0

    if is_log and min_p > 0 and price > 0:
        log_p = math.log(price)
        log_min = math.log(min_p)
        log_max = math.log(max_p)
        if log_max <= log_min:
            return height / 2.0
        ratio = (log_p - log_min) / (log_max - log_min)
    else:
        ratio = (price - min_p) / (max_p - min_p)

    return height - (ratio * height)


def y_to_price(y, min_p, max_p, height, is_log=False):
    """Map pixel Y positions back to price values safely."""
    if height <= 0 or max_p <= min_p:
        return (min_p + max_p) / 2.0

    ratio = (height - y) / height
    if is_log and min_p > 0 and max_p > 0:
        log_min = math.log(min_p)
        log_max = math.log(max_p)
        return math.exp(log_min + ratio * (log_max - log_min))

    return min_p + ratio * (max_p - min_p)


class PriceAxis(QWidget):
    """TradingView Style Interactive Vertical Price Axis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(PRICE_AXIS_WIDTH)
        self.min_price = 0.0
        self.max_price = 1.0
        self.is_log = False
        self.current_price = None
        self.is_bullish = True
        self.candle_countdown = None
        self.hover_y = None
        self.dragging = False
        self.last_mouse_y = 0.0

        self.on_scale_dragged = None
        self.on_auto_reset = None
        self.setMouseTracking(True)

    def set_range(self, min_p, max_p, is_log=False, current_price=None, is_bullish=True, hover_y=None):
        self.min_price = min_p
        self.max_price = max_p
        self.is_log = is_log
        self.current_price = current_price
        self.is_bullish = is_bullish
        self.hover_y = hover_y
        self.update()

    def set_candle_countdown(self, countdown):
        """Update the current-candle countdown without recalculating the chart."""
        if self.candle_countdown != countdown:
            self.candle_countdown = countdown
            self.update()

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            self.dragging = True
            self.last_mouse_y = event.position().y()
            self.setCursor(Qt.CursorShape.SizeVerCursor)

    def mouseMoveEvent(self, event):
        self.hover_y = event.position().y()
        if self.dragging and self.on_scale_dragged:
            dy = event.position().y() - self.last_mouse_y
            self.last_mouse_y = event.position().y()
            self.on_scale_dragged(dy)
        self.update()

    def leaveEvent(self, event):
        self.hover_y = None
        self.update()

    def mouseReleaseEvent(self, event):
        self.dragging = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        if self.on_auto_reset:
            self.on_auto_reset()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#121318"))
        painter.setPen(QPen(QColor("#1E222D"), 1))
        painter.drawLine(0, 0, 0, self.height())

        if self.max_price <= self.min_price:
            return

        h = self.height()
        painter.setFont(QFont("Consolas", 8))

        price_range = self.max_price - self.min_price
        step = max(0.1, round(price_range / 10.0, 1))

        current_p = math.ceil(self.min_price / step) * step
        while current_p <= self.max_price:
            y = price_to_y(current_p, self.min_price, self.max_price, h, self.is_log)
            painter.setPen(QPen(QColor("#2A2E39"), 1))
            painter.drawLine(0, int(y), 4, int(y))

            painter.setPen(QColor("#B2B5BE"))
            painter.drawText(
                QRectF(6, y - 8, PRICE_AXIS_WIDTH - 8, 16),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                f"{current_p:,.1f}",
            )
            current_p += step

        # Crosshair Price Indicator Label
        if self.hover_y is not None and 0 <= self.hover_y <= h:
            hover_p = y_to_price(self.hover_y, self.min_price, self.max_price, h, self.is_log)
            pill_rect = QRectF(0, self.hover_y - 9, PRICE_AXIS_WIDTH, 18)
            painter.fillRect(pill_rect, QColor("#363A45"))
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, f"{hover_p:,.1f}")

        # Current Live Price Label
        if self.current_price is not None and self.min_price <= self.current_price <= self.max_price:
            y_curr = price_to_y(self.current_price, self.min_price, self.max_price, h, self.is_log)
            bg_col = QColor("#089981") if self.is_bullish else QColor("#F23645")

            pill_rect = QRectF(0, y_curr - 10, PRICE_AXIS_WIDTH, 20)
            painter.fillRect(pill_rect, bg_col)
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
            painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, f"{self.current_price:,.1f}")

            # TradingView-style time remaining for the live candle.  It is
            # drawn on the same right-hand scale, directly below the price
            # unless the price is near the bottom of the visible range.
            if self.candle_countdown:
                timer_y = y_curr + 11
                if timer_y + 18 > h:
                    timer_y = y_curr - 30
                timer_rect = QRectF(0, timer_y, PRICE_AXIS_WIDTH, 18)
                painter.fillRect(timer_rect, bg_col)
                painter.drawText(timer_rect, Qt.AlignmentFlag.AlignCenter, self.candle_countdown)


class TimeAxis(QWidget):
    """TradingView Style Horizontal Time Axis matched strictly to canvas x-coordinates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(TIME_AXIS_HEIGHT)
        self.setMinimumHeight(TIME_AXIS_HEIGHT)
        self.candles = []
        self.candle_width = 160
        self.pan_offset_x = 0.0
        self.timeframe_sec = 300

    def set_params(self, candles, candle_w, pan_x, timeframe_sec):
        self.candles = candles
        self.candle_width = max(1.0, candle_w)
        self.pan_offset_x = pan_x
        self.timeframe_sec = max(1, timeframe_sec)
        self.update()

    def _get_timestamp_sec(self, candle):
        """Extract clean Epoch Unix timestamp in seconds."""
        raw_ts = None
        for attr in ("start_time", "timestamp", "time", "ts", "date", "datetime"):
            if hasattr(candle, attr):
                raw_ts = getattr(candle, attr)
                if raw_ts is not None:
                    break

        if raw_ts is None and isinstance(candle, dict):
            for key in ("start_time", "timestamp", "time", "ts", "date", "datetime"):
                if key in candle and candle[key] is not None:
                    raw_ts = candle[key]
                    break

        if raw_ts is None:
            return None

        try:
            if isinstance(raw_ts, (int, float)):
                return raw_ts / 1000.0 if raw_ts > 1e11 else float(raw_ts)
            if isinstance(raw_ts, datetime):
                return raw_ts.timestamp()
            if isinstance(raw_ts, str):
                return datetime.fromisoformat(raw_ts.replace("Z", "+00:00")).timestamp()
        except Exception:
            pass

        return None

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Background Frame Rendering
        painter.fillRect(self.rect(), QColor("#121318"))
        painter.setPen(QPen(QColor("#2A2E39"), 1))
        painter.drawLine(0, 0, self.width(), 0)

        w = self.width()
        cw = self.candle_width
        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))

        if not self.candles:
            return

        # Calculate stride spacing based on candle width so labels don't collide
        min_label_px = 100.0
        step_bars = max(1, math.ceil(min_label_px / cw))

        last_valid_ts = None
        last_valid_idx = None

        for idx in range(0, len(self.candles), step_bars):
            c = self.candles[idx]
            ts_sec = self._get_timestamp_sec(c)
            if ts_sec is None:
                continue

            last_valid_ts = ts_sec
            last_valid_idx = idx

            # Exact center X corresponding to candle center on canvas
            x = (idx * cw) + self.pan_offset_x + (cw / 2.0)

            # Draw labels if within or near viewport boundaries
            if -50 <= x <= w + 50:
                dt = datetime.fromtimestamp(ts_sec)

                # Format string matched to TradingView standard
                if self.timeframe_sec >= 86400:
                    time_str = dt.strftime("%d %b %y")
                elif self.timeframe_sec < 60:
                    time_str = dt.strftime("%H:%M:%S")
                else:
                    time_str = dt.strftime("%H:%M")

                # Tick mark
                painter.setPen(QPen(QColor("#363A45"), 1))
                painter.drawLine(int(x), 0, int(x), 5)

                # Time Label Text
                painter.setPen(QColor("#8F96A3"))
                painter.drawText(
                    QRectF(int(x) - 45, 4, 90, TIME_AXIS_HEIGHT - 4),
                    Qt.AlignmentFlag.AlignCenter,
                    time_str,
                )

        # Fallback: if no real candle carried a usable timestamp, anchor future
        # projection off the last candle's index 0 so the axis isn't left blank.
        if last_valid_ts is None and self.candles:
            last_valid_ts = time.time()
            last_valid_idx = len(self.candles) - 1

        # Project evenly-spaced labels into the empty margin beyond the last
        # candle (future time), same stride as the historical labels above.
        if last_valid_ts is not None:
            last_drawn_idx = ((len(self.candles) - 1) // step_bars) * step_bars
            idx = last_drawn_idx + step_bars
            safety_cap = 500

            while safety_cap > 0:
                safety_cap -= 1
                x = (idx * cw) + self.pan_offset_x + (cw / 2.0)
                if x > w + 50:
                    break

                ts_future = last_valid_ts + (idx - last_valid_idx) * self.timeframe_sec
                dt = datetime.fromtimestamp(ts_future)

                if self.timeframe_sec >= 86400:
                    time_str = dt.strftime("%d %b %y")
                elif self.timeframe_sec < 60:
                    time_str = dt.strftime("%H:%M:%S")
                else:
                    time_str = dt.strftime("%H:%M")

                if x >= -50:
                    painter.setPen(QPen(QColor("#2A2E39"), 1))
                    painter.drawLine(int(x), 0, int(x), 5)

                    painter.setPen(QColor("#5A5F6B"))
                    painter.drawText(
                        QRectF(int(x) - 45, 4, 90, TIME_AXIS_HEIGHT - 4),
                        Qt.AlignmentFlag.AlignCenter,
                        time_str,
                    )

                idx += step_bars


class FootprintCanvas(QWidget):
    """TradingView Chart Engine with Dynamic Crosshair and Footprint Overlays."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.candles = []
        self.min_price = 0.0
        self.max_price = 1.0
        self.is_log = False
        self.candle_width = 160
        self.pan_offset_x = 0.0
        self.timeframe_sec = 300

        self.panning = False
        self.last_pan_pos = QPointF()
        self.crosshair_pos = None

        self.on_pan = None
        self.on_zoom = None
        self.on_crosshair_move = None
        self.setMouseTracking(True)

        # Entry / Stop-Loss / Take-Profit overlay lines for open
        # positions (spec: "Chart Visualization: Draw Entry, SL, & TP
        # Lines", TradingView-style). Each entry:
        # {"entry","side","stop_loss","take_profit","risk_usd","reward_usd"}
        self.position_lines = []

    def set_position_lines(self, lines):
        self.position_lines = lines or []
        self.update()

    def set_candles(self, candles, min_p, max_p, is_log, candle_w, pan_x, timeframe_sec):
        self.candles = candles
        self.min_price = min_p
        self.max_price = max_p
        self.is_log = is_log
        self.candle_width = max(80, candle_w)
        self.pan_offset_x = pan_x
        self.timeframe_sec = timeframe_sec
        self.update()

    def wheelEvent(self, event):
        if self.on_zoom:
            self.on_zoom(event.angleDelta().y())

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            self.panning = True
            self.last_pan_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event):
        self.crosshair_pos = event.position()
        if self.on_crosshair_move:
            self.on_crosshair_move(self.crosshair_pos.y())

        if self.panning and self.on_pan:
            delta = event.position() - self.last_pan_pos
            self.last_pan_pos = event.position()
            self.on_pan(delta.x(), delta.y())
        self.update()

    def leaveEvent(self, event):
        self.crosshair_pos = None
        if self.on_crosshair_move:
            self.on_crosshair_move(None)
        self.update()

    def mouseReleaseEvent(self, event):
        self.panning = False
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def _format_vol(self, val):
        """Format a volume/delta figure for on-chart display.

        2026-08-18 fix: trade sizes are now correctly denominated in
        actual BTC (see exchange/websocket_client.py's contract->BTC
        conversion) rather than raw whole-number Delta contract
        counts. The old fallback here did `f"{int(val)}"` -- harmless
        truncation back when a "typical" cell value was already a
        whole number (e.g. 5 contracts), but with real BTC sizes most
        individual footprint cells hold well under 1.0 (e.g. 0.005,
        0.03, 0.686 BTC), so int() collapsed nearly every cell and
        every candle's Delta/Total label to "0" -- exactly the "0
        after the 1st candle" pattern reported against a live
        screenshot. Sub-1 values now keep decimal precision instead of
        being truncated to an integer.
        """
        abs_v = abs(val)
        if abs_v >= 1_000_000:
            return f"{val/1_000_000:.2f}M"
        elif abs_v >= 1_000:
            return f"{val/1_000:.1f}K"
        elif abs_v >= 1:
            return f"{val:.2f}"
        elif abs_v > 0:
            return f"{val:.3f}"
        return "0"

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#121318"))

        if self.max_price <= self.min_price:
            return

        h = self.height()
        cw = max(1.0, self.candle_width)

        # Grid Lines
        painter.setPen(QPen(QColor("#1E222D"), 1, Qt.PenStyle.DashLine))
        price_range = self.max_price - self.min_price
        step = max(0.1, round(price_range / 10.0, 1))
        curr_p = math.ceil(self.min_price / step) * step
        while curr_p <= self.max_price:
            gy = price_to_y(curr_p, self.min_price, self.max_price, h, self.is_log)
            painter.drawLine(0, int(gy), self.width(), int(gy))
            curr_p += step

        latest_close = None
        latest_is_bull = True

        start_i = max(0, int((-self.pan_offset_x) // cw) - 1)
        end_i = min(len(self.candles), start_i + int(self.width() // cw) + 3)

        for i in range(start_i, end_i):
            c = self.candles[i]
            if getattr(c, "high", None) is None or getattr(c, "low", None) is None:
                continue

            cx = (i * cw) + self.pan_offset_x
            col_width = (cw - 24) / 2.0
            y_high = price_to_y(c.high, self.min_price, self.max_price, h, self.is_log)
            y_low = price_to_y(c.low, self.min_price, self.max_price, h, self.is_log)
            y_open = price_to_y(c.open, self.min_price, self.max_price, h, self.is_log)
            y_close = price_to_y(c.close, self.min_price, self.max_price, h, self.is_log)

            is_bull = c.close >= c.open
            theme_col = QColor("#089981") if is_bull else QColor("#F23645")

            if i == len(self.candles) - 1:
                latest_close = c.close
                latest_is_bull = is_bull

            center_x = cx + cw / 2.0

            # Central Wick
            painter.setPen(QPen(theme_col, 2))
            painter.drawLine(int(center_x), int(y_high), int(center_x), int(y_low))

            # Body
            body_top = min(y_open, y_close)
            body_h = max(abs(y_close - y_open), 2.0)
            body_w = 6.0
            body_rect = QRectF(center_x - (body_w / 2.0), body_top, body_w, body_h)
            painter.fillRect(body_rect, theme_col)

            # Footprint Volumes
            footprint = getattr(c, "footprint", {})
            if footprint:
                sorted_prices = sorted(footprint.keys(), reverse=True)

                if len(sorted_prices) > 1:
                    price_step = abs(sorted_prices[0] - sorted_prices[1])
                    y_p0 = price_to_y(sorted_prices[0], self.min_price, self.max_price, h, self.is_log)
                    y_p1 = price_to_y(sorted_prices[0] - price_step, self.min_price, self.max_price, h, self.is_log)
                    cell_h = max(1.0, abs(y_p1 - y_p0))
                else:
                    cell_h = 14.0

                poc_price = max(
                    footprint.keys(),
                    key=lambda p: footprint[p].get("buy", 0) + footprint[p].get("sell", 0),
                ) if footprint else None

                max_vol_row = max(
                    (f.get("buy", 0) + f.get("sell", 0) for f in footprint.values()), default=1.0
                )
                max_vol_row = max(max_vol_row, 1.0)

                for price in sorted_prices:
                    y_p = price_to_y(price, self.min_price, self.max_price, h, self.is_log)

                    if y_p + cell_h < 0 or y_p - cell_h > h:
                        continue

                    row_data = footprint[price]
                    sell_v = row_data.get("sell", 0.0)
                    buy_v = row_data.get("buy", 0.0)

                    if sell_v <= 0 and buy_v <= 0:
                        continue

                    seller_rect = QRectF(
                        center_x - body_w / 2.0 - col_width,
                        y_p - (cell_h / 2.0),
                        col_width,
                        max(1.0, cell_h - 1.0),
                    )
                    buyer_rect = QRectF(
                        center_x + body_w / 2.0,
                        y_p - (cell_h / 2.0),
                        col_width,
                        max(1.0, cell_h - 1.0),
                    )

                    sell_alpha = int(60 + (sell_v / max_vol_row) * 170)
                    buy_alpha = int(60 + (buy_v / max_vol_row) * 170)

                    painter.fillRect(seller_rect, QColor(242, 54, 69, min(230, sell_alpha)))
                    painter.fillRect(buyer_rect, QColor(8, 153, 129, min(230, buy_alpha)))

                    if price == poc_price:
                        painter.setPen(QPen(QColor("#FFD700"), 1.5))
                        painter.drawRect(seller_rect)
                        painter.drawRect(buyer_rect)

                    if cell_h >= 10.0:
                        font_size = 8 if cell_h >= 16.0 else (7 if cell_h >= 13.0 else 6)
                        painter.setFont(QFont("Consolas", font_size, QFont.Weight.Bold))
                        painter.setPen(QColor("#FFFFFF"))

                        s_str = self._format_vol(sell_v)
                        b_str = self._format_vol(buy_v)

                        painter.drawText(seller_rect, Qt.AlignmentFlag.AlignCenter, s_str)
                        painter.drawText(buyer_rect, Qt.AlignmentFlag.AlignCenter, b_str)

            # Delta & Volume Summary Box
            tot_vol = getattr(c, "volume", 0.0)
            delta = getattr(c, "delta", 0.0)

            box_w = max(60.0, cw - 16.0)
            box_h = 28.0
            box_x = center_x - (box_w / 2.0)
            box_y = y_low + 6.0

            card_rect = QRectF(box_x, box_y, box_w, box_h)
            painter.fillRect(card_rect, QColor("#161922"))
            painter.setPen(QPen(QColor("#2A2E39"), 1))
            painter.drawRoundedRect(card_rect, 3, 3)

            delta_color = QColor("#089981") if delta >= 0 else QColor("#F23645")
            painter.setFont(QFont("Consolas", 7, QFont.Weight.Bold))

            painter.setPen(delta_color)
            painter.drawText(QRectF(box_x, box_y + 2, box_w, 12), Qt.AlignmentFlag.AlignCenter, f"Delta {self._format_vol(delta)}")

            painter.setPen(QColor("#8F96A3"))
            painter.drawText(QRectF(box_x, box_y + 14, box_w, 12), Qt.AlignmentFlag.AlignCenter, f"Total {self._format_vol(tot_vol)}")

        # Dotted Line for Current Price
        if latest_close is not None and self.min_price <= latest_close <= self.max_price:
            y_curr = price_to_y(latest_close, self.min_price, self.max_price, h, self.is_log)
            line_color = QColor("#089981") if latest_is_bull else QColor("#F23645")

            painter.setPen(QPen(line_color, 1, Qt.PenStyle.DotLine))
            painter.drawLine(0, int(y_curr), self.width(), int(y_curr))

        # Entry / Stop-Loss / Take-Profit overlay lines for open
        # positions — TradingView-style: solid blue Entry line, red
        # dashed Stop Loss line labeled with the $ loss it represents,
        # green dashed Take Profit line labeled with the $ gain.
        for line in self.position_lines:
            self._draw_position_line(
                painter, price=line.get("entry"),
                color=QColor("#2979FF"), style=Qt.PenStyle.SolidLine,
                label=f"{line.get('side', '')} ENTRY  {line.get('entry', 0):,.1f}",
                label_bg=QColor("#2979FF"),
            )
            if line.get("stop_loss"):
                self._draw_position_line(
                    painter, price=line["stop_loss"],
                    color=QColor("#F23645"), style=Qt.PenStyle.DashLine,
                    label=f"SL   -{abs(line.get('risk_usd', 0)):,.2f} USD",
                    label_bg=QColor("#F23645"),
                )
            if line.get("take_profit"):
                self._draw_position_line(
                    painter, price=line["take_profit"],
                    color=QColor("#089981"), style=Qt.PenStyle.DashLine,
                    label=f"TP   +{abs(line.get('reward_usd', 0)):,.2f} USD",
                    label_bg=QColor("#089981"),
                )

        # Dynamic Crosshair
        if self.crosshair_pos is not None:
            painter.setPen(QPen(QColor("#787B86"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(0, int(self.crosshair_pos.y()), self.width(), int(self.crosshair_pos.y()))
            painter.drawLine(int(self.crosshair_pos.x()), 0, int(self.crosshair_pos.x()), self.height())

    def _draw_position_line(self, painter, price, color, style, label, label_bg):
        if price is None or not (self.min_price <= price <= self.max_price):
            return

        h = self.height()
        y = price_to_y(price, self.min_price, self.max_price, h, self.is_log)

        painter.setPen(QPen(color, 1, style))
        painter.drawLine(0, int(y), self.width(), int(y))

        painter.setFont(QFont("Consolas", 8, QFont.Weight.Bold))
        text_w = painter.fontMetrics().horizontalAdvance(label) + 12

        # Clamp the label pill's vertical position to stay fully inside
        # the canvas (TradingView-style) even when its price sits right
        # at the top/bottom edge of the visible range — the dashed/solid
        # line itself still gets drawn at the exact true price (above),
        # only the readability of the label text is protected here.
        label_y = min(max(y - 9, 2.0), h - 20.0)
        label_rect = QRectF(8, label_y, text_w, 18)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(label_bg)
        painter.drawRoundedRect(label_rect, 3, 3)

        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, label)


class FootprintChart(QWidget):
    """Main Chart Layout combining Canvas, Right Price Axis, and Bottom Time Axis."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.candles = []
        self.auto_scale = True
        self.is_log = False
        self.manual_min_p = None
        self.manual_max_p = None
        self.candle_width = 160
        self.pan_offset_x = 0.0
        # The dashboard's selected timeframe is the single source of truth
        # for the candle countdown.  Do not derive the close from the
        # CandleManager's aggregated candle start_time: its aggregation can
        # be offset (especially on 1H/4H/1D), while Delta/TradingView BTCUSD
        # candles are aligned to UTC exchange boundaries.
        self.timeframe_sec = 300
        self._selected_timeframe_sec = 300
        self.current_price = None
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._refresh_candle_countdown)
        self._countdown_timer.start()

        # The chart's own size must only ever come from whatever
        # container/splitter it's placed in — never from its content.
        # Without this, a stylesheet repolish elsewhere in the window
        # (e.g. the AUTO MODE toggle button) can trigger a layout pass
        # that briefly lets this widget's *content* (candle count,
        # label text, etc.) influence its size hint, which is what
        # produced the chart-viewport "stretch/jump" on toggle.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Main Plot Area
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)

        self.canvas = FootprintCanvas()
        self.canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.canvas.on_pan = self._on_canvas_pan
        self.canvas.on_zoom = self._on_canvas_zoom
        self.canvas.on_crosshair_move = self._on_crosshair_moved
        top_layout.addWidget(self.canvas, 1)

        self.price_axis = PriceAxis()
        self.price_axis.on_scale_dragged = self._on_axis_dragged
        self.price_axis.on_auto_reset = self._reset_auto_scale
        top_layout.addWidget(self.price_axis, 0)

        main_layout.addWidget(top_widget, 1)

        # Bottom Time Scale Frame
        bottom_widget = QWidget()
        bottom_widget.setFixedHeight(TIME_AXIS_HEIGHT)
        bottom_widget.setMinimumHeight(TIME_AXIS_HEIGHT)

        bottom_layout = QHBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.setSpacing(0)

        self.time_axis = TimeAxis()
        bottom_layout.addWidget(self.time_axis, 1)

        axis_corner = QWidget()
        axis_corner.setFixedWidth(PRICE_AXIS_WIDTH)
        axis_corner.setFixedHeight(TIME_AXIS_HEIGHT)
        axis_corner.setStyleSheet("background-color: #121318; border-top: 1px solid #1E222D; border-left: 1px solid #1E222D;")
        bottom_layout.addWidget(axis_corner, 0)

        main_layout.addWidget(bottom_widget, 0)

    def set_candles(self, candles, timeframe_sec=300, current_price=None):
        self.candles = candles
        # Incoming candle refreshes may carry a legacy/default timeframe.
        # Never let them overwrite the timeframe selected in the dashboard.
        self.timeframe_sec = self._selected_timeframe_sec
        # The live/forming candle's own high/low should already track
        # the latest tick, but ticks can arrive between candle updates
        # and chart redraws — explicitly folding the *actual* current
        # price into the Y-range calc (see _get_active_range) is a
        # defensive guard against the price momentarily sitting outside
        # whatever the last-known candle high/low was.
        self.current_price = current_price if current_price is not None else (
            candles[-1].close if candles else None
        )
        self._refresh_candle_countdown()

        if self.auto_scale and self.candles:
            canvas_w = max(self.canvas.width(), 800)
            future_margin = self.candle_width * FUTURE_MARGIN_BARS
            self.pan_offset_x = canvas_w - (len(self.candles) * self.candle_width) - future_margin

        self._recalculate_and_draw()

    def set_position_lines(self, lines):
        """lines: list of dicts, one per open position —
        {"entry","side","stop_loss","take_profit","risk_usd","reward_usd"}.
        Redraws Entry/SL/TP overlay lines dynamically whenever positions
        open/close or their SL/TP values change (called every UI tick
        from DashboardController.refresh_positions).

        Entry/SL/TP prices now feed into _get_active_range() (so a stop
        placed outside the visible candles' own high/low doesn't get
        clipped) — recalculating right here, instead of waiting for the
        next set_candles() tick, keeps that in sync immediately instead
        of lagging one UI-refresh cycle behind a position open/edit."""
        self.canvas.set_position_lines(lines)
        self._recalculate_and_draw()

    def set_timeframe(self, timeframe):
        """Set timeframe from the dashboard selector (1m/5m/15m/1H/4H/1D).

        Accepts either the button label ("1H") or the lowercase REST
        resolution string ("1h") — TimeframeSelector.timeframe_changed
        emits (resolution, seconds), and `resolution` is lowercase for
        hour/day units ("1h"/"4h"/"1d"; see ui/timeframe_selector.py's
        TIMEFRAMES list). Dashboard._on_timeframe_changed only declares
        one parameter, so PyQt hands it that lowercase resolution
        string, not the seconds int or the label.

        Without .upper() here, "1h"/"4h"/"1d" never matched this map's
        uppercase keys, so tf_sec came back None and the method
        returned BEFORE updating self._selected_timeframe_sec — the
        chart (and therefore the candle-close countdown, which reads
        _selected_timeframe_sec) silently stayed on whatever timeframe
        was active before switching to 1H/4H/1D. "1m"/"5m"/"15m" never
        showed this because the "M"/"m" unit doesn't change case
        between the label and the resolution string — only "H" and "D"
        do, which is exactly why the countdown broke specifically on
        the jump from 15m to 1H (and would also break for 4H/1D).
        """
        timeframe_map = {
            "1M": 60,
            "5M": 300,
            "15M": 900,
            "1H": 3600,
            "4H": 14400,
            "1D": 86400,
        }
        tf_sec = timeframe_map.get(str(timeframe).upper())
        if tf_sec is None:
            return

        self._selected_timeframe_sec = tf_sec
        self.timeframe_sec = tf_sec
        self._refresh_candle_countdown()
        self._reset_auto_scale()

    def change_timeframe(self, tf_sec):
        """Backward-compatible numeric timeframe setter."""
        try:
            tf_sec = int(tf_sec)
        except (TypeError, ValueError):
            return
        if tf_sec <= 0:
            return

        self._selected_timeframe_sec = tf_sec
        self.timeframe_sec = tf_sec
        self._refresh_candle_countdown()
        self._reset_auto_scale()

    @staticmethod
    def _next_utc_boundary(now_utc, tf_sec):
        """Return the next exchange-aligned UTC candle close."""
        if tf_sec < 3600:
            epoch = now_utc.timestamp()
            next_epoch = (math.floor(epoch / tf_sec) + 1) * tf_sec
            return datetime.fromtimestamp(next_epoch, tz=timezone.utc)

        if tf_sec == 3600:
            return now_utc.replace(
                minute=0, second=0, microsecond=0
            ) + timedelta(hours=1)

        if tf_sec == 14400:
            block_hour = (now_utc.hour // 4) * 4
            close = now_utc.replace(
                hour=block_hour, minute=0, second=0, microsecond=0
            )
            if close <= now_utc:
                close += timedelta(hours=4)
            return close

        if tf_sec == 86400:
            close = now_utc.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            if close <= now_utc:
                close += timedelta(days=1)
            return close

        epoch = now_utc.timestamp()
        next_epoch = (math.floor(epoch / tf_sec) + 1) * tf_sec
        return datetime.fromtimestamp(next_epoch, tz=timezone.utc)

    def _refresh_candle_countdown(self):
        """Show remaining time to the selected Delta/TradingView candle close."""
        if not self.candles:
            self.price_axis.set_candle_countdown(None)
            return

        now_utc = datetime.now(timezone.utc)
        next_close_utc = self._next_utc_boundary(
            now_utc, int(self._selected_timeframe_sec)
        )

        remaining = max(
            0,
            math.ceil((next_close_utc - now_utc).total_seconds())
        )

        hours, remainder = divmod(remaining, 3600)
        minutes, seconds = divmod(remainder, 60)
        countdown = (
            f"{hours}:{minutes:02d}:{seconds:02d}"
            if hours
            else f"{minutes:02d}:{seconds:02d}"
        )
        self.price_axis.set_candle_countdown(countdown)

    def _reset_auto_scale(self):
        self.auto_scale = True
        self.manual_min_p = None
        self.manual_max_p = None
        if self.candles:
            canvas_w = max(self.canvas.width(), 800)
            future_margin = self.candle_width * FUTURE_MARGIN_BARS
            self.pan_offset_x = canvas_w - (len(self.candles) * self.candle_width) - future_margin
        self._recalculate_and_draw()

    def _on_canvas_pan(self, dx, dy):
        self.pan_offset_x += dx

        if abs(dy) > 0.1:
            self.auto_scale = False
            min_p, max_p = self._get_active_range()
            span = max_p - min_p
            shift = (dy / max(self.canvas.height(), 1)) * span
            self.manual_min_p = min_p + shift
            self.manual_max_p = max_p + shift

        self._recalculate_and_draw()

    def _on_canvas_zoom(self, delta):
        if delta > 0:
            self.candle_width = min(320, self.candle_width + 15)
        else:
            self.candle_width = max(90, self.candle_width - 15)
        self._recalculate_and_draw()

    def _on_crosshair_moved(self, y_pos):
        min_p, max_p = self._get_active_range()
        curr_p = self.candles[-1].close if self.candles else None
        is_bullish = self.candles[-1].close >= self.candles[-1].open if self.candles else True
        self.price_axis.set_range(min_p, max_p, self.is_log, curr_p, is_bullish, hover_y=y_pos)

    def _on_axis_dragged(self, dy):
        if not self.candles:
            return

        self.auto_scale = False
        min_p, max_p = self._get_active_range()
        span = max_p - min_p
        if span <= 0:
            return

        factor = 1.0 + (dy * 0.005)
        center = (min_p + max_p) / 2.0
        new_half_span = (span * factor) / 2.0

        self.manual_min_p = center - new_half_span
        self.manual_max_p = center + new_half_span
        self._recalculate_and_draw()

    def get_price_range(self):
        """Current visible (min_price, max_price) — lets other panels
        (e.g. the Volume Profile / VPVR) sync their own price axis to
        this chart's so price levels line up horizontally."""
        return self._get_active_range()

    def _get_visible_candles(self):
        """Returns only the candles currently within the canvas viewport,
        using the same pan/width math the canvas uses to paint them."""
        if not self.candles:
            return []

        cw = max(1.0, self.candle_width)
        canvas_w = max(self.canvas.width(), 100)

        start_i = max(0, int((-self.pan_offset_x) // cw) - 1)
        end_i = min(len(self.candles), start_i + int(canvas_w // cw) + 3)

        visible = self.candles[start_i:end_i]
        return visible if visible else self.candles

    def _get_active_range(self):
        if not self.auto_scale and self.manual_min_p is not None:
            return self.manual_min_p, self.manual_max_p

        visible_candles = self._get_visible_candles()

        valid_highs = [c.high for c in visible_candles if getattr(c, "high", None) is not None]
        valid_lows = [c.low for c in visible_candles if getattr(c, "low", None) is not None]

        # Footprint cluster rows are binned to the candle's tick size
        # (see core.candle_engine.round_price), which can round a row
        # UP above the candle's actual high or DOWN below its actual
        # low by up to half a tick. That mismatch — a footprint cell
        # sitting just outside the wick's own high/low — is exactly
        # what clipped cluster rows off the top of the canvas, so the
        # Y-range has to consider every footprint price level too, not
        # just the candle wick extremes.
        for c in visible_candles:
            footprint = getattr(c, "footprint", None)
            if footprint:
                valid_highs.append(max(footprint.keys()))
                valid_lows.append(min(footprint.keys()))

        # Active order overlays (Entry / Stop Loss / Take Profit lines,
        # e.g. the "SHORT ENTRY" tag) were never folded into the bounds
        # at all — a line/label sitting outside the visible candles'
        # own high/low (a stop placed well beyond the last few bars,
        # for instance) could get excluded from the range entirely, or
        # squeezed right up against the canvas edge with no headroom.
        for line in getattr(self.canvas, "position_lines", None) or []:
            for key in ("entry", "stop_loss", "take_profit"):
                p = line.get(key)
                if p is not None:
                    valid_highs.append(p)
                    valid_lows.append(p)

        if not valid_highs or not valid_lows:
            if self.current_price:
                return self.current_price * 0.99, self.current_price * 1.01
            return 0.0, 100.0

        min_p = min(valid_lows)
        max_p = max(valid_highs)

        # Defensive guard against the exact bug reported: the live tick
        # price sitting outside the visible candles' cached high/low
        # (e.g. a fast tick arriving between a candle update and this
        # redraw) — always fold the actual current price into bounds
        # before padding is applied, so the axis can never cap below it.
        if self.current_price:
            min_p = min(min_p, self.current_price)
            max_p = max(max_p, self.current_price)

        # Generous 8% top/bottom padding so wicks, footprint clusters
        # (including each row's own half-cell height, which extends a
        # bit further past the extreme price level), and order-line
        # labels are never tightly clipped against the canvas edge.
        padding = max((max_p - min_p) * 0.08, max_p * 0.008, 0.5)
        min_p -= padding
        max_p += padding

        # Fixed pixel-based reserves on top of the percentage padding
        # above — percentage padding alone shrinks to nothing on a
        # very tight price range, which is exactly when fixed-size
        # overlays (footprint row text, the Entry/SL/TP label pills)
        # are most likely to get clipped. price_to_y maps the highest
        # price to y=0 (top of canvas) and the lowest price to y=height
        # (bottom), so the top reserve extends max_p upward and the
        # bottom reserve extends min_p downward.
        canvas_h = max(self.canvas.height(), 1)
        span = max(max_p - min_p, 1e-9)
        price_per_px = span / canvas_h

        # Top: room for the topmost footprint row's own text/cell
        # extent and any order-line label pill sitting near the top.
        top_reserve_px = 22.0
        max_p += top_reserve_px * price_per_px

        # Bottom: the Delta/Volume summary card is drawn just below
        # each candle's low (FootprintCanvas.paintEvent: box_y =
        # y_low + 6, box_h = 28), plus room for an order-line label
        # pill sitting near the bottom.
        bottom_reserve_px = 40.0
        min_p -= bottom_reserve_px * price_per_px

        return min_p, max_p

    def _recalculate_and_draw(self):
        min_p, max_p = self._get_active_range()

        curr_p = self.current_price
        is_bullish = True
        if self.candles:
            if curr_p is None:
                curr_p = self.candles[-1].close
            is_bullish = self.candles[-1].close >= self.candles[-1].open

        self.canvas.set_candles(
            self.candles, min_p, max_p, self.is_log, self.candle_width, self.pan_offset_x, self.timeframe_sec
        )
        self.price_axis.set_range(min_p, max_p, self.is_log, curr_p, is_bullish)
        self.time_axis.set_params(self.candles, self.candle_width, self.pan_offset_x, self.timeframe_sec)


class ChartWidget(QWidget):
    """Outer Widget Container handling toolbar interactions and live candles."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self.timeframe_map = {
            "1M": 60,
            "5M": 300,
            "15M": 900,
            "1H": 3600,
            "4H": 14400,
            "1D": 86400,
        }
        self.current_tf_str = "15M"
        self.current_tf_sec = 900

        self.candle_manager = CandleManager(
            timeframe_seconds=self.current_tf_sec,
            tick_size=calculate_dynamic_tick_size(self.current_tf_sec),
        )

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._init_ui()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Toolbar Frame
        toolbar = QFrame()
        toolbar.setStyleSheet("background-color: #121318; border-bottom: 1px solid #1E222D;")
        tb_layout = QHBoxLayout(toolbar)
        tb_layout.setContentsMargins(8, 6, 8, 6)
        tb_layout.setSpacing(6)

        # TIMEFRAME Badge Label
        tf_label = QLabel("TIMEFRAME")
        tf_label.setStyleSheet(
            "color: #8F96A3; background-color: #1E222D; font-weight: bold; "
            "font-family: Consolas; font-size: 10px; padding: 3px 6px; border-radius: 2px;"
        )
        tb_layout.addWidget(tf_label)

        self.tf_buttons = {}
        for tf_str in ["1M", "5M", "15M", "1H", "4H", "1D"]:
            btn = QPushButton(tf_str)
            btn.setCheckable(True)
            btn.setFixedSize(36, 24)
            btn.setStyleSheet("""
                QPushButton {
                    background: #1E222D;
                    color: #B2B5BE;
                    border: none;
                    border-radius: 2px;
                    font-family: Consolas;
                    font-size: 11px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background: #2A2E39;
                    color: #FFFFFF;
                }
                QPushButton:checked {
                    background: #089981;
                    color: #FFFFFF;
                }
            """)
            btn.clicked.connect(lambda checked, tf=tf_str: self.on_timeframe_changed(tf))
            tb_layout.addWidget(btn)
            self.tf_buttons[tf_str] = btn

        self.tf_buttons[self.current_tf_str].setChecked(True)

        tb_layout.addSpacing(12)

        # Indicators Button
        indicators_btn = QPushButton("Indicators")
        indicators_btn.setFixedSize(85, 24)
        indicators_btn.setStyleSheet("""
            QPushButton {
                background: #1E222D;
                color: #089981;
                border: 1px solid #089981;
                border-radius: 2px;
                font-family: Consolas;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #089981;
                color: #FFFFFF;
            }
        """)
        tb_layout.addWidget(indicators_btn)

        tb_layout.addStretch()

        main_layout.addWidget(toolbar, 0)

        self.footprint_chart = FootprintChart()
        main_layout.addWidget(self.footprint_chart, 1)

    def on_timeframe_changed(self, tf_str):
        if tf_str not in self.timeframe_map:
            return

        self.current_tf_str = tf_str
        self.current_tf_sec = self.timeframe_map[tf_str]

        for button_tf, btn in self.tf_buttons.items():
            btn.setChecked(button_tf == tf_str)

        new_tick_size = calculate_dynamic_tick_size(self.current_tf_sec)
        self.candle_manager.set_timeframe(self.current_tf_sec, tick_size=new_tick_size)

        self.footprint_chart.change_timeframe(self.current_tf_sec)
        self.refresh_chart()

    def on_live_trade(self, price, size, side, timestamp=None):
        self.candle_manager.on_trade(price, size, side, timestamp)
        self.refresh_chart()

    def seed_historical_candles(self, ohlcv_rows):
        self.candle_manager.seed_history(ohlcv_rows)
        self.refresh_chart()

    def refresh_chart(self):
        candles = self.candle_manager.get_candles()
        self.footprint_chart.set_candles(candles, self.current_tf_sec)
