from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QPushButton, QSizePolicy,
    QDialog, QFormLayout, QDoubleSpinBox, QDialogButtonBox
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont

# Explicit pixel widths per column — NOT QHeaderView.Stretch. Stretch
# mode recomputes every column's width off the table's current total
# width on every single repaint, so as soon as any cell's *text*
# changes (a PnL flipping between "-35.50 USDT" and "17.50 USDT" is a
# different string width), Qt was re-running that layout pass and the
# whole panel visibly flexed/shifted horizontally. Fixed pixel widths
# make column geometry independent of cell content entirely.
COLUMN_WIDTHS = {
    "Symbol": 90,
    "Side": 70,
    "Size": 70,
    "Entry": 95,
    "Mark": 95,
    "Stop Loss": 95,
    "Take Profit": 95,
    "PnL ($)": 100,
    "PnL (%)": 85,
    "Edit": 90,     # per-row Edit SL/TP button column
    "": 80,         # per-row Close button column (dedicated tab only)
}

# Fixed-width, monospace-ish numeric font so digit-count changes (e.g.
# "9.50" -> "17.50") don't change a cell's *rendered* width either —
# QTableWidget cell width is fixed already, but a proportional font
# rendering a wider string could still visually crowd/re-elide.
_NUMERIC_FONT = QFont("Consolas", 10)


