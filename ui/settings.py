"""
ui/settings.py

SETTINGS tab. Previously an empty placeholder file (nothing was ever
implemented here), which is why the tab rendered blank. This exposes
the parameters that already exist and do something real elsewhere in
the app — AutoTradeExecutor's risk sizing / confidence threshold /
cooldown, and the paper account balance — instead of adding decorative
controls that don't connect to anything.
"""

from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QFrame,
    QDoubleSpinBox, QSpinBox, QPushButton, QScrollArea,
)
from PyQt6.QtCore import pyqtSignal


def _section_title(text):
    label = QLabel(text)
    label.setStyleSheet("QLabel{font-size:13px; font-weight:bold; color:#00FF88; padding-top:10px;}")
    return label


def _row(label_text, widget):
    row = QHBoxLayout()
    label = QLabel(label_text)
    label.setStyleSheet("QLabel{font-size:12px; color:#c7cbd6;}")
    row.addWidget(label)
    row.addStretch()
    row.addWidget(widget)
    return row


class SettingsPanel(QWidget):

    # (size, stop_loss_pct, take_profit_pct)
    risk_params_changed = pyqtSignal(float, float, float)
    confidence_threshold_changed = pyqtSignal(float)
    cooldown_changed = pyqtSignal(int)
    reset_balance_clicked = pyqtSignal()

    # Emitted when "Save Settings" is clicked, carrying every value on
    # this screen as a plain dict ready for core.config.ConfigManager.save()
    save_settings_clicked = pyqtSignal(dict)

    def __init__(self):
        super().__init__()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea{border:none;}")
        outer.addWidget(scroll)

        body = QWidget()
        scroll.setWidget(body)

        layout = QVBoxLayout(body)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(10)

        title = QLabel("⚙️  Settings")
        title.setStyleSheet("QLabel{font-size:16px; font-weight:bold; color:white;}")
        layout.addWidget(title)

        # -------- Trading Preferences (spec section 5) --------
        layout.addWidget(_section_title("Trading Preferences"))

        self.default_leverage_spin = QSpinBox()
        self.default_leverage_spin.setRange(1, 200)
        self.default_leverage_spin.setValue(25)
        self.default_leverage_spin.setSuffix("x")
        layout.addLayout(_row("Default Leverage", self.default_leverage_spin))

        self.capital_alloc_spin = QDoubleSpinBox()
        self.capital_alloc_spin.setRange(1, 100)
        self.capital_alloc_spin.setDecimals(0)
        self.capital_alloc_spin.setValue(50)
        self.capital_alloc_spin.setSuffix(" %")
        layout.addLayout(_row("Capital Allocation per trade", self.capital_alloc_spin))

        self.trade_risk_spin = QDoubleSpinBox()
        self.trade_risk_spin.setRange(0.1, 100)
        self.trade_risk_spin.setDecimals(1)
        self.trade_risk_spin.setValue(2.0)
        self.trade_risk_spin.setSuffix(" %")
        layout.addLayout(_row("Trade Risk % (of balance)", self.trade_risk_spin))

        divider0 = QFrame()
        divider0.setFrameShape(QFrame.Shape.HLine)
        divider0.setStyleSheet("background:#232936; max-height:1px; border:none; margin-top:8px;")
        layout.addWidget(divider0)

        # -------- AI Auto Trading risk parameters --------
        layout.addWidget(_section_title("AI Auto Trading — Risk Parameters"))

        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(0.01, 100)
        self.size_spin.setDecimals(3)
        self.size_spin.setSingleStep(0.1)
        self.size_spin.setValue(1.0)
        self.size_spin.setSuffix(" BTC")
        layout.addLayout(_row("Position Size per auto-trade", self.size_spin))

        self.sl_pct_spin = QDoubleSpinBox()
        self.sl_pct_spin.setRange(0.05, 20)
        self.sl_pct_spin.setDecimals(2)
        self.sl_pct_spin.setSingleStep(0.1)
        self.sl_pct_spin.setValue(0.5)
        self.sl_pct_spin.setSuffix(" %")
        layout.addLayout(_row("Default Stop Loss distance", self.sl_pct_spin))

        self.tp_pct_spin = QDoubleSpinBox()
        self.tp_pct_spin.setRange(0.05, 50)
        self.tp_pct_spin.setDecimals(2)
        self.tp_pct_spin.setSingleStep(0.1)
        self.tp_pct_spin.setValue(1.5)
        self.tp_pct_spin.setSuffix(" %")
        layout.addLayout(_row("Default Take Profit distance", self.tp_pct_spin))

        self.confidence_spin = QSpinBox()
        self.confidence_spin.setRange(1, 100)
        self.confidence_spin.setValue(55)
        self.confidence_spin.setSuffix(" %")
        layout.addLayout(_row("Minimum AI Confidence to auto-trade", self.confidence_spin))

        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(0, 3600)
        self.cooldown_spin.setValue(20)
        self.cooldown_spin.setSuffix(" sec")
        layout.addLayout(_row("Cooldown between auto-trades", self.cooldown_spin))

        for spin in (self.size_spin, self.sl_pct_spin, self.tp_pct_spin):
            spin.valueChanged.connect(self._emit_risk_params)
        self.confidence_spin.valueChanged.connect(
            lambda v: self.confidence_threshold_changed.emit(float(v))
        )
        self.cooldown_spin.valueChanged.connect(
            lambda v: self.cooldown_changed.emit(int(v))
        )

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("background:#232936; max-height:1px; border:none; margin-top:8px;")
        layout.addWidget(divider)

        # -------- Paper account --------
        layout.addWidget(_section_title("Paper Account"))

        reset_row = QHBoxLayout()
        reset_label = QLabel("Reset paper balance and close all positions")
        reset_label.setStyleSheet("QLabel{font-size:12px; color:#c7cbd6;}")
        reset_row.addWidget(reset_label)
        reset_row.addStretch()
        self.reset_btn = QPushButton("RESET BALANCE")
        self.reset_btn.setObjectName("reset_btn")
        self.reset_btn.setStyleSheet("""
            QPushButton{
                background:#2A2E39; color:#ff8a65; border:1px solid #ff8a65;
                border-radius:4px; padding:6px 14px; font-weight:bold; font-size:11px;
            }
            QPushButton:hover{ background:#ff8a65; color:#131722; }
        """)
        self.reset_btn.clicked.connect(self.reset_balance_clicked.emit)
        reset_row.addWidget(self.reset_btn)
        layout.addLayout(reset_row)

        divider2 = QFrame()
        divider2.setFrameShape(QFrame.Shape.HLine)
        divider2.setStyleSheet("background:#232936; max-height:1px; border:none; margin-top:8px;")
        layout.addWidget(divider2)

        # -------- Save Settings (spec section 5) --------
        save_row = QHBoxLayout()
        self.saved_label = QLabel("")
        self.saved_label.setStyleSheet("QLabel{font-size:11px; color:#2ecc71;}")
        save_row.addWidget(self.saved_label)
        save_row.addStretch()

        self.save_settings_btn = QPushButton("💾 SAVE SETTINGS")
        self.save_settings_btn.setStyleSheet("""
            QPushButton{
                background:#00C853; color:#04140a; border-radius:4px;
                padding:8px 18px; font-weight:bold; font-size:12px;
            }
            QPushButton:hover{ background:#00e676; }
        """)
        self.save_settings_btn.clicked.connect(self._on_save_clicked)
        save_row.addWidget(self.save_settings_btn)
        layout.addLayout(save_row)

        layout.addStretch()

    def _emit_risk_params(self):
        self.risk_params_changed.emit(
            self.size_spin.value(), self.sl_pct_spin.value(), self.tp_pct_spin.value()
        )

    def _collect_settings(self) -> dict:
        """Every value on this screen, as a plain dict — what gets
        written to config/settings.json."""
        return {
            "default_leverage": self.default_leverage_spin.value(),
            "capital_allocation_pct": self.capital_alloc_spin.value(),
            "trade_risk_pct": self.trade_risk_spin.value(),
            "auto_trade_size_btc": self.size_spin.value(),
            "default_stop_loss_pct": self.sl_pct_spin.value(),
            "default_take_profit_pct": self.tp_pct_spin.value(),
            "min_ai_confidence_pct": self.confidence_spin.value(),
            "cooldown_seconds": self.cooldown_spin.value(),
        }

    def _on_save_clicked(self):
        self.save_settings_clicked.emit(self._collect_settings())
        self.saved_label.setText("✓ Saved")

    def apply_settings(self, settings: dict):
        """Push a loaded config/settings.json dict into every widget on
        this screen, without re-triggering the per-field change signals
        (those would fire risk_params_changed etc. — harmless, but this
        keeps 'load' silent and 'save' explicit, as the spec asks)."""

        widgets = {
            "default_leverage": self.default_leverage_spin,
            "capital_allocation_pct": self.capital_alloc_spin,
            "trade_risk_pct": self.trade_risk_spin,
            "auto_trade_size_btc": self.size_spin,
            "default_stop_loss_pct": self.sl_pct_spin,
            "default_take_profit_pct": self.tp_pct_spin,
            "min_ai_confidence_pct": self.confidence_spin,
            "cooldown_seconds": self.cooldown_spin,
        }

        for key, widget in widgets.items():
            if key in settings and settings[key] is not None:
                widget.blockSignals(True)
                widget.setValue(settings[key])
                widget.blockSignals(False)
