from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QLineEdit,
    QDialog, QTextBrowser, QTextEdit, QFileDialog
)
from PyQt6.QtCore import Qt, pyqtSignal, QUrl
from PyQt6.QtGui import QColor, QDesktopServices

COLUMNS = [
    "Trade ID", "Date/Time", "Symbol", "Side", "Qty", "Entry", "Exit",
    "PnL ($)", "PnL (%)", "Strategy", "AI Score", "Report",
]

REPORT_COL = len(COLUMNS) - 1
TRADE_ID_COL = 0


class TradeReportDialog(QDialog):
    """Pop-up modal opened by the Journal tab's '📄 View Report' button.
    Renders the trade's full structured record as styled HTML (the same
    HTML written to data/reports/trade_<id>.html), plus an editable
    Notes box that saves back to trade_journal.csv."""

    notes_saved = pyqtSignal(object, str)  # (trade_id, new_notes)

    def __init__(self, trade_id, html: str, notes: str, report_path: str = "", parent=None):
        super().__init__(parent)
        self.trade_id = trade_id
        self.report_path = report_path

        self.setWindowTitle(f"Trade Report — #{trade_id}")
        self.resize(560, 640)
        self.setStyleSheet("QDialog{ background:#0b0e14; }")

        layout = QVBoxLayout(self)

        self.browser = QTextBrowser()
        self.browser.setHtml(html)
        self.browser.setStyleSheet("background:#0b0e14; border:none;")
        layout.addWidget(self.browser)

        notes_label = QLabel("Notes")
        notes_label.setStyleSheet("color:#00FF88; font-weight:bold; font-size:12px;")
        layout.addWidget(notes_label)

        self.notes_edit = QTextEdit()
        self.notes_edit.setPlainText(str(notes) if notes else "")
        self.notes_edit.setFixedHeight(80)
        self.notes_edit.setStyleSheet(
            "background:#131722; color:#e1e4ea; border:1px solid #1E222D; border-radius:6px; padding:6px;"
        )
        layout.addWidget(self.notes_edit)

        btn_row = QHBoxLayout()

        self.open_file_btn = QPushButton("📂 Open HTML File")
        self.open_file_btn.clicked.connect(self._open_file)
        btn_row.addWidget(self.open_file_btn)

        btn_row.addStretch()

        self.save_btn = QPushButton("💾 Save Notes")
        self.save_btn.setStyleSheet(
            "background:#00C853; color:#04140a; border-radius:4px; padding:6px 14px; font-weight:bold;"
        )
        self.save_btn.clicked.connect(self._save_notes)
        btn_row.addWidget(self.save_btn)

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)

        layout.addLayout(btn_row)

    def _open_file(self):
        if self.report_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.report_path))

    def _save_notes(self):
        self.notes_saved.emit(self.trade_id, self.notes_edit.toPlainText())
        self.save_btn.setText("✓ Saved")


class JournalPanel(QWidget):
    """JOURNAL tab — filterable trade history read from
    data/trade_journal.csv. Each row's structured market context
    (Trend, VWAP, Delta, CVD, Volume, Liquidity, Psychology Score, AI
    Score) lives behind a '📄 View Report' button in the Report column
    rather than being crammed into the table itself."""

    notes_edited = pyqtSignal(object, str)  # (trade_id, new_notes)
    view_report_clicked = pyqtSignal(object)  # trade_id

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
        QLineEdit{
            background:#0b0e14; color:white; border:1px solid #232936;
            border-radius:4px; padding:4px;
        }
        QPushButton#report_btn{
            background:#1a5cff; color:white; border-radius:4px; padding:4px 10px; font-weight:bold;
        }
        QPushButton#report_btn:hover{ background:#3b75ff; }
        """)

        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()
        title = QLabel("📓 JOURNAL")
        title.setObjectName("title")
        header_row.addWidget(title)
        header_row.addStretch()

        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filter by symbol or side…")
        self.filter_box.setFixedWidth(220)
        self.filter_box.textChanged.connect(self._apply_filter)
        header_row.addWidget(self.filter_box)

        layout.addLayout(header_row)

        self.table = QTableWidget()
        self.table.setColumnCount(len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)

        layout.addWidget(self.table)

        self._records = []
        # keyed by trade_id -> record dict, so the Report button's
        # click handler doesn't need to re-scan self._records
        self._records_by_id = {}

    def set_records(self, records: list):
        self._records = records
        self._records_by_id = {r.get("trade_id"): r for r in records}
        self._render(records)

    def _render(self, records):
        self.table.setRowCount(len(records))

        for row, r in enumerate(records):
            pnl = r.get("pnl_usd") or 0
            try:
                pnl = float(pnl)
            except (TypeError, ValueError):
                pnl = 0.0
            color = QColor("#2ecc71") if pnl >= 0 else QColor("#e74c3c")
            side_color = QColor("#2ecc71") if r.get("side") == "LONG" else QColor("#e74c3c")

            ai_score = r.get("ai_confidence")
            ai_score_text = f"{ai_score}%" if ai_score not in (None, "", "nan") else "—"

            values = [
                r.get("trade_id"), r.get("date_time"), r.get("symbol"), r.get("side"),
                r.get("qty"), r.get("entry_price"), r.get("exit_price"),
                f"{pnl:,.2f}", r.get("pnl_percent"), r.get("strategy_used"),
                ai_score_text,
            ]

            for col, val in enumerate(values):
                item = QTableWidgetItem("" if val is None else str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if col == 3:
                    item.setForeground(side_color)
                if col in (7, 8):
                    item.setForeground(color)
                self.table.setItem(row, col, item)

            report_btn = QPushButton("📄 View Report")
            report_btn.setObjectName("report_btn")
            trade_id = r.get("trade_id")
            report_btn.clicked.connect(
                lambda _checked, tid=trade_id: self.view_report_clicked.emit(tid)
            )
            self.table.setCellWidget(row, REPORT_COL, report_btn)

    def get_record(self, trade_id) -> dict:
        return self._records_by_id.get(trade_id, {})

    def _apply_filter(self, text):
        text = text.strip().lower()
        if not text:
            filtered = self._records
        else:
            filtered = [
                r for r in self._records
                if text in str(r.get("symbol", "")).lower()
                or text in str(r.get("side", "")).lower()
            ]
        self._render(filtered)
