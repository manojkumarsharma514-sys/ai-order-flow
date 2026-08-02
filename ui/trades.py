from PyQt6.QtWidgets import QWidget
from PyQt6.QtWidgets import QVBoxLayout
from PyQt6.QtWidgets import QLabel
from PyQt6.QtWidgets import QTableWidget
from PyQt6.QtWidgets import QTableWidgetItem
from PyQt6.QtWidgets import QHeaderView
from PyQt6.QtCore import Qt
from datetime import datetime


class RecentTrades(QWidget):

    def __init__(self):
        super().__init__()

        self.setMinimumWidth(350)

        self.setStyleSheet("""
        QWidget{
            background:#131722;
            border:1px solid #1E222D;
            border-radius:8px;
        }

        QLabel{
            color:#00FF88;
            font-size:15px;
            font-weight:bold;
            padding:10px;
        }

        QTableWidget{
            background:#131722;
            color:white;
            border:none;
            gridline-color:#333;
            font-size:13px;
        }

        QHeaderView::section{
            background:#2b2b2b;
            color:white;
            border:none;
            padding:6px;
            font-weight:bold;
        }
        """)

        layout = QVBoxLayout(self)

        title = QLabel("📊 RECENT TRADES")

        layout.addWidget(title)

        self.table = QTableWidget()

        self.table.setColumnCount(4)

        self.table.setHorizontalHeaderLabels([
            "Time",
            "Side",
            "Price",
            "Qty"
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

        layout.addWidget(self.table)

        self.max_rows = 100

    def add_trade(self, side, price, qty):

        row = 0

        self.table.insertRow(row)

        if self.table.rowCount() > self.max_rows:
            self.table.removeRow(self.max_rows)

        current_time = datetime.now().strftime("%H:%M:%S")

        time_item = QTableWidgetItem(current_time)
        side_item = QTableWidgetItem(side)
        price_item = QTableWidgetItem(str(price))
        qty_item = QTableWidgetItem(str(qty))

        time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        side_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

        if side.upper() == "BUY":
            side_item.setForeground(Qt.GlobalColor.green)
        else:
            side_item.setForeground(Qt.GlobalColor.red)

        self.table.setItem(row, 0, time_item)
        self.table.setItem(row, 1, side_item)
        self.table.setItem(row, 2, price_item)
        self.table.setItem(row, 3, qty_item)