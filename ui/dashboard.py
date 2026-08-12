from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QScrollArea,
    QStackedWidget,
    QLabel,
    QPushButton,
    QMenu,
    QWidgetAction,
    QSplitter,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction

from ui.header import Header
from ui.topnav import TopNav, TABS
from ui.chart_widget import FootprintChart
from ui.timeframe_selector import TimeframeSelector
from ui.ai_panel import AIPanel
from ui.microstructure_panel import MicrostructurePanel
from ui.volume_profile import VolumeProfile
from ui.orderbook import OrderBook
from ui.trades import RecentTrades
from ui.positions import PositionsPanel
from ui.orders import OrdersPanel
from ui.journal import JournalPanel
from ui.analytics import AnalyticsPanel
from ui.trade_setup import TradeSetup
from ui.settings import SettingsPanel
from ui.statusbar import StatusBar

from controller.dashboard_controller import DashboardController
from core.app_state import AppStateHandler


# The compact Dashboard tab was laid out, pixel-for-pixel, assuming a
# canvas around 1900x1000 (fixed-width table columns in ui/positions.py,
# a fixed-width AIPanel, a Header QHBoxLayout with no wrap/scroll of its
# own, etc.). None of those panels gracefully reflow below their design
# width — the Header simply loses whatever falls past the window's right
# edge (no scrollbar at all), and the AI Engine panel's scroll area had
# its horizontal scrollbar explicitly disabled, so text past its
# allotted width was silently truncated mid-word instead of being
# reachable by scrolling. Rather than rewrite every panel to reflow
# responsively, the practical fix is to stop the window from ever being
# resized into a state those panels weren't designed for, and add a
# scrollbar as a fallback for the one panel that can still get squeezed
# by the splitter even at the minimum size.
MIN_WINDOW_WIDTH = 1600
MIN_WINDOW_HEIGHT = 900


def _placeholder_page(name):
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel(f"{name}\n\nNot built yet.")
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setStyleSheet("color:#555; font-size:16px;")
    layout.addWidget(label)
    return page


