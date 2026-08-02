from PyQt6.QtWidgets import QWidget, QGridLayout, QVBoxLayout, QLabel, QFrame
from PyQt6.QtCore import Qt


class _MetricCard(QFrame):
    def __init__(self, title):
        super().__init__()
        self.setStyleSheet("""
        QFrame{ background:#131722; border:1px solid #1E222D; border-radius:8px; }
        QLabel#label{ color:#7b8191; font-size:11px; font-weight:bold; }
        QLabel#value{ color:#e1e4ea; font-size:20px; font-weight:bold; }
        """)
        layout = QVBoxLayout(self)
        self.label = QLabel(title)
        self.label.setObjectName("label")
        self.value = QLabel("--")
        self.value.setObjectName("value")
        self.value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value.setWordWrap(True)
        layout.addWidget(self.label)
        layout.addWidget(self.value)

    def set_value(self, text, color=None, font_size=20):
        self.value.setText(str(text))
        text_color = color or "#e1e4ea"
        self.value.setStyleSheet(f"color:{text_color}; font-size:{font_size}px; font-weight:bold;")


class AnalyticsPanel(QWidget):
    """ANALYTICS tab — key performance metrics computed by
    strategy.analytics.AnalyticsEngine from orders_history.csv /
    trade_journal.csv, refreshed every time a position closes."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet("QWidget{ background:#0B0E14; }")

        layout = QVBoxLayout(self)

        title = QLabel("📊 ANALYTICS — Performance Summary")
        title.setStyleSheet("color:#00FF88; font-size:16px; font-weight:bold;")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setSpacing(12)
        layout.addLayout(grid)
        layout.addStretch()

        self.win_rate_card = _MetricCard("WIN RATE")
        self.pnl_card = _MetricCard("TOTAL REALIZED PNL ($)")
        self.profit_factor_card = _MetricCard("PROFIT FACTOR")
        self.drawdown_card = _MetricCard("MAX DRAWDOWN (%)")
        self.rr_card = _MetricCard("AVG RISK / REWARD")
        self.trades_card = _MetricCard("TOTAL TRADES (WIN / LOSS)")

        cards = [
            self.win_rate_card, self.pnl_card, self.profit_factor_card,
            self.drawdown_card, self.rr_card, self.trades_card,
        ]
        for i, card in enumerate(cards):
            grid.addWidget(card, i // 3, i % 3)

    def set_metrics(self, metrics: dict):
        pnl = metrics.get("total_realized_pnl", 0.0)
        pnl_color = "#2ecc71" if pnl >= 0 else "#e74c3c"

        self.win_rate_card.set_value(f"{metrics.get('win_rate_pct', 0):.2f}%")
        self.pnl_card.set_value(f"{pnl:,.2f}", color=pnl_color)
        self.profit_factor_card.set_value(metrics.get("profit_factor", 0))
        self.drawdown_card.set_value(f"{metrics.get('max_drawdown_pct', 0):.2f}%")
        self.rr_card.set_value(f"1 : {metrics.get('avg_risk_reward', 0):.2f}")
        total_trades = metrics.get('total_trades', 0)
        wins = metrics.get('win_count', 0)
        losses = metrics.get('loss_count', 0)
        longs = metrics.get('long_trades', 0)
        shorts = metrics.get('short_trades', 0)
        self.trades_card.set_value(
            f"{total_trades} Trades ({wins} Wins / {losses} Losses)\n({longs}L / {shorts}S)",
            font_size=14,
        )