class EditSLTPDialog(QDialog):
    """Small pop-up letting the trader change Stop Loss / Take Profit
    on an already-open position — the chart's SL/TP lines and the
    Positions table were previously read-only once a trade was placed,
    with no way to move a stop or target after entry. Prefilled with
    the position's current values; Save emits back to the panel, which
    re-emits sl_tp_updated for the controller to apply."""

    def __init__(self, position, parent=None):
        super().__init__(parent)
        self.position = position

        self.setWindowTitle(f"Edit SL/TP — {position.symbol} {position.side} #{position.id}")
        self.setStyleSheet("""
            QDialog{ background:#131722; }
            QLabel{ color:#c7cbd6; font-size:12px; }
            QDoubleSpinBox{
                background:#0b0e14; color:#ffffff; border:1px solid #232936;
                border-radius:4px; padding:4px 6px; font-size:13px; font-weight:bold;
            }
        """)

        layout = QVBoxLayout(self)

        info = QLabel(
            f"Entry: {position.entry_price:,.1f}   Mark: {position.mark_price:,.1f}   "
            f"({'LONG' if position.side == 'LONG' else 'SHORT'})"
        )
        info.setStyleSheet("QLabel{color:#7b8191; font-size:11px;}")
        layout.addWidget(info)

        form = QFormLayout()

        self.sl_spin = QDoubleSpinBox()
        self.sl_spin.setRange(0, 100_000_000)
        self.sl_spin.setDecimals(1)
        self.sl_spin.setSingleStep(0.5)
        self.sl_spin.setValue(position.stop_loss or 0.0)
        form.addRow("Stop Loss", self.sl_spin)

        self.tp_spin = QDoubleSpinBox()
        self.tp_spin.setRange(0, 100_000_000)
        self.tp_spin.setDecimals(1)
        self.tp_spin.setSingleStep(0.5)
        self.tp_spin.setValue(position.take_profit or 0.0)
        form.addRow("Take Profit", self.tp_spin)

        layout.addLayout(form)

        hint = QLabel(
            "Leave a field at 0 to remove that protection entirely — "
            "a position with Stop Loss at 0 has NO stop and unbounded downside."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("QLabel{color:#e67e22; font-size:10px;}")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def resolved_values(self):
        """Returns (stop_loss, take_profit) as floats or None (0 ->
        None, i.e. "no stop"/"no target"), ready to hand to
        PaperTradingEngine.modify_position_sl_tp()."""
        sl = self.sl_spin.value()
        tp = self.tp_spin.value()
        return (sl if sl > 0 else None), (tp if tp > 0 else None)


class PositionsPanel(QWidget):

    close_all_clicked = pyqtSignal()
    reset_clicked = pyqtSignal()
    close_position_clicked = pyqtSignal(int)  # position.id
    # (position_id, new_stop_loss_or_None, new_take_profit_or_None) —
    # None means "clear this field", not "leave unchanged": the dialog
    # always sends both current values, edited or not.
    sl_tp_updated = pyqtSignal(int, object, object)

    def __init__(self, show_close_column: bool = False):
        super().__init__()

        # The compact Dashboard-tab panel (default) keeps its original
        # 7-column layout. The dedicated POSITIONS tab instantiates
        # this with show_close_column=True to add a manual per-row
        # "Close Position" button, per spec section 4. The "Edit"
        # SL/TP button is available on BOTH — adjusting risk on an open
        # trade shouldn't require switching tabs.
        self.show_close_column = show_close_column

        # Lock this panel's own footprint in the bottom row so a PnL
        # update can't ripple into the Recent Trades / Trade Setup
        # panels next to it either.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

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
        }

        QTableWidget{
            background:#131722;
            color:white;
            gridline-color:#232323;
            border:none;
            font-size:12px;
        }

        QHeaderView::section{
            background:#2b2b2b;
            color:white;
            padding:6px;
            border:none;
            font-weight:bold;
        }

        QPushButton{
            background:#c0392b;
            color:white;
            border-radius:4px;
            padding:4px 10px;
            font-weight:bold;
        }
        """)

        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()

        title = QLabel("💼 POSITIONS (Paper)")
        title.setObjectName("title")
        self.title_label = title
        header_row.addWidget(title)

        # Active execution mode ("paper" | "demo" | "live") — drives
        # both the title text above and RESET BALANCE visibility below.
        self._account_mode = "paper"

        header_row.addStretch()

        self.total_pnl_label = QLabel("Total P&L : 0.00 USDT")
        # Fixed width + right alignment: the string's own width no
        # longer shifts the CLOSE ALL / RESET BALANCE buttons next to
        # it as the digits/sign change.
        self.total_pnl_label.setMinimumWidth(170)
        self.total_pnl_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.total_pnl_label.setFont(_NUMERIC_FONT)
        header_row.addWidget(self.total_pnl_label)

        self.close_all_btn = QPushButton("CLOSE ALL")
        self.close_all_btn.clicked.connect(self.close_all_clicked.emit)
        header_row.addWidget(self.close_all_btn)

        self.reset_btn = QPushButton("RESET BALANCE")
        self.reset_btn.setStyleSheet("background:#555;")
        self.reset_btn.clicked.connect(self.reset_clicked.emit)
        header_row.addWidget(self.reset_btn)

        layout.addLayout(header_row)

        self.table = QTableWidget()

        self.columns = ["Symbol", "Side", "Size", "Entry", "Mark",
                         "Stop Loss", "Take Profit", "PnL ($)", "PnL (%)", "Edit"]
        if self.show_close_column:
            self.columns = self.columns + [""]  # per-row Close Position button

        self.table.setColumnCount(len(self.columns))
        self.table.setHorizontalHeaderLabels(self.columns)

        # Interactive + explicit setColumnWidth (not Stretch): widths
        # are set once, up front, and never recomputed off cell text —
        # the user can still manually drag a column wider if they want.
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        for i, col_name in enumerate(self.columns):
            self.table.setColumnWidth(i, COLUMN_WIDTHS.get(col_name, 90))
        header.setStretchLastSection(False)

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(22)

        self.table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )

        self.table.setSelectionMode(
            QTableWidget.SelectionMode.NoSelection
        )

        # Table itself doesn't grow/shrink the panel around it — its
        # own scrollbars handle overflow instead of the panel resizing.
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout.addWidget(self.table)

        # Keep a live reference to the position objects currently
        # rendered, keyed by id, so the Edit button's click handler can
        # look up fresh entry/mark/side/current-SL-TP at click time
        # instead of capturing possibly-stale values from whenever the
        # row was drawn.
        self._positions_by_id = {}

    def set_account_mode(self, mode):
        """mode: "paper" | "demo" | "live" — updates the panel title
        ("POSITIONS (Paper/Demo/Live)") and hides RESET BALANCE
        entirely on Live so it can never be clicked against a real
        connected account (it stays visible for Paper/Demo)."""

        mode = (mode or "paper").lower()
        self._account_mode = mode

        label = {"paper": "Paper", "demo": "Demo", "live": "Live"}.get(mode, "Paper")
        self.title_label.setText(f"💼 POSITIONS ({label})")

        if mode == "live":
            self.reset_btn.setVisible(False)   # Completely hide for Live trading
        else:
            self.reset_btn.setVisible(True)    # Keep visible for Paper / Demo modes

    def update_positions(self, positions, total_pnl):

        self._positions_by_id = {p.id: p for p in positions}

        self.table.setRowCount(len(positions))

        pnl_color = "#2ecc71" if total_pnl >= 0 else "#e74c3c"
        self.total_pnl_label.setText(f"Total P&L : {total_pnl:,.2f} USDT")
        self.total_pnl_label.setStyleSheet(f"color:{pnl_color}; font-weight:bold; font-size:13px;")

        edit_col_index = self.columns.index("Edit")
        close_col_index = len(self.columns) - 1  # only meaningful if show_close_column

        for row, p in enumerate(positions):

            pnl = p.unrealized_pnl()
            pnl_pct = p.unrealized_pnl_pct()

            color = QColor("#2ecc71") if pnl >= 0 else QColor("#e74c3c")
            side_color = QColor("#2ecc71") if p.side == "LONG" else QColor("#e74c3c")

            sl_text = f"{p.stop_loss:,.1f}" if p.stop_loss else "—"
            tp_text = f"{p.take_profit:,.1f}" if p.take_profit else "—"

            values = [
                p.symbol,
                p.side,
                f"{p.size:g}",
                f"{p.entry_price:,.1f}",
                f"{p.mark_price:,.1f}",
                sl_text,
                tp_text,
                f"{pnl:,.2f}",
                f"{pnl_pct:,.2f}%",
            ]

            for col, val in enumerate(values):

                item = QTableWidgetItem(val)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                item.setFont(_NUMERIC_FONT)

                if col == 1:
                    item.setForeground(side_color)
                elif col == 5:
                    item.setForeground(QColor("#e74c3c") if p.stop_loss else QColor("#5b6272"))
                elif col == 6:
                    item.setForeground(QColor("#2ecc71") if p.take_profit else QColor("#5b6272"))
                elif col in (7, 8):
                    item.setForeground(color)

                self.table.setItem(row, col, item)

            edit_btn = QPushButton("✏ Edit")
            edit_btn.setStyleSheet(
                "background:#1a5cff; color:white; border-radius:4px; padding:2px 8px;"
            )
            edit_btn.clicked.connect(
                lambda _checked, pid=p.id: self._open_edit_dialog(pid)
            )
            self.table.setCellWidget(row, edit_col_index, edit_btn)

            if self.show_close_column:
                close_btn = QPushButton("Close")
                close_btn.setStyleSheet(
                    "background:#c0392b; color:white; border-radius:4px; padding:2px 8px;"
                )
                close_btn.clicked.connect(
                    lambda _checked, pid=p.id: self.close_position_clicked.emit(pid)
                )
                self.table.setCellWidget(row, close_col_index, close_btn)

    def _open_edit_dialog(self, position_id):
        """'✏ Edit' button clicked for a given row. Looks the position
        up fresh (rather than trusting whatever was captured at row-
        draw time) since mark price / even the position's continued
        existence can change between a repaint and a click — a
        position that hit its SL/TP and closed in that window simply
        has no dialog to open, rather than editing a stale snapshot."""

        position = self._positions_by_id.get(position_id)
        if position is None:
            return  # closed (e.g. hit SL/TP) between last repaint and this click

        dialog = EditSLTPDialog(position, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            new_sl, new_tp = dialog.resolved_values()
            self.sl_tp_updated.emit(position_id, new_sl, new_tp)
