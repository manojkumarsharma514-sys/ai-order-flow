import calendar as _calendar_module
from datetime import date

from PyQt6.QtWidgets import (
    QWidget, QGridLayout, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
)
from PyQt6.QtCore import Qt, pyqtSignal, QPointF
from PyQt6.QtGui import QPainter, QColor, QPen

from ui.gauge import CircularGauge


class _StatCard(QFrame):
    """Small 'label on top, value below' card — same visual language
    as the rest of the dashboard's panels."""

    def __init__(self, title):
        super().__init__()
        self.setStyleSheet("""
        QFrame{ background:#131722; border:1px solid #1E222D; border-radius:8px; }
        QLabel#label{ color:#7b8191; font-size:11px; font-weight:bold; }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self.label = QLabel(title)
        self.label.setObjectName("label")
        layout.addWidget(self.label)

        self.value = QLabel("--")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value.setWordWrap(True)
        self.value.setTextFormat(Qt.TextFormat.RichText)
        self.value.setStyleSheet("QLabel{color:#e1e4ea; font-size:18px; font-weight:bold;}")
        layout.addWidget(self.value)

        layout.addStretch()

    def set_value(self, text, color=None):
        self.value.setText(str(text))
        text_color = color or "#e1e4ea"
        self.value.setStyleSheet(f"QLabel{{color:{text_color}; font-size:18px; font-weight:bold;}}")

    def set_value_html(self, html):
        """For cards that need two differently-colored lines (e.g. Avg
        Win/Loss Trade) — QLabel rich text, styling comes from the
        inline <span> tags in `html` itself."""
        self.value.setText(html)
        self.value.setStyleSheet("QLabel{font-size:14px; font-weight:bold;}")


class _Sparkline(QWidget):
    """Minimal equity-curve line chart — no axes/labels, just the
    shape, matching the small inline sparkline next to Net P&L."""

    def __init__(self, height=30):
        super().__init__()
        self.setFixedHeight(height)
        self._values = []

    def set_values(self, values):
        self._values = [float(v) for v in values] if values else []
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if len(self._values) < 2:
            painter.end()
            return

        w = self.width()
        h = self.height()

        lo = min(self._values)
        hi = max(self._values)
        span = max(hi - lo, 1e-9)

        color = QColor("#2ecc71") if self._values[-1] >= self._values[0] else QColor("#e74c3c")

        n = len(self._values)
        points = []
        for i, v in enumerate(self._values):
            x = (i / (n - 1)) * (w - 4) + 2
            y = h - 2 - ((v - lo) / span) * (h - 4)
            points.append(QPointF(x, y))

        painter.setPen(QPen(color, 1.6))
        for i in range(len(points) - 1):
            painter.drawLine(points[i], points[i + 1])

        painter.end()


class _NetPnlCard(_StatCard):
    """Same as _StatCard, plus an inline equity-curve sparkline under
    the $ value."""

    def __init__(self, title):
        super().__init__(title)
        self.sparkline = _Sparkline(height=28)
        # index 2 = right after the value label, before the trailing stretch
        self.layout().insertWidget(2, self.sparkline)

    def set_pnl(self, net_pnl, equity_curve):
        color = "#2ecc71" if net_pnl >= 0 else "#e74c3c"
        self.set_value(f"{'+' if net_pnl >= 0 else ''}${net_pnl:,.2f}", color=color)
        self.sparkline.set_values(equity_curve)


class PnLCalendar(QWidget):
    """Month-view P&L calendar: one cell per day (net $ + trade count,
    colored green/red/neutral), plus a trailing 'Weekly' rollup column.
    Navigation only changes what's on screen — DashboardController is
    responsible for actually fetching the new month's data and calling
    set_data() back (see calendar_month_requested)."""

    month_changed = pyqtSignal(int, int)  # (year, month) the user navigated TO

    DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
        QWidget{ background:#131722; border:1px solid #1E222D; border-radius:8px; }
        QLabel#title{ color:#00FF88; font-size:14px; font-weight:bold; }
        QLabel#nav_label{ color:#e1e4ea; font-size:12px; font-weight:bold; }
        QPushButton#nav_btn{
            background:#1a1f2c; color:#c7cbd6; border:none; border-radius:4px;
            padding:4px 12px; font-weight:bold; font-size:13px;
        }
        QPushButton#nav_btn:hover{ background:#252c3d; color:white; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("📅 P&L CALENDAR")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        self.prev_btn = QPushButton("‹")
        self.prev_btn.setObjectName("nav_btn")
        self.prev_btn.clicked.connect(self._go_prev)
        header.addWidget(self.prev_btn)

        self.month_label = QLabel("")
        self.month_label.setObjectName("nav_label")
        self.month_label.setMinimumWidth(120)
        self.month_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.month_label)

        self.next_btn = QPushButton("›")
        self.next_btn.setObjectName("nav_btn")
        self.next_btn.clicked.connect(self._go_next)
        header.addWidget(self.next_btn)

        outer.addLayout(header)

        self.grid = QGridLayout()
        self.grid.setSpacing(4)
        outer.addLayout(self.grid)
        outer.addStretch()

        today = date.today()
        self._year = today.year
        self._month = today.month
        self._data = {}

        self._build_day_headers()
        self._render()

    def _build_day_headers(self):
        for col, text in enumerate(self.DAY_LABELS + ["Weekly"]):
            lbl = QLabel(text.upper())
            lbl.setStyleSheet("QLabel{color:#7b8191; font-size:10px; font-weight:bold; border:none; background:transparent;}")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.grid.addWidget(lbl, 0, col)

    def _go_prev(self):
        month, year = self._month - 1, self._year
        if month < 1:
            month, year = 12, year - 1
        self.month_changed.emit(year, month)

    def _go_next(self):
        month, year = self._month + 1, self._year
        if month > 12:
            month, year = 1, year + 1
        self.month_changed.emit(year, month)

    def set_data(self, year: int, month: int, data: dict):
        """data: {day_of_month:int -> {"pnl": float, "count": int}}"""
        self._year = year
        self._month = month
        self._data = data or {}
        self._render()

    def _clear_day_cells(self):
        # Row 0 is the day-name header — leave it, remove everything else.
        for i in reversed(range(self.grid.count())):
            item = self.grid.itemAt(i)
            widget = item.widget() if item else None
            if widget is None:
                continue
            row, _col, _rspan, _cspan = self.grid.getItemPosition(i)
            if row > 0:
                widget.setParent(None)

    def _render(self):
        self._clear_day_cells()

        self.month_label.setText(date(self._year, self._month, 1).strftime("%B %Y"))

        first_weekday_monday0 = date(self._year, self._month, 1).weekday()  # Mon=0..Sun=6
        first_weekday_sunday0 = (first_weekday_monday0 + 1) % 7               # Sun=0..Sat=6
        days_in_month = _calendar_module.monthrange(self._year, self._month)[1]

        row, col = 1, first_weekday_sunday0
        week_pnl, week_count = 0.0, 0

        for day in range(1, days_in_month + 1):
            info = self._data.get(day)
            pnl = info["pnl"] if info else 0.0
            count = info["count"] if info else 0

            self.grid.addWidget(self._make_day_cell(day, pnl, count), row, col)
            week_pnl += pnl
            week_count += count

            col += 1
            if col == 7:
                self.grid.addWidget(self._make_week_cell(week_pnl, week_count), row, 7)
                week_pnl, week_count = 0.0, 0
                col = 0
                row += 1

        if col != 0:
            # Trailing partial week still gets its own weekly total.
            self.grid.addWidget(self._make_week_cell(week_pnl, week_count), row, 7)

    def _cell_colors(self, pnl, count):
        if count > 0 and pnl > 0:
            return "#0f2e1f", "#1f6b43"
        if count > 0 and pnl < 0:
            return "#331414", "#7a2b2b"
        return "#161a24", "#1E222D"

    def _make_day_cell(self, day, pnl, count):
        bg, border = self._cell_colors(pnl, count)

        cell = QFrame()
        cell.setStyleSheet(f"QFrame{{background:{bg}; border:1px solid {border}; border-radius:6px;}}")
        cell.setMinimumSize(68, 54)

        layout = QVBoxLayout(cell)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        day_label = QLabel(str(day))
        day_label.setStyleSheet("QLabel{color:#7b8191; font-size:10px; font-weight:bold; border:none; background:transparent;}")
        layout.addWidget(day_label)

        if count > 0:
            pnl_color = "#2ecc71" if pnl >= 0 else "#e74c3c"
            pnl_label = QLabel(f"{'+' if pnl >= 0 else ''}${pnl:,.0f}")
            pnl_label.setStyleSheet(f"QLabel{{color:{pnl_color}; font-size:12px; font-weight:bold; border:none; background:transparent;}}")
            layout.addWidget(pnl_label)

            count_label = QLabel(f"{count} trade{'s' if count != 1 else ''}")
            count_label.setStyleSheet("QLabel{color:#5b6272; font-size:9px; border:none; background:transparent;}")
            layout.addWidget(count_label)
        else:
            layout.addStretch()

        return cell

    def _make_week_cell(self, pnl, count):
        bg, border = self._cell_colors(pnl, count)

        cell = QFrame()
        cell.setStyleSheet(f"QFrame{{background:{bg}; border:1px solid {border}; border-radius:6px;}}")
        cell.setMinimumSize(68, 54)

        layout = QVBoxLayout(cell)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(1)

        pnl_color = "#2ecc71" if pnl >= 0 else "#e74c3c"
        pnl_label = QLabel(f"{'+' if pnl >= 0 else ''}${pnl:,.2f}" if count else "$0.00")
        pnl_label.setStyleSheet(f"QLabel{{color:{pnl_color}; font-size:12px; font-weight:bold; border:none; background:transparent;}}")
        layout.addWidget(pnl_label)

        count_label = QLabel(f"{count} trade{'s' if count != 1 else ''}")
        count_label.setStyleSheet("QLabel{color:#5b6272; font-size:9px; border:none; background:transparent;}")
        layout.addWidget(count_label)

        return cell


class TradesTable(QWidget):
    """Recent (closed) trades / Open Positions toggle + table."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("""
        QWidget{ background:#131722; border:1px solid #1E222D; border-radius:8px; }
        QLabel#title{ color:#00FF88; font-size:14px; font-weight:bold; }
        QPushButton#toggle_btn{
            background:transparent; color:#7b8191; border:none; border-radius:4px;
            padding:5px 12px; font-size:11px; font-weight:bold;
        }
        QPushButton#toggle_btn[active="true"]{ background:#1a5cff; color:white; }
        QTableWidget{
            background:#131722; color:white; gridline-color:#232323;
            border:none; font-size:12px;
        }
        QHeaderView::section{ background:#1a1d26; color:#999; padding:6px; border:none; font-weight:600; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("📄 TRADES")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch()

        self.recent_btn = QPushButton("Recent")
        self.recent_btn.setObjectName("toggle_btn")
        self.recent_btn.setProperty("active", "true")
        self.recent_btn.clicked.connect(lambda: self._select_mode("recent"))
        header.addWidget(self.recent_btn)

        self.open_btn = QPushButton("Open Positions")
        self.open_btn.setObjectName("toggle_btn")
        self.open_btn.setProperty("active", "false")
        self.open_btn.clicked.connect(lambda: self._select_mode("open"))
        header.addWidget(self.open_btn)

        outer.addLayout(header)

        self.table = QTableWidget()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        outer.addWidget(self.table)

        self._mode = "recent"
        self._recent = []
        self._open = []
        self._render()

    def _select_mode(self, mode):
        if mode == self._mode:
            return
        self._mode = mode
        for btn, active in ((self.recent_btn, mode == "recent"), (self.open_btn, mode == "open")):
            btn.setProperty("active", "true" if active else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self._render()

    def set_recent_trades(self, records: list):
        self._recent = records or []
        if self._mode == "recent":
            self._render()

    def set_open_positions(self, positions: list):
        self._open = positions or []
        if self._mode == "open":
            self._render()

    def _render(self):
        self.table.setColumnCount(3)

        if self._mode == "recent":
            self.table.setHorizontalHeaderLabels(["Symbol", "Close Date", "Net P&L"])
            rows = self._recent[:15]
            self.table.setRowCount(len(rows))
            for r, rec in enumerate(rows):
                pnl = rec.get("pnl_usd") or 0
                try:
                    pnl = float(pnl)
                except (TypeError, ValueError):
                    pnl = 0.0
                closed_at = rec.get("closed_at")
                closed_text = str(closed_at)[:10] if closed_at not in (None, "") else "—"
                self._fill_row(r, rec.get("symbol", ""), closed_text, pnl)
        else:
            self.table.setHorizontalHeaderLabels(["Symbol", "Opened", "Unrealized P&L"])
            rows = self._open
            self.table.setRowCount(len(rows))
            for r, p in enumerate(rows):
                pnl = p.unrealized_pnl()
                opened_text = p.opened_at.strftime("%Y-%m-%d %H:%M") if getattr(p, "opened_at", None) else "—"
                self._fill_row(r, p.symbol, opened_text, pnl)

    def _fill_row(self, row, symbol, date_text, pnl):
        color = QColor("#2ecc71") if pnl >= 0 else QColor("#e74c3c")
        values = [symbol, date_text, f"{'+' if pnl >= 0 else ''}{pnl:,.2f}"]
        for col, val in enumerate(values):
            item = QTableWidgetItem(str(val))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if col == 2:
                item.setForeground(color)
            self.table.setItem(row, col, item)


class AnalyticsPanel(QWidget):
    """ANALYTICS tab — overview dashboard: Trade Win gauge, Profit
    Factor / Trade Expectancy / Avg Win-Loss / Net P&L / Day Streak /
    Trade Streak cards, a P&L Calendar, and a Recent/Open Positions
    trades table. Metrics come from strategy.analytics.AnalyticsEngine
    via DashboardController.refresh_history_tabs()."""

    calendar_month_requested = pyqtSignal(int, int)  # (year, month)

    def __init__(self):
        super().__init__()
        self.setStyleSheet("QWidget{ background:#0B0E14; }")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)

        title = QLabel("📊 ANALYTICS — Overview")
        title.setStyleSheet("color:#00FF88; font-size:16px; font-weight:bold;")
        outer.addWidget(title)

        # ---- Top row: Trade Win gauge card + 2x3 stat grid ----
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        top_row.addWidget(self._build_win_card(), 0)

        stats_grid = QGridLayout()
        stats_grid.setSpacing(12)

        self.profit_factor_card = _StatCard("PROFIT FACTOR")
        self.expectancy_card = _StatCard("TRADE EXPECTANCY")
        self.avg_win_loss_card = _StatCard("AVG WIN / LOSS TRADE")
        self.net_pnl_card = _NetPnlCard("NET P&L")
        self.day_streak_card = _StatCard("DAY STREAK")
        self.trade_streak_card = _StatCard("TRADE STREAK")

        stats_grid.addWidget(self.profit_factor_card, 0, 0)
        stats_grid.addWidget(self.expectancy_card, 0, 1)
        stats_grid.addWidget(self.avg_win_loss_card, 0, 2)
        stats_grid.addWidget(self.net_pnl_card, 1, 0)
        stats_grid.addWidget(self.day_streak_card, 1, 1)
        stats_grid.addWidget(self.trade_streak_card, 1, 2)

        top_row.addLayout(stats_grid, 1)
        outer.addLayout(top_row)

        # ---- Bottom row: P&L Calendar + Trades table ----
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(12)

        self.calendar = PnLCalendar()
        self.calendar.month_changed.connect(self.calendar_month_requested.emit)
        bottom_row.addWidget(self.calendar, 3)

        self.trades_table = TradesTable()
        bottom_row.addWidget(self.trades_table, 2)

        outer.addLayout(bottom_row, 1)

    def _build_win_card(self):
        card = QFrame()
        card.setStyleSheet("QFrame{ background:#131722; border:1px solid #1E222D; border-radius:8px; }")
        card.setMinimumWidth(220)
        card.setMaximumWidth(240)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        label = QLabel("TRADE WIN")
        label.setStyleSheet("QLabel{color:#7b8191; font-size:11px; font-weight:bold;}")
        layout.addWidget(label)

        self.win_gauge = CircularGauge("", size=120)
        layout.addWidget(self.win_gauge, 0, Qt.AlignmentFlag.AlignHCenter)

        counts_row = QHBoxLayout()
        counts_row.setSpacing(10)
        counts_row.addStretch()

        self.win_count_label = QLabel("0")
        self.win_count_label.setStyleSheet("QLabel{color:#2ecc71; font-size:12px; font-weight:bold;}")
        self.breakeven_count_label = QLabel("0")
        self.breakeven_count_label.setStyleSheet("QLabel{color:#7b8191; font-size:12px; font-weight:bold;}")
        self.loss_count_label = QLabel("0")
        self.loss_count_label.setStyleSheet("QLabel{color:#e74c3c; font-size:12px; font-weight:bold;}")

        counts_row.addWidget(self.win_count_label)
        counts_row.addWidget(self.breakeven_count_label)
        counts_row.addWidget(self.loss_count_label)
        counts_row.addStretch()
        layout.addLayout(counts_row)

        layout.addStretch()
        return card

    # ------------------------------------------------------------
    # Public update API — called by DashboardController.refresh_history_tabs()
    # ------------------------------------------------------------

    def set_metrics(self, metrics: dict):
        """metrics: strategy.analytics.AnalyticsEngine.latest_saved() / compute()."""

        win_rate = float(metrics.get("win_rate_pct", 0) or 0)
        win_count = int(metrics.get("win_count", 0) or 0)
        loss_count = int(metrics.get("loss_count", 0) or 0)
        total_trades = int(metrics.get("total_trades", 0) or 0)
        breakeven_count = max(0, total_trades - win_count - loss_count)

        self.win_gauge.set_value(win_rate, "", "#2ecc71" if win_rate >= 50 else "#e67e22")
        self.win_count_label.setText(str(win_count))
        self.breakeven_count_label.setText(str(breakeven_count))
        self.loss_count_label.setText(str(loss_count))

        pf = metrics.get("profit_factor", 0)
        pf_text = "\u221e" if pf == "inf" else f"{float(pf or 0):.2f}"
        self.profit_factor_card.set_value(pf_text)

    def set_extras(self, extras: dict):
        """extras: strategy.analytics.AnalyticsEngine.compute_extras()."""

        expectancy = float(extras.get("trade_expectancy", 0) or 0)
        self.expectancy_card.set_value(
            f"${expectancy:,.2f}", color="#2ecc71" if expectancy >= 0 else "#e74c3c"
        )

        avg_win = float(extras.get("avg_win", 0) or 0)
        avg_loss = float(extras.get("avg_loss", 0) or 0)
        self.avg_win_loss_card.set_value_html(
            f"<span style='color:#2ecc71;'>+${avg_win:,.2f}</span><br>"
            f"<span style='color:#e74c3c;'>-${abs(avg_loss):,.2f}</span>"
        )

        equity_curve = extras.get("equity_curve", [])
        net_pnl = equity_curve[-1] if equity_curve else 0.0
        self.net_pnl_card.set_pnl(net_pnl, equity_curve)

        day_streak = int(extras.get("day_streak", 0) or 0)
        self.day_streak_card.set_value(
            f"{day_streak} day{'s' if day_streak != 1 else ''} \U0001F525" if day_streak else "0 days",
            color="#f5a623" if day_streak else None,
        )

        trade_streak = int(extras.get("trade_streak", 0) or 0)
        self.trade_streak_card.set_value(
            f"{trade_streak} trade{'s' if trade_streak != 1 else ''} \U0001F525" if trade_streak else "0 trades",
            color="#f5a623" if trade_streak else None,
        )

    def set_calendar(self, year: int, month: int, data: dict):
        self.calendar.set_data(year, month, data)

    def set_recent_trades(self, records: list):
        self.trades_table.set_recent_trades(records)

    def set_open_positions(self, positions: list):
        self.trades_table.set_open_positions(positions)
