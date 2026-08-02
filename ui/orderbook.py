from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QStyledItemDelegate, QStyle
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPainter


SUM_ROLE = Qt.ItemDataRole.UserRole
SIDE_ROLE = Qt.ItemDataRole.UserRole + 1
MAX_SUM_ROLE = Qt.ItemDataRole.UserRole + 2


def _parse_level(entry):
    """
    Order book levels can arrive as either a dict ({"price":.., "size":..})
    or a [price, size] list/tuple, depending on the exchange payload.
    Handle both so the DOM never silently shows blank rows.
    """

    try:
        if isinstance(entry, dict):
            price = float(entry.get("price", entry.get("limit_price", 0)))
            size = float(entry.get("size", entry.get("quantity", 0)))
        else:
            price = float(entry[0])
            size = float(entry[1])

        return price, size

    except (TypeError, ValueError, IndexError, KeyError):
        return None, None


class DepthBarDelegate(QStyledItemDelegate):
    """Paints a proportional colored depth bar behind the Sum column,
    like a real DOM — width scales with cumulative size vs. the
    largest cumulative size currently visible on that side."""

    def paint(self, painter, option, index):

        cum_sum = index.data(SUM_ROLE)
        max_sum = index.data(MAX_SUM_ROLE)
        side = index.data(SIDE_ROLE)

        painter.save()

        # base cell background
        painter.fillRect(option.rect, QColor("#131722"))

        if cum_sum and max_sum and max_sum > 0:
            ratio = min(cum_sum / max_sum, 1.0)
            bar_width = int(option.rect.width() * ratio)

            color = QColor(46, 204, 113, 70) if side == "bid" else QColor(231, 76, 60, 70)

            bar_rect = option.rect
            bar_rect = bar_rect.adjusted(
                bar_rect.width() - bar_width, 0, 0, 0
            ) if side == "bid" else bar_rect.adjusted(0, 0, -(bar_rect.width() - bar_width), 0)

            painter.fillRect(bar_rect, color)

        painter.restore()

        super().paint(painter, option, index)


class OrderBook(QWidget):

    ROWS_PER_SIDE = 10

    def __init__(self):
        super().__init__()

        self.setMinimumWidth(260)

        self.setStyleSheet("""
        QWidget{
            background:#131722;
            border:1px solid #1E222D;
            border-radius:8px;
        }

        QLabel#title{
            color:#00FF88;
            font-size:15px;
            font-weight:bold;
            padding:10px;
        }

        QTableWidget{
            background:#131722;
            color:white;
            gridline-color:#1E222D;
            border:none;
            font-size:13px;
        }

        QHeaderView::section{
            background:#1a1d26;
            color:#999;
            padding:6px;
            border:none;
            font-weight:600;
            font-size:11px;
        }
        """)

        layout = QVBoxLayout(self)

        title = QLabel("📚 LIVE ORDER BOOK")
        title.setObjectName("title")

        layout.addWidget(title)

        self.table = QTableWidget()
        self.table.verticalHeader().setDefaultSectionSize(26)

        self.table.setColumnCount(3)

        self.table.setHorizontalHeaderLabels([
            "Price",
            "Size",
            "Sum"
        ])

        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )

        self.table.verticalHeader().setVisible(False)

        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        self.table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )

        self.table.setItemDelegateForColumn(2, DepthBarDelegate(self.table))

        layout.addWidget(self.table)

        self._last_shown_price = None

        self.update_orderbook([], [])

    def _make_item(self, text, side=None, cum_sum=None, max_sum=None, color=None):

        item = QTableWidgetItem(text)
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        if color:
            item.setForeground(color)

        if side:
            item.setData(SIDE_ROLE, side)
            item.setData(SUM_ROLE, cum_sum)
            item.setData(MAX_SUM_ROLE, max_sum)

        return item

    def update_orderbook(self, bids, asks, last_price=None):

        n = self.ROWS_PER_SIDE

        # --- parse + sort ---
        parsed_bids = sorted(
            (lvl for lvl in (_parse_level(b) for b in bids) if lvl[0] is not None),
            key=lambda x: x[0], reverse=True
        )[:n]

        parsed_asks = sorted(
            (lvl for lvl in (_parse_level(a) for a in asks) if lvl[0] is not None),
            key=lambda x: x[0]
        )[:n]

        # asks displayed highest-to-lowest (best ask sits just above the spread)
        parsed_asks = list(reversed(parsed_asks))

        # --- cumulative sums, best price outward ---
        ask_cum = []
        running = 0.0
        for price, size in reversed(parsed_asks):  # best ask first for accumulation
            running += size
            ask_cum.append(running)
        ask_cum = list(reversed(ask_cum))
        max_ask_sum = max(ask_cum) if ask_cum else 0

        bid_cum = []
        running = 0.0
        for price, size in parsed_bids:  # best bid first for accumulation
            running += size
            bid_cum.append(running)
        max_bid_sum = max(bid_cum) if bid_cum else 0

        red = QColor("#e74c3c")
        green = QColor("#2ecc71")

        show_mid_row = last_price is not None
        total_rows = len(parsed_asks) + len(parsed_bids) + (1 if show_mid_row else 0)
        self.table.setRowCount(total_rows)

        row = 0

        for i, (price, size) in enumerate(parsed_asks):
            self.table.setItem(row, 0, self._make_item(f"{price:,.1f}", color=red))
            self.table.setItem(row, 1, self._make_item(f"{size:,.3f}"))
            self.table.setItem(row, 2, self._make_item(
                f"{ask_cum[i]:,.3f}", side="ask", cum_sum=ask_cum[i], max_sum=max_ask_sum
            ))
            row += 1

        if show_mid_row:
            try:
                last_price = float(last_price)
            except (TypeError, ValueError):
                last_price = None

        if show_mid_row and last_price is not None:

            if self._last_shown_price is None or last_price == self._last_shown_price:
                arrow, price_color = "", "white"
            elif last_price > self._last_shown_price:
                arrow, price_color = "▲", "#2ecc71"
            else:
                arrow, price_color = "▼", "#e74c3c"

            mid_item = self._make_item(
                f"{last_price:,.1f} {arrow}".strip(), color=QColor(price_color)
            )
            font = mid_item.font()
            font.setPointSize(font.pointSize() + 3)
            font.setBold(True)
            mid_item.setFont(font)

            self.table.setItem(row, 0, mid_item)
            self.table.setItem(row, 1, QTableWidgetItem(""))
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self.table.setSpan(row, 0, 1, 3)
            self.table.setRowHeight(row, 34)

            self._last_shown_price = last_price
            row += 1

        for i, (price, size) in enumerate(parsed_bids):
            self.table.setItem(row, 0, self._make_item(f"{price:,.1f}", color=green))
            self.table.setItem(row, 1, self._make_item(f"{size:,.3f}"))
            self.table.setItem(row, 2, self._make_item(
                f"{bid_cum[i]:,.3f}", side="bid", cum_sum=bid_cum[i], max_sum=max_bid_sum
            ))
            row += 1
