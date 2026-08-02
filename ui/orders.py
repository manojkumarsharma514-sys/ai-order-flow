from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor

COLUMNS = [
    "Order ID", "Opened", "Closed", "Symbol", "Side", "Qty",
    "Entry", "Exit", "PnL ($)", "PnL (%)", "Total Fee ($)", "Status", "Source", "Close Reason",
]


class OrdersPanel(QWidget):
    """ORDERS tab — all completed / historical orders, loaded from and
    always in sync with data/orders_history.csv."""

    def __init__(self):
        super().__init__()

        self.setStyleSheet("""
        QWidget{ background:#131722; }
        QLabel#title{ color:#00FF88; font-size:15px; font-weight:bold; }
        QTableWidget{
            background:#131722; color:white; gridline-color:#232323;
            border:1px solid #1E222D; font-size:12px;
        }
        QHeaderView::section{
            background:#2b2b2b; color:white; padding:6px; border:none; font-weight:bold;
        }
        QPushButton{
            background:#1a5cff; color:white; border-radius:4px; padding:6px 14px; font-weight:bold;
        }
        """)

        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()
        title = QLabel("📄 ORDERS — History")
        title.setObjectName("title")
        header_row.addWidget(title)
        header_row.addStretch()

        self.refresh_btn = QPushButton("Refresh")
        header_row.addWidget(self.refresh_btn)
        layout.addLayout(header_row)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)

    def set_records(self, records: list):
        """records: list[dict] as produced by OrdersManager.load_records()"""

        self.table.setRowCount(len(records))

        for row, r in enumerate(records):
            pnl = r.get("pnl_usd") or 0
            try:
                pnl = float(pnl)
            except (TypeError, ValueError):
                pnl = 0.0
            color = QColor("#2ecc71") if pnl >= 0 else QColor("#e74c3c")
            side_color = QColor("#2ecc71") if r.get("side") == "LONG" else QColor("#e74c3c")

            fee = r.get("total_fee") or 0
            try:
                fee = float(fee)
            except (TypeError, ValueError):
                fee = 0.0

            values = [
                r.get("order_id"), r.get("opened_at"), r.get("closed_at"),
                r.get("symbol"), r.get("side"), r.get("qty"),
                r.get("entry_price"), r.get("exit_price"),
                f"{pnl:,.2f}", r.get("pnl_pct"), f"{fee:,.2f}", r.get("status"),
                r.get("source"), r.get("close_reason"),
            ]

            for col, val in enumerate(values):
                item = QTableWidgetItem("" if val is None else str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 4:
                    item.setForeground(side_color)
                if col in (8, 9):
                    item.setForeground(color)
                if col == 10:
                    item.setForeground(QColor("#e67e22"))  # fee: neutral orange, always a cost
                self.table.setItem(row, col, item)
