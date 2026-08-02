from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox, QSlider, QFrame, QComboBox,
    QSizePolicy
)
from PyQt6.QtCore import pyqtSignal, QTimer, Qt
from PyQt6.QtGui import QFontMetrics


class TradeSetup(QWidget):
    """Paper-trading order entry panel matching reference design with reactive slider & price controls."""

    buy_long_clicked = pyqtSignal(dict)
    sell_short_clicked = pyqtSignal(dict)
    # (capital_pct_clicked removed — its only emitters, the quick %
    # buttons and the manual size slider, no longer exist; Position
    # Size is now fully auto-calculated, see _auto_size_from_formula)
    auto_mode_toggled = pyqtSignal(bool)
    ai_trading_toggled = pyqtSignal(bool)

    def __init__(self):
        super().__init__()

        # Locks this panel's own footprint within the bottom splitter
        # cell (same fix already applied to PositionsPanel) — its size
        # comes only from the splitter's allotted cell, never from
        # content changes like the AUTO MODE toggle re-enabling widgets.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)

        self.setStyleSheet("""
            QWidget {
                background-color: #0b0e14;
                color: #a0a5b5;
                font-family: 'Segoe UI', sans-serif;
            }

            QFrame#main_frame {
                background-color: #12161f;
                border: 1px solid #1a1f2c;
                border-radius: 8px;
            }

            QLabel#section_title {
                color: #e1e4ea;
                font-size: 13px;
                font-weight: bold;
                letter-spacing: 0.5px;
            }

            QLabel {
                color: #7b8191;
                font-size: 11px;
                font-weight: 500;
            }

            /* SpinBox Styling with Visible Up/Down Adjusters */
            QDoubleSpinBox {
                background-color: #090b0e;
                color: #ffffff;
                border: 1px solid #232936;
                border-radius: 4px;
                padding: 4px 18px 4px 6px;
                font-size: 13px;
                font-weight: bold;
            }
            
            QDoubleSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 16px;
                border-left: 1px solid #232936;
                border-bottom: 1px solid #232936;
                background-color: #141824;
                border-top-right-radius: 4px;
            }
            QDoubleSpinBox::up-button:hover {
                background-color: #202636;
            }
            QDoubleSpinBox::up-arrow {
                width: 0;
                height: 0;
                border-left: 3px solid transparent;
                border-right: 3px solid transparent;
                border-bottom: 4px solid #00FF88;
            }

            QDoubleSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 16px;
                border-left: 1px solid #232936;
                background-color: #141824;
                border-bottom-right-radius: 4px;
            }
            QDoubleSpinBox::down-button:hover {
                background-color: #202636;
            }
            QDoubleSpinBox::down-arrow {
                width: 0;
                height: 0;
                border-left: 3px solid transparent;
                border-right: 3px solid transparent;
                border-top: 4px solid #ff5b5b;
            }

            /* Risk/Reward Display Box */
            QLabel#rr_box {
                background-color: #090b0e;
                color: #ffffff;
                border: 1px solid #232936;
                border-radius: 4px;
                padding: 6px;
                font-size: 13px;
                font-weight: bold;
            }

            /* Quick % Buttons */
            QPushButton#pct_btn {
                background-color: #1a1f2c;
                color: #8b92a5;
                border: none;
                border-radius: 3px;
                font-size: 10px;
                font-weight: bold;
                padding: 4px 0px;
            }
            QPushButton#pct_btn:hover {
                background-color: #252c3d;
                color: #ffffff;
            }

            /* Main Action Buttons */
            QPushButton#buy_btn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #22a053, stop:1 #156d37);
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton#buy_btn:hover {
                background: #28b860;
            }

            QPushButton#sell_btn {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e54343, stop:1 #9e2323);
                color: #ffffff;
                font-weight: bold;
                font-size: 13px;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton#sell_btn:hover {
                background: #f05252;
            }

            /* Toggle Switch Containers */
            QFrame#toggle_container {
                background-color: #181d29;
                border-radius: 4px;
                border: 1px solid #232936;
            }

            QPushButton#toggle_label_btn {
                background: transparent;
                color: #7b8191;
                font-size: 10px;
                font-weight: bold;
                border: none;
                padding: 6px;
            }

            QPushButton#toggle_state_btn {
                background-color: #1a5cff;
                color: #ffffff;
                font-size: 10px;
                font-weight: bold;
                border: none;
                border-radius: 3px;
                padding: 6px 10px;
            }
            QPushButton#toggle_state_btn[active="false"] {
                background-color: #252c3d;
                color: #61687a;
            }

            /* Interactive Position Slider */
            QSlider::groove:horizontal {
                height: 4px;
                background: #232936;
                border-radius: 2px;
            }
            QSlider::sub-page:horizontal {
                background: #1a5cff;
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: #1a5cff;
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
            }
            QSlider::handle:horizontal:hover {
                background: #3b75ff;
            }

            QLabel#warning {
                color: #ff5b5b;
                font-size: 11px;
                font-weight: bold;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.card = QFrame()
        self.card.setObjectName("main_frame")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(10, 8, 10, 8)
        card_layout.setSpacing(6)

        title = QLabel("TRADE SETUP")
        title.setObjectName("section_title")
        card_layout.addWidget(title)

        cols_layout = QHBoxLayout()
        cols_layout.setSpacing(16)

        # ================= LEFT COLUMN =================
        left_col = QVBoxLayout()
        left_col.setSpacing(10)

        inputs_row = QHBoxLayout()
        inputs_row.setSpacing(8)

        # Direct QDoubleSpinBox fields with step options (0.5 BTC / USDT per click)
        self.entry_price, _ = self._field(inputs_row, "Entry Price", 0.0, step=0.5)
        self.stop_loss, self.stop_loss_label = self._field(inputs_row, "Stop Loss", 0.0, step=0.5)
        self.take_profit, self.take_profit_label = self._field(inputs_row, "Take Profit", 0.0, step=0.5)

        left_col.addLayout(inputs_row)

        # Per-unit price distance, kept only so _update_rr has a
        # consistent number for the Risk/Reward ratio box — SL/TP are
        # always absolute prices, there's no separate "$" input mode.
        self._sl_distance = 0.0
        self._tp_distance = 0.0
        self._suspend_sltp_signals = False

        # Entry/SL/TP auto-follow the live price until the trader
        # manually edits that specific field — see set_last_price() /
        # _on_entry_price_changed() / _on_sltp_value_changed().
        self._entry_locked = False
        self._sl_locked = False
        self._tp_locked = False
        self._default_sl_pct = 0.005   # 0.5% below entry, matches executor default
        self._default_tp_pct = 0.015   # 1.5% above entry, matches executor default

        # Leverage + Margin Usage % no longer have their own controls
        # here — they live once, in Settings ("Default Leverage" /
        # "Capital Allocation per trade"), and are pushed into this
        # panel via set_leverage()/set_margin_pct(). Position Size
        # (BTC) is fully auto-calculated from them (see
        # _auto_size_from_formula) instead of being a manual/%-button
        # input, so it can never silently drift from what Settings says.
        self._leverage = 25
        self._margin_pct = 0.50

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self.buy_btn = QPushButton("↑\nBUY LONG")
        self.buy_btn.setObjectName("buy_btn")
        self.buy_btn.clicked.connect(self._emit_buy)

        self.sell_btn = QPushButton("↓\nSELL SHORT")
        self.sell_btn.setObjectName("sell_btn")
        self.sell_btn.clicked.connect(self._emit_sell)

        action_row.addWidget(self.buy_btn)
        action_row.addWidget(self.sell_btn)
        left_col.addLayout(action_row)

        cols_layout.addLayout(left_col, stretch=5)

        # ================= RIGHT COLUMN =================
        right_col = QVBoxLayout()
        right_col.setSpacing(10)

        rr_size_row = QHBoxLayout()
        rr_size_row.setSpacing(8)

        # Risk / Reward
        rr_box = QVBoxLayout()
        rr_box.setSpacing(4)
        rr_label = QLabel("Risk/Reward")
        self.rr_value = QLabel("1 : 3.50")
        self.rr_value.setObjectName("rr_box")
        self.rr_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rr_box.addWidget(rr_label)
        rr_box.addWidget(self.rr_value)
        rr_size_row.addLayout(rr_box, stretch=1)

        # Position Size — auto-calculated: (balance x leverage x margin%) / price.
        # Read-only: editing it directly would just get overwritten on
        # the next price tick or balance update, which is more
        # confusing than a field that's clearly automatic.
        size_box = QVBoxLayout()
        size_box.setSpacing(4)
        size_label = QLabel("Position Size (BTC) — auto")
        self.size = QDoubleSpinBox()
        self.size.setRange(0, 10_000)
        self.size.setDecimals(3)
        self.size.setSingleStep(0.01)
        self.size.setValue(1.000)
        self.size.setReadOnly(True)
        self.size.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.size.setToolTip(
            "Auto-calculated: (Balance x Leverage x Margin Usage %) / Entry Price.\n"
            "Change Leverage / Capital Allocation % in Settings to adjust."
        )
        size_box.addWidget(size_label)
        size_box.addWidget(self.size)
        rr_size_row.addLayout(size_box, stretch=1)

        right_col.addLayout(rr_size_row)

        # Leverage / Margin Usage — spec section 2: proper spacing
        # between the two (previously one crowded label), and each
        # becomes an interactive QComboBox once AUTO MODE is OFF so the
        # trader can manually override what Settings/the auto-formula
        # would otherwise pick. Locked (disabled) while AUTO MODE is ON.
        leverage_margin_row = QHBoxLayout()
        leverage_margin_row.setSpacing(18)  # clear separation, no overlap

        leverage_box = QVBoxLayout()
        leverage_box.setSpacing(3)
        leverage_box.addWidget(QLabel("Leverage"))
        self.leverage_combo = QComboBox()
        self.leverage_combo.addItems(["1x", "5x", "10x", "25x", "50x", "100x"])
        self.leverage_combo.setCurrentText("25x")
        self.leverage_combo.setEnabled(False)  # AUTO MODE starts ON
        self.leverage_combo.currentTextChanged.connect(self._on_leverage_combo_changed)
        leverage_box.addWidget(self.leverage_combo)
        leverage_margin_row.addLayout(leverage_box)

        margin_box = QVBoxLayout()
        margin_box.setSpacing(3)
        margin_box.addWidget(QLabel("Margin Usage %"))
        self.margin_combo = QComboBox()
        self.margin_combo.addItems(["10%", "25%", "50%", "75%", "100%"])
        self.margin_combo.setCurrentText("50%")
        self.margin_combo.setEnabled(False)  # AUTO MODE starts ON
        self.margin_combo.currentTextChanged.connect(self._on_margin_combo_changed)
        margin_box.addWidget(self.margin_combo)
        leverage_margin_row.addLayout(margin_box)

        right_col.addLayout(leverage_margin_row)

        # Switches
        switches_row = QHBoxLayout()
        switches_row.setSpacing(8)

        self.auto_mode_btn = self._create_toggle_switch(
            switches_row, "AUTO MODE", True, self._toggle_auto_mode
        )
        self.ai_trading_btn = self._create_toggle_switch(
            switches_row, "AI AUTO TRADING", True, self._toggle_ai_trading
        )

        right_col.addLayout(switches_row)
        cols_layout.addLayout(right_col, stretch=4)

        card_layout.addLayout(cols_layout)

        self.warning_label = QLabel("")
        self.warning_label.setObjectName("warning")
        self.warning_label.setVisible(False)
        card_layout.addWidget(self.warning_label)

        main_layout.addWidget(self.card)

        # Recalculate Risk:Reward / SL-TP-Size relationships on change
        self.entry_price.valueChanged.connect(self._on_entry_price_changed)
        self.stop_loss.valueChanged.connect(self._on_sltp_value_changed)
        self.take_profit.valueChanged.connect(self._on_sltp_value_changed)
        self.size.valueChanged.connect(self._on_size_changed)

        # Paper account balance, kept in sync via set_balance() every UI
        # tick — drives the (balance x leverage x margin%) / price
        # auto-sizing formula together with set_leverage()/set_margin_pct().
        self._balance = 10000.0

        self._warning_timer = QTimer(self)
        self._warning_timer.setSingleShot(True)
        self._warning_timer.timeout.connect(lambda: self.warning_label.setVisible(False))

        self._last_price = 0.0

        # AUTO MODE starts ON (see _create_toggle_switch call above), so
        # manual controls start locked to match — the bot, not the
        # trader's mouse, is in charge until AUTO MODE is switched off.
        self.set_manual_controls_locked(True)
        self.auto_mode_toggled.connect(self.set_manual_controls_locked)

    def _field(self, parent_layout, label_text, default_val=0.0, step=0.5,
               decimals=1, max_val=10_000_000):
        box = QVBoxLayout()
        box.setSpacing(4)
        label = QLabel(label_text)
        spin = QDoubleSpinBox()
        spin.setRange(0, max_val)
        spin.setDecimals(decimals)
        spin.setSingleStep(step)
        spin.setValue(default_val)
        box.addWidget(label)
        box.addWidget(spin)
        parent_layout.addLayout(box)
        return spin, label

    def _create_toggle_switch(self, parent_layout, text, initial_state, callback):
        container = QFrame()
        container.setObjectName("toggle_container")
        layout = QHBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(0)

        label_btn = QPushButton(text)
        label_btn.setObjectName("toggle_label_btn")

        state_btn = QPushButton("ON" if initial_state else "OFF")
        state_btn.setObjectName("toggle_state_btn")
        state_btn.setProperty("active", str(initial_state).lower())
        state_btn.clicked.connect(lambda: callback(state_btn))

        # Fixed width sized to the wider of "ON"/"OFF" (plus the
        # button's own horizontal padding) — otherwise flipping between
        # the two different-length strings changes this button's own
        # sizeHint every toggle, which invalidates geometry up through
        # container -> switches_row -> card_layout -> main_layout and
        # is what caused the whole panel (and, via the splitter, the
        # main chart viewport next to it) to visibly stretch/jump.
        fm = QFontMetrics(state_btn.font())
        text_w = max(fm.horizontalAdvance("ON"), fm.horizontalAdvance("OFF"))
        state_btn.setFixedWidth(text_w + 20)  # + left/right padding (10px + 10px)
        state_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        layout.addWidget(label_btn)
        layout.addStretch()
        layout.addWidget(state_btn)

        parent_layout.addWidget(container)
        return state_btn

    def _toggle_auto_mode(self, btn: QPushButton):
        is_active = btn.property("active") == "true"
        new_state = not is_active
        btn.setProperty("active", str(new_state).lower())
        btn.setText("ON" if new_state else "OFF")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        self.auto_mode_toggled.emit(new_state)

    def _toggle_ai_trading(self, btn: QPushButton):
        is_active = btn.property("active") == "true"
        new_state = not is_active
        btn.setProperty("active", str(new_state).lower())
        btn.setText("ON" if new_state else "OFF")
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        self.ai_trading_toggled.emit(new_state)

    # --- Dynamic Position Sizing ---
    #   Total Purchasing Power = Balance x Leverage
    #   Allocated Capital ($)  = Purchasing Power x Margin Usage %
    #   Position Size (BTC)    = Allocated Capital / Current Price
    #
    # Normally driven from Settings (no in-panel controls when AUTO
    # MODE is ON); this recalculates on every price tick and every
    # balance update. When AUTO MODE is OFF, the Leverage / Margin
    # Usage % dropdowns unlock so the trader can override them directly
    # for manual trades — see _on_leverage_combo_changed /
    # _on_margin_combo_changed below.

    def set_leverage(self, leverage):
        try:
            self._leverage = float(leverage) if leverage else 25
        except (TypeError, ValueError):
            self._leverage = 25
        self._sync_leverage_combo()
        self._auto_size_from_formula()

    def set_margin_pct(self, pct):
        """pct as a fraction (0.50 == 50%)."""
        try:
            self._margin_pct = max(0.0, min(1.0, float(pct))) if pct else 0.50
        except (TypeError, ValueError):
            self._margin_pct = 0.50
        self._sync_margin_combo()
        self._auto_size_from_formula()

    def _sync_leverage_combo(self):
        text = f"{int(self._leverage)}x"
        self.leverage_combo.blockSignals(True)
        if self.leverage_combo.findText(text) >= 0:
            self.leverage_combo.setCurrentText(text)
        self.leverage_combo.blockSignals(False)

    def _sync_margin_combo(self):
        text = f"{int(round(self._margin_pct * 100))}%"
        self.margin_combo.blockSignals(True)
        if self.margin_combo.findText(text) >= 0:
            self.margin_combo.setCurrentText(text)
        self.margin_combo.blockSignals(False)

    def _on_leverage_combo_changed(self, text):
        """Trader manually picked a leverage from the dropdown (only
        possible while AUTO MODE is OFF) — overrides Settings' Default
        Leverage for this panel until AUTO MODE is turned back on."""
        try:
            self._leverage = float(text.rstrip("x"))
        except ValueError:
            return
        self._auto_size_from_formula()

    def _on_margin_combo_changed(self, text):
        """Trader manually picked a Margin Usage % (only possible while
        AUTO MODE is OFF)."""
        try:
            self._margin_pct = float(text.rstrip("%")) / 100
        except ValueError:
            return
        self._auto_size_from_formula()

    def _auto_size_from_formula(self):
        entry = self.entry_price.value() or self._last_price

        if entry <= 0 or not self._balance:
            return

        purchasing_power = self._balance * self._leverage
        allocated_usd = purchasing_power * self._margin_pct
        qty = allocated_usd / entry

        # Round to 3 decimals; enforce a 0.001 BTC minimum lot size so
        # a tiny balance/price combination can't produce a zero/invalid
        # order quantity.
        qty = max(0.001, round(qty, 3))

        self._suspend_sltp_signals = True
        self.size.blockSignals(True)
        self.size.setValue(min(qty, self.size.maximum()))
        self.size.blockSignals(False)
        self._suspend_sltp_signals = False
        self._update_rr()

    def set_balance(self, balance):
        """Called every UI tick with the live paper-account balance —
        recalculates Position Size (BTC) immediately, per spec:
        'Automatically update the Position Size (BTC) input field
        dynamically whenever price ticks change or balance updates.'"""
        try:
            self._balance = float(balance)
        except (TypeError, ValueError):
            return
        self._auto_size_from_formula()

    def _update_rr(self):
        entry = self.entry_price.value()
        sl = self.stop_loss.value()
        tp = self.take_profit.value()

        if entry <= 0 or sl <= 0 or tp <= 0:
            self.rr_value.setText("—")
            return

        risk = abs(entry - sl)
        reward = abs(tp - entry)

        self._sl_distance = risk
        self._tp_distance = reward

        if risk <= 0:
            self.rr_value.setText("—")
            return

        ratio = reward / risk
        self.rr_value.setText(f"1 : {ratio:.2f}")

    def _on_entry_price_changed(self):
        """Entry Price field edited (by the trader, or programmatically
        by set_last_price() with signals blocked — so this only ever
        fires for a real user edit)."""
        if not self._suspend_sltp_signals:
            self._entry_locked = True
        self._auto_size_from_formula()

    def _on_sltp_value_changed(self):
        """Stop Loss / Take Profit field edited by the trader (both
        fields are always plain prices now)."""
        if self._suspend_sltp_signals:
            return

        sender = self.sender()
        if sender is self.stop_loss:
            self._sl_locked = True
        elif sender is self.take_profit:
            self._tp_locked = True

        self._update_rr()

    def _on_size_changed(self, _value=None):
        """Position Size changed (manual edit, slider, %-buttons, or the
        leverage-driven auto-sizing rule) — just keep the $ risk/reward
        hints and R:R display in sync with the new size."""
        if self._suspend_sltp_signals:
            return
        self._update_rr()

    def show_rejection(self, message):
        self.warning_label.setText(f"⛔ {message}")
        self.warning_label.setVisible(True)
        self._warning_timer.start(5000)

    def set_size(self, size):
        self.size.setValue(round(size, 3))

    def set_last_price(self, price):
        """Called every UI tick with the live market price. Entry Price
        (and, in PRICE mode, Stop Loss / Take Profit at their default
        offsets) keep tracking the live price until the trader manually
        edits that specific field — otherwise they'd stay pinned at
        whatever stale number they were initialized with, no matter how
        far the market has since moved."""

        try:
            price = float(price)
        except (TypeError, ValueError):
            return

        self._last_price = price

        if price <= 0:
            return

        self._suspend_sltp_signals = True

        if not self._entry_locked and not self.entry_price.hasFocus():
            self.entry_price.blockSignals(True)
            self.entry_price.setValue(round(price, 1))
            self.entry_price.blockSignals(False)

        if not self._sl_locked and not self.stop_loss.hasFocus():
            self.stop_loss.blockSignals(True)
            self.stop_loss.setValue(round(price * (1 - self._default_sl_pct), 1))
            self.stop_loss.blockSignals(False)

        if not self._tp_locked and not self.take_profit.hasFocus():
            self.take_profit.blockSignals(True)
            self.take_profit.setValue(round(price * (1 + self._default_tp_pct), 1))
            self.take_profit.blockSignals(False)

        self._suspend_sltp_signals = False
        self._auto_size_from_formula()

    def _resolved_sl_tp(self, side):
        """
        Resolve the Stop Loss / Take Profit price fields for the trading
        engine — direction depends on side, since a LONG's stop sits
        below entry while a SHORT's sits above it.
        """

        entry = self.entry_price.value() or self._last_price

        sl_price = self.stop_loss.value()
        tp_price = self.take_profit.value()
        sl_dist = abs(entry - sl_price) if sl_price else 0.0
        tp_dist = abs(tp_price - entry) if tp_price else 0.0

        if side == "LONG":
            sl = (entry - sl_dist) if sl_dist else None
            tp = (entry + tp_dist) if tp_dist else None
        else:
            sl = (entry + sl_dist) if sl_dist else None
            tp = (entry - tp_dist) if tp_dist else None

        return sl, tp

    def _payload(self, side="LONG"):
        sl, tp = self._resolved_sl_tp(side)
        return {
            "entry_price": self.entry_price.value() or self._last_price,
            "stop_loss": sl,
            "take_profit": tp,
            "size": self.size.value() or 1.0,
            "leverage": self._leverage,
        }

    def _emit_buy(self):
        self.buy_long_clicked.emit(self._payload("LONG"))

    def _emit_sell(self):
        self.sell_short_clicked.emit(self._payload("SHORT"))

    # --- AUTO MODE UI locking (spec section 2) ---
    def set_manual_controls_locked(self, locked: bool):
        """AUTO MODE == ON  -> locked=True  -> manual widgets disabled
        AUTO MODE == OFF -> locked=False -> manual widgets re-enabled

        Disables exactly the controls a manual trader would otherwise
        use to interfere with the bot: Buy/Sell buttons, entry/SL/TP
        price fields, and the Leverage / Margin Usage % dropdowns
        (spec section 2 — those unlock only while AUTO MODE is OFF, so
        the automated formula's inputs can't be changed out from under
        it while it's running). Position Size stays read-only/auto
        regardless of AUTO MODE.
        """

        enabled = not locked

        # Batch all the state changes below into a single repaint pass
        # instead of one per widget — setEnabled()/setToolTip() alone
        # never touch layout geometry, but suspending updates here is
        # cheap insurance against any intermediate partial-repaint
        # flicker while five widgets update back-to-back.
        self.setUpdatesEnabled(False)
        try:
            self.buy_btn.setEnabled(enabled)
            self.sell_btn.setEnabled(enabled)
            self.entry_price.setEnabled(enabled)
            self.stop_loss.setEnabled(enabled)
            self.take_profit.setEnabled(enabled)
            self.leverage_combo.setEnabled(enabled)
            self.margin_combo.setEnabled(enabled)

            if locked:
                self.buy_btn.setToolTip("AUTO MODE is ON — the bot is trading. Turn AUTO MODE off to trade manually.")
                self.sell_btn.setToolTip(self.buy_btn.toolTip())
            else:
                self.buy_btn.setToolTip("")
                self.sell_btn.setToolTip("")
        finally:
            self.setUpdatesEnabled(True)