class Dashboard(QMainWindow):

    def __init__(self):
        super().__init__()

        self.setWindowTitle("AI OrderFlow Pro V10.0")
        self.resize(1900, 1000)

        # Guards against the exact "screen stretch / clipped text" bug
        # this fixes: dragging or restoring the window to something
        # narrower than the dashboard's fixed-pixel panels need used to
        # silently cut off content (Header's Balance/mode/clock, the AI
        # Engine panel's labels) with no way to scroll and see it. A
        # hard floor here means those panels always get at least the
        # width they were designed for.
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        self.setStyleSheet("""
        QMainWindow{
            background:#0B0E14;
        }
        QWidget{
            background:#0B0E14;
            color:white;
        }
        """)

        # Central Layout
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        central.setLayout(root)

        # Top Navigation & Header
        self.topnav = TopNav()
        root.addWidget(self.topnav)

        self.header = Header()
        root.addWidget(self.header)

        # Pages
        self.pages = QStackedWidget()
        root.addWidget(self.pages)

        dashboard_page = self._build_dashboard_page()
        self.pages.addWidget(dashboard_page)

        self._page_index = {"Dashboard": 0}

        # Dedicated tab pages (separate widget instances from the
        # compact Dashboard-page ones — a QWidget can only live in one
        # layout at a time). Settings has no spec in this pass, so it
        # stays a placeholder.
        self.positions_tab = PositionsPanel(show_close_column=True)
        self.orders_tab = OrdersPanel()
        self.analytics_tab = AnalyticsPanel()
        self.journal_tab = JournalPanel()
        self.settings_tab = SettingsPanel()

        tab_pages = {
            "Positions": self.positions_tab,
            "Orders": self.orders_tab,
            "Analytics": self.analytics_tab,
            "Journal": self.journal_tab,
            "Settings": self.settings_tab,
        }

        for i, name in enumerate(TABS[1:], start=1):
            self.pages.addWidget(tab_pages[name])
            self._page_index[name] = i

        self.topnav.tab_clicked.connect(self._switch_page)

        # Dashboard Controller
        self.controller = DashboardController(self)

        # Restore last-used state (AUTO MODE / AI AUTO TRADING toggles,
        # symbol, timeframe, indicators, trade-setup fields, balance)
        # now that the controller (and therefore paper_engine) exists.
        self.app_state = AppStateHandler()
        self.app_state.restore_state(self)

        # Populate Orders/Journal/Analytics tabs from CSV immediately,
        # so history from previous sessions shows up on launch even
        # before any trade closes in this session.
        self.controller.refresh_history_tabs()

        print("✅ Dashboard Loaded")

    def _switch_page(self, name):
        self.pages.setCurrentIndex(self._page_index.get(name, 0))

        # Lazily refresh tab contents only when the user actually looks
        # at them — avoids re-reading CSVs on every single UI tick.
        if name in ("Orders", "Journal", "Analytics", "Positions"):
            self.controller.refresh_history_tabs()

    def closeEvent(self, event):
        """Auto-save everything (toggles, symbol/timeframe, indicators,
        trade-setup fields, paper balance) so the app resumes exactly
        where it was closed next launch."""

        try:
            self.app_state.save_state(self)
        except Exception as e:
            print(f"⚠️ closeEvent state save failed: {e}")

        try:
            if hasattr(self, "_ws_thread") and self._ws_thread is not None:
                self._ws_thread.quit()
                self._ws_thread.wait(2000)
        except Exception as e:
            print(f"⚠️ closeEvent websocket shutdown failed: {e}")

        super().closeEvent(event)

    def _build_dashboard_page(self):
        page = QWidget()
        center = QVBoxLayout(page)
        center.setContentsMargins(5, 5, 5, 5)

        # ---------------- TOP ROW ----------------
        # A QSplitter, not a plain QHBoxLayout+stretch: stretch factors
        # only set *proportions* — they don't stop a pane's own content
        # (or a child widget's minimum-width) from forcing a relayout.
        # A QSplitter's pane widths are fixed by setSizes()/user-drag
        # only; they never move just because a label's text changed.
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.setHandleWidth(4)
        top_splitter.setChildrenCollapsible(False)
        top_splitter.setStyleSheet("QSplitter::handle{ background:#1E222D; }")
        center.addWidget(top_splitter, 7)

        chart_container = QWidget()
        chart_col = QVBoxLayout(chart_container)
        chart_col.setContentsMargins(0, 0, 0, 0)
        chart_col.setSpacing(4)

        # Controls bar above the chart
        chart_controls = QHBoxLayout()

        self.timeframe = TimeframeSelector(default_label="15m")
        chart_controls.addWidget(self.timeframe)

        chart_controls.addStretch()
        chart_col.addLayout(chart_controls)

        # Native Footprint Chart
        self.chart = FootprintChart()
        # Keep the chart synchronized with TimeframeSelector default (15m).
        self.chart.set_timeframe("15m")
        
        # Connect Timeframe selection to chart
        if hasattr(self.timeframe, 'timeframe_changed'):
            self.timeframe.timeframe_changed.connect(self._on_timeframe_changed)

        chart_col.addWidget(self.chart)
        top_splitter.addWidget(chart_container)

        # --- Middle Column: OrderBook ---
        dom_container = QWidget()
        dom_col = QVBoxLayout(dom_container)
        dom_col.setContentsMargins(0, 0, 0, 0)
        dom_col.setSpacing(4)

        self.orderbook = OrderBook()
        dom_col.addWidget(self.orderbook)
        top_splitter.addWidget(dom_container)

        # --- Right Column: AI Panel + Microstructure Diagnostics + Volume Profile ---
        right_container = QWidget()
        right_col = QVBoxLayout(right_container)
        right_col.setContentsMargins(0, 0, 0, 0)
        right_col.setSpacing(0)

        self.ai = AIPanel()
        self.microstructure = MicrostructurePanel()
        self.volume_profile = VolumeProfile()

        right_col.addWidget(self.ai)
        right_col.addWidget(self.microstructure)
        right_col.addWidget(self.volume_profile)

        right_scroll = QScrollArea()
        right_scroll.setWidget(right_container)
        right_scroll.setWidgetResizable(True)
        # Fallback only — with the window's new minimum size (see
        # MIN_WINDOW_WIDTH above) this pane should always get enough
        # room to render without needing to scroll sideways. But if the
        # splitter still ends up squeezing this pane below the AI
        # panel's natural content width (e.g. the user drags the
        # splitter handle manually), AsNeeded means that content
        # becomes reachable by scrolling instead of being silently
        # truncated mid-word with no way to see the rest at all.
        right_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        right_scroll.setStyleSheet("QScrollArea{ background:#131722; border-left:1px solid #1E222D; }")

        top_splitter.addWidget(right_scroll)

        # Layout ratio: Footprint/Chart 55% | Live Orderbook 20% | AI Engine 25%
        # (setSizes is only the *initial* split — the user can still
        # drag the handles; the splitter re-clamps to the window's
        # actual width on resize instead of ever overflowing it, and
        # never re-splits just because a child's text changed.)
        total_width = max(self.width(), 1900)
        top_splitter.setSizes([
            int(total_width * 0.55),
            int(total_width * 0.20),
            int(total_width * 0.25),
        ])
        top_splitter.setStretchFactor(0, 55)
        top_splitter.setStretchFactor(1, 20)
        top_splitter.setStretchFactor(2, 25)

        # ---------------- BOTTOM ROW ----------------
        # Same QSplitter fix: Positions / Recent Trades / Trade Setup
        # used to sit in a QHBoxLayout with equal stretch, which let a
        # PnL string flipping sign/width nudge all three panels
        # sideways. A splitter's panes stay exactly where they're put.
        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        bottom_splitter.setHandleWidth(4)
        bottom_splitter.setChildrenCollapsible(False)
        bottom_splitter.setStyleSheet("QSplitter::handle{ background:#1E222D; }")

        self.positions = PositionsPanel()
        self.trades = RecentTrades()
        self.trade_setup = TradeSetup()

        bottom_splitter.addWidget(self.positions)
        bottom_splitter.addWidget(self.trades)
        bottom_splitter.addWidget(self.trade_setup)

        bottom_splitter.setSizes([
            int(total_width * 0.34),
            int(total_width * 0.30),
            int(total_width * 0.36),
        ])
        bottom_splitter.setStretchFactor(0, 34)
        bottom_splitter.setStretchFactor(1, 30)
        bottom_splitter.setStretchFactor(2, 36)

        # Spec: "Reduce vertical/horizontal space taken by Positions /
        # Recent Trades / Trade Setup ... re-allocate freed screen
        # space to expand the main Chart." A hard cap here (on top of
        # the 7:1 top:bottom stretch above) means this row can't grow
        # to fit its own content — its own scrollbars/table rows handle
        # overflow instead of pushing the chart smaller.
        bottom_splitter.setMaximumHeight(230)

        center.addWidget(bottom_splitter, 1)

        # Footer
        self.statusbar = StatusBar()
        center.addWidget(self.statusbar)

        return page

    def _on_timeframe_changed(self, tf):
        """Keep the native chart timeframe synchronized with the selector."""
        if hasattr(self.chart, 'set_timeframe'):
            self.chart.set_timeframe(tf)
        elif hasattr(self.chart, 'change_timeframe'):
            # Backward-compatible fallback for older FootprintChart versions.
            tf_seconds = {
                "1m": 60,
                "5m": 300,
                "15m": 900,
                "1H": 3600,
                "4H": 14400,
                "1D": 86400,
            }.get(tf)
            if tf_seconds is not None:
                self.chart.change_timeframe(tf_seconds)
