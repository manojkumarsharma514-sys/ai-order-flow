import time

from PyQt6.QtCore import QTimer

from core.orderflow_engine import orderflow_engine as market
from core.candle_engine import CandleManager, aggregate_volume_profile
from core.websocket_thread import HistoryFetchThread
from core import event_bus

from strategy.indicators import calculate_rsi, calculate_atr, calculate_vwap
from strategy.trend import ema_trend
from strategy.analytics import AnalyticsEngine

from trading.paper_trading import PaperTradingEngine
from trading.orders import OrdersManager
from trading.journal import JournalManager
from trading.executor import AutoTradeExecutor
from trading.risk import calculate_risk_percent, risk_label

from strategy.ai_engine import compute_factor_breakdown

from core.config import ConfigManager
from trading.journal import generate_report_html
from ui.journal import TradeReportDialog


UI_REFRESH_MS = 250  # ~4 repaints/sec — see note below


class DashboardController:
    """
    Delta can push dozens of trades and large order-book snapshots per
    second. Repainting every widget on every single message floods Qt's
    paint queue faster than the screen can keep up, which is what caused
    the garbled/ghosted text and layout glitches that only cleared on
    minimize/maximize (that forces one clean full repaint).

    Fix: event handlers below only ever do *cheap* work — updating the
    underlying data models (market engine, candle series, positions,
    latest orderbook/trade). All *expensive* widget repaints (chart,
    volume profile, AI panel, order book table, positions table) happen
    on a fixed-rate QTimer instead, reading whatever the latest state
    is. This decouples repaint rate from raw message rate.
    """

    def __init__(self, dashboard):

        self.dashboard = dashboard

        # single rolling footprint candle series feeding the chart
        self.candle_manager = CandleManager(timeframe_seconds=300, tick_size=5.0)

        # simulated-only paper trading engine (no real orders are ever sent)
        self.paper_engine = PaperTradingEngine(starting_balance=10000.0)

        # "paper" | "demo" | "live" — captured/restored by
        # AppStateHandler (app_state.trading_mode / exchange_config).
        # Real live-order routing is out of scope here (see the note in
        # trading/paper_trading.py); this flag is tracked so it round
        # trips through app_state.json even before that work lands, and
        # drives the Header/Positions "Paper/Demo/Live" badges below.
        # `account_type` is kept as an alias for the same value, since
        # different parts of the app refer to it under either name.
        self.trading_mode = "paper"
        self.account_type = "paper"

        # --- CSV persistence layer (Orders / Journal / Analytics) ---
        self.orders_manager = OrdersManager()
        self.journal_manager = JournalManager()
        self.analytics_engine = AnalyticsEngine(self.orders_manager)

        # Every position close (manual, SL/TP, or AI auto-trade) fans
        # out to Orders CSV -> Journal CSV -> Analytics recompute ->
        # dashboard tab refresh, via this single listener.
        self.paper_engine.add_close_listener(self._on_position_closed)

        # --- AI auto-trade executor (AI Engine -> Executor -> Paper Trading) ---
        self.executor = AutoTradeExecutor(
            paper_engine=self.paper_engine,
            symbol=self.paper_engine.symbol,
        )
        self.executor.auto_trade_executed.connect(self._on_auto_trade_executed)
        self.executor.auto_trade_rejected.connect(self._on_auto_trade_rejected)

        self.dashboard.positions.close_all_clicked.connect(self.close_all_positions)
        self.dashboard.positions.reset_clicked.connect(self.reset_paper_account)
        self.dashboard.trade_setup.buy_long_clicked.connect(self.open_long)
        self.dashboard.trade_setup.sell_short_clicked.connect(self.open_short)
        self.dashboard.statusbar.stop_clicked.connect(self.toggle_pause)
        self.dashboard.timeframe.timeframe_changed.connect(self.change_timeframe)

        # AUTO MODE: UI locking is self-contained inside TradeSetup
        # (see ui/trade_setup.py set_manual_controls_locked). The
        # controller only needs to track the value for state save/load.
        self.dashboard.trade_setup.auto_mode_toggled.connect(self._on_auto_mode_toggled)

        # AI AUTO TRADING: this is the switch that actually lets
        # AutoTradeExecutor place paper trades.
        self.dashboard.trade_setup.ai_trading_toggled.connect(self.executor.set_enabled)

        # Dedicated Positions tab (separate instance, show_close_column=True)
        self.dashboard.positions_tab.close_position_clicked.connect(self.close_position_by_id)

        # Dedicated Journal tab — editable Notes column saves back to CSV
        self.dashboard.journal_tab.notes_edited.connect(self._on_journal_notes_edited)
        self.dashboard.journal_tab.view_report_clicked.connect(self._on_view_report)

        # Dedicated Settings tab — AI Auto Trading risk params + paper reset
        self.dashboard.settings_tab.risk_params_changed.connect(
            lambda size, sl_pct, tp_pct: self.executor.set_risk_params(
                size=size, stop_loss_pct=sl_pct, take_profit_pct=tp_pct
            )
        )
        self.dashboard.settings_tab.confidence_threshold_changed.connect(
            self._set_confidence_threshold
        )
        self.dashboard.settings_tab.cooldown_changed.connect(self._set_cooldown_seconds)
        self.dashboard.settings_tab.reset_balance_clicked.connect(self.reset_paper_account)

        # -------------------------------------------------------
        # Persistent Settings (spec section 5): config/settings.json.
        # Distinct from AppStateHandler (session state saved on every
        # close) — these are explicit preferences the trader saves on
        # purpose, so they're only written when "Save Settings" is
        # clicked, and loaded once here at startup.
        # -------------------------------------------------------
        self.config_manager = ConfigManager()
        saved_settings = self.config_manager.load()
        print(f"📂 Loaded settings.json — starting_paper_balance = {saved_settings.get('starting_paper_balance')!r}")
        self.dashboard.settings_tab.apply_settings(saved_settings)
        self._apply_settings_to_live_controls(saved_settings)

        self.dashboard.settings_tab.save_settings_clicked.connect(self._on_save_settings)

        try:
            self.dashboard.statusbar.set_symbol(self.paper_engine.symbol)
        except Exception as e:
            print(f"statusbar symbol init error: {e}")

        self.auto_mode = True

        # Push the initial "paper"/"demo"/"live" badge state into the
        # Header + Positions panels now that they all exist. Restored
        # sessions get this re-applied again by AppStateHandler once
        # the saved trading_mode is loaded (see restore_state()).
        self.set_account_mode(self.trading_mode)

        # keeps a reference to whichever one-shot history-fetch thread is
        # currently running, so it isn't garbage-collected mid-request
        self._history_thread = None

        # trading paused = new Buy/Sell clicks are ignored (Stop Bot).
        # Data keeps flowing either way — this pauses trading, not the feed.
        self.trading_paused = False

        # real feed-freshness tracking for the footer's Latency readout
        self._last_event_time = None

        # cached latest state, written on every event, read by the timer
        self._latest_price = None
        self._latest_bids = []
        self._latest_asks = []
        self._pending_trades = []  # [(side, price, size), ...] since last repaint
        self._dirty = False

        # latest ATR(14), refreshed by update_indicators() each tick —
        # fed into the executor so SL/TP can be ATR-based instead of a
        # flat percentage (see trading/executor.py).
        self._latest_atr = None

        event_bus.subscribe(self.on_market_update)

        self._ui_timer = QTimer()
        self._ui_timer.timeout.connect(self.refresh_ui)
        self._ui_timer.start(UI_REFRESH_MS)

        print("✅ Dashboard Controller Started")

    # -------------------------------------------------------
    # Main Event — cheap, runs on every message
    # -------------------------------------------------------

    def on_market_update(self, data):

        self._last_event_time = time.time()

        try:
            market.process(data)
        except Exception as e:
            print("orderflow_engine error:", e)

        event = data.get("event")

        if event == "trade":
            self._record_trade(data)

        elif event == "orderbook":
            self._latest_bids = data.get("bids", [])
            self._latest_asks = data.get("asks", [])

        self._dirty = True

    def _record_trade(self, data):

        side = "BUY"

        if data.get("seller_role") == "taker":
            side = "SELL"

        price = data.get("price")
        size = data.get("size")
        ts = data.get("timestamp")

        try:
            price_f = float(price)
        except (TypeError, ValueError):
            return

        self._latest_price = price_f
        self._pending_trades.append((side, price_f, size))

        try:
            self.candle_manager.on_trade(price_f, size, side, ts)
        except Exception as e:
            print("candle update error:", e)

        try:
            self.paper_engine.mark_to_market(price_f)
        except Exception as e:
            print("position mark-to-market error:", e)

    # -------------------------------------------------------
    # UI Refresh — expensive, runs on a fixed timer only
    # -------------------------------------------------------

    def refresh_ui(self):

        if self._last_event_time is not None:
            try:
                ms_since_last = (time.time() - self._last_event_time) * 1000
                self.dashboard.statusbar.set_latency(ms_since_last)
            except Exception:
                pass

        if not self._dirty:
            return

        self._dirty = False

        # ---- recent trades (flush anything queued since last tick) ----
        for side, price, size in self._pending_trades:
            try:
                self.dashboard.trades.add_trade(side, price, size)
            except Exception:
                pass
        self._pending_trades.clear()

        # ---- order book ----
        try:
            self.dashboard.orderbook.update_orderbook(
                self._latest_bids, self._latest_asks, last_price=self._latest_price
            )
        except Exception as e:
            print("orderbook render error:", e)

        # ---- header price ----
        try:
            self.dashboard.header.update_price(market.price)
        except Exception:
            pass

        # ---- chart + volume profile ----
        try:
            self.dashboard.chart.set_candles(self.candle_manager.get_candles(), current_price=self._latest_price)

            profile = aggregate_volume_profile(self.candle_manager.get_candles())
            self.dashboard.volume_profile.set_profile(profile, current_price=self._latest_price)

            # Keep the VPVR's price axis aligned with the main chart's
            # visible price bounds so levels line up horizontally.
            if hasattr(self.dashboard.chart, "get_price_range"):
                vp_min, vp_max = self.dashboard.chart.get_price_range()
                self.dashboard.volume_profile.set_price_range(vp_min, vp_max)
        except Exception as e:
            print("chart render error:", e)

        # ---- trade setup default entry price ----
        if self._latest_price is not None:
            try:
                self.dashboard.trade_setup.set_last_price(self._latest_price)
            except Exception:
                pass

        try:
            self.dashboard.trade_setup.set_balance(self.paper_engine.balance)
        except Exception:
            pass

        # ---- AI panel ----
        try:
            self.dashboard.ai.update_ai(
                confidence=int(market.confidence),
                buyers=int(market.buy_strength),
                sellers=int(market.sell_strength),
                trend=market.market_regime,
                signal=market.signal,
                delta=round(market.delta, 2),
                liquidity=f"{market.dom_pressure:.1f}%"
            )
        except Exception as e:
            print("ai panel update error:", e)

        try:
            direction = "BULLISH" if market.buy_strength >= market.sell_strength else "BEARISH"
            self.dashboard.header.update_gauges(
                confidence=market.confidence,
                direction_label=direction,
                risk_pct=self._risk_percent(),
                risk_label=self._risk_label(),
            )
        except Exception as e:
            print("gauge update error:", e)

        # ---- indicators (moved ahead of the executor call below so
        # ATR is freshly computed before it's handed to the executor
        # for ATR-based SL/TP — previously this ran *after* the
        # executor, so evaluate() was always one tick stale on ATR) ----
        self.update_indicators()

        # ---- AI Engine -> Executor bridge (auto-trading) ----
        # Trades on market.confirmed_signal (persisted for several
        # seconds — see core/orderflow_engine.py), not the raw
        # per-tick market.signal, so a single noisy tick can no longer
        # trigger an entry or a signal-flip on its own. ATR is passed
        # through so the executor can set real ATR-based SL/TP instead
        # of only ever exiting via signal flip.
        try:
            self.executor.evaluate(
                signal=getattr(market, "confirmed_signal", market.signal),
                confidence=market.confidence,
                price=self._latest_price,
                atr=self._latest_atr,
            )
        except Exception as e:
            print("auto-trade executor error:", e)

        # ---- positions ----
        self.refresh_positions()

    def _risk_percent(self):
        """
        Real, calculable risk measure: dollars-at-risk (position size *
        |entry - stop loss|) as a percentage of account balance — see
        trading/risk.py. Positions with no stop loss set contribute 0
        (their downside isn't bounded), and no open positions -> 0%.
        Never a static/maxed-out 100%.
        """

        return calculate_risk_percent(self.paper_engine.positions, self.paper_engine.balance)

    def _risk_label(self):
        return risk_label(self._risk_percent())

    # -------------------------------------------------------
    # Positions / Trade Setup (paper trading only)
    # -------------------------------------------------------

    def refresh_positions(self):

        self.dashboard.positions.update_positions(
            self.paper_engine.positions,
            self.paper_engine.total_unrealized_pnl(),
        )

        # Dedicated POSITIONS tab: spec section 4 — only current-date
        # open/active positions. Closed positions are removed from
        # `paper_engine.positions` the instant they close (see
        # PaperTradingEngine.close_position), so this list is always
        # "currently open", filtered further to ones opened today.
        todays_positions = [
            p for p in self.paper_engine.positions if p.is_open_today()
        ]
        todays_pnl = sum(p.unrealized_pnl() for p in todays_positions)
        self.dashboard.positions_tab.update_positions(todays_positions, todays_pnl)

        self.dashboard.header.update_balance(self.paper_engine.equity())

        # Chart overlay: Entry (blue) / Stop Loss (red, $-loss labeled) /
        # Take Profit (green, $-gain labeled) lines for every open
        # position — spec section 3, redrawn every tick so they track
        # size/SL/TP edits dynamically.
        try:
            lines = []
            for p in self.paper_engine.positions:
                lines.append({
                    "entry": p.entry_price,
                    "side": p.side,
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "risk_usd": p.size * abs(p.entry_price - p.stop_loss) if p.stop_loss else 0.0,
                    "reward_usd": p.size * abs(p.take_profit - p.entry_price) if p.take_profit else 0.0,
                })
            self.dashboard.chart.set_position_lines(lines)
        except Exception as e:
            print("chart position-lines render error:", e)

    # (size_by_capital_pct removed — the 25/50/75/100% quick-size
    # buttons it served are gone; Position Size (BTC) is now always
    # auto-calculated from balance x leverage x margin%, see
    # ui/trade_setup.py _auto_size_from_formula and
    # trading/executor.py calculate_position_size)

    def open_long(self, payload):

        if self.trading_paused:
            print("⏸ Trading paused — Buy Long ignored")
            self.dashboard.trade_setup.show_rejection("Trading is paused — resume the bot to trade")
            return

        # Keep the engine's margin check in step with whatever leverage
        # is selected in the Trade Setup panel (spec section 4) — a
        # manual trade sized against 100x shouldn't get rejected by a
        # leftover 20x cap from a previous session.
        leverage = payload.get("leverage")
        if leverage:
            self.paper_engine.max_leverage = leverage

        result = self.paper_engine.open_position(
            side="LONG",
            size=payload["size"],
            entry_price=payload["entry_price"],
            stop_loss=payload["stop_loss"],
            take_profit=payload["take_profit"],
        )

        if result is None:
            self.dashboard.trade_setup.show_rejection(
                self.paper_engine.last_rejection or "Order rejected"
            )
            return

        self.refresh_positions()

    def open_short(self, payload):

        if self.trading_paused:
            print("⏸ Trading paused — Sell Short ignored")
            self.dashboard.trade_setup.show_rejection("Trading is paused — resume the bot to trade")
            return

        leverage = payload.get("leverage")
        if leverage:
            self.paper_engine.max_leverage = leverage

        result = self.paper_engine.open_position(
            side="SHORT",
            size=payload["size"],
            entry_price=payload["entry_price"],
            stop_loss=payload["stop_loss"],
            take_profit=payload["take_profit"],
        )

        if result is None:
            self.dashboard.trade_setup.show_rejection(
                self.paper_engine.last_rejection or "Order rejected"
            )
            return

        self.refresh_positions()

    # -------------------------------------------------------
    # Timeframe switching
    # -------------------------------------------------------

    def change_timeframe(self, resolution, seconds):
        """
        Switch the chart to a new timeframe. Starts a fresh live candle
        series immediately (so the chart doesn't show stale-timeframe
        bars), then re-fetches REST OHLC history for the new resolution
        in the background to backfill it, exactly like startup does.
        """

        self.candle_manager.set_timeframe(seconds)

        # clear the chart right away instead of waiting for the
        # background fetch to land
        try:
            self.dashboard.chart.set_candles(self.candle_manager.get_candles(), current_price=self._latest_price)
        except Exception as e:
            print("chart clear on timeframe switch error:", e)

        try:
            self.dashboard.tv_chart.set_timeframe(seconds)
        except Exception as e:
            print("tradingview chart timeframe sync error:", e)

        symbol = getattr(self.paper_engine, "symbol", "BTCUSD")

        self._history_thread = HistoryFetchThread(symbol=symbol, resolution=resolution, count=150)
        self._history_thread.history_loaded.connect(self._on_timeframe_history_loaded)
        self._history_thread.start()

    def _on_timeframe_history_loaded(self, rows):

        try:
            self.candle_manager.seed_history(rows)
            self.dashboard.chart.set_candles(self.candle_manager.get_candles(), current_price=self._latest_price)
        except Exception as e:
            print("timeframe history backfill error:", e)

    def toggle_pause(self):

        self.trading_paused = not self.trading_paused
        self.dashboard.statusbar.set_paused(self.trading_paused)

    def close_all_positions(self):

        self.paper_engine.close_all(reason="manual")
        self.refresh_positions()

    def close_position_by_id(self, position_id):
        """Manual 'Close Position' button on the dedicated Positions tab."""

        result = self.paper_engine.close_position(position_id, reason="manual")
        if result is None:
            print(f"⚠️ close_position_by_id: no open position with id {position_id}")
        self.refresh_positions()

    def reset_paper_account(self):

        print(f"🔄 RESET BALANCE clicked — paper_engine.starting_balance is currently ${self.paper_engine.starting_balance:,.2f}")
        self.paper_engine.reset()
        print(f"✅ Paper balance is now ${self.paper_engine.balance:,.2f}")
        self.refresh_positions()

    def _set_confidence_threshold(self, value: float):
        self.executor.confidence_threshold = value

    def _set_cooldown_seconds(self, value: int):
        self.executor.cooldown_seconds = value

    def _apply_settings_to_live_controls(self, settings: dict):
        """Push a loaded (or just-saved) settings dict into whatever
        actually drives behavior — the AutoTradeExecutor's dynamic
        position-sizing formula (leverage + margin %) and its risk
        params/confidence threshold/cooldown, plus the Trade Setup
        panel's own copy of leverage/margin so its Position Size (BTC)
        field tracks the same formula for manual trades."""

        leverage = settings.get("default_leverage", 25)
        margin_pct = (settings.get("capital_allocation_pct", 50) or 50) / 100

        self.executor.set_leverage(leverage)
        self.executor.set_margin_pct(margin_pct)

        try:
            self.dashboard.trade_setup.set_leverage(leverage)
            self.dashboard.trade_setup.set_margin_pct(margin_pct)
        except Exception as e:
            print(f"apply leverage/margin to Trade Setup error: {e}")

        self.executor.set_risk_params(
            size=settings.get("auto_trade_size_btc"),
            stop_loss_pct=settings.get("default_stop_loss_pct"),
            take_profit_pct=settings.get("default_take_profit_pct"),
        )
        self.executor.confidence_threshold = settings.get("min_ai_confidence_pct", self.executor.confidence_threshold)
        self.executor.cooldown_seconds = settings.get("cooldown_seconds", self.executor.cooldown_seconds)

        # What RESET BALANCE resets the paper account back to. Doesn't
        # touch the CURRENT balance by itself (that would silently
        # change the account's live equity out from under an open
        # session) — the trader clicks RESET BALANCE separately to
        # actually apply it, same as changing SL/TP % doesn't retroactively
        # edit an already-open position.
        starting_balance = settings.get("starting_paper_balance")
        if starting_balance:
            self.paper_engine.starting_balance = starting_balance
            print(f"🔧 paper_engine.starting_balance set to ${starting_balance:,.2f} (from settings)")
        else:
            print(f"⚠️ 'starting_paper_balance' missing/falsy in settings dict "
                  f"(got: {settings.get('starting_paper_balance')!r}) — starting_balance "
                  f"left at ${self.paper_engine.starting_balance:,.2f}")

    def _on_save_settings(self, settings: dict):
        self.config_manager.save(settings)
        self._apply_settings_to_live_controls(settings)

    # -------------------------------------------------------
    # AUTO MODE / AI AUTO TRADING toggle bookkeeping
    # -------------------------------------------------------

    def _on_auto_mode_toggled(self, is_on: bool):
        self.auto_mode = is_on
        print(f"🔒 AUTO MODE -> {'ON (manual controls locked)' if is_on else 'OFF (manual controls unlocked)'}")

    # -------------------------------------------------------
    # Account mode ("paper" | "demo" | "live") — read from
    # app_state.trading_mode / exchange_config, and pushed into every
    # widget that displays it: Header badge, Positions panel titles
    # (compact dashboard panel + dedicated Positions tab), and the
    # RESET BALANCE button's visibility (hidden entirely on Live).
    # -------------------------------------------------------

    def set_account_mode(self, mode: str):
        mode = mode if mode in ("paper", "demo", "live") else "paper"
        self.trading_mode = mode
        self.account_type = mode  # alias — same value, other naming

        try:
            self.dashboard.header.set_account_mode(mode)
        except Exception as e:
            print(f"header account-mode update error: {e}")

        try:
            self.dashboard.positions.set_account_mode(mode)
        except Exception as e:
            print(f"positions panel account-mode update error: {e}")

        try:
            self.dashboard.positions_tab.set_account_mode(mode)
        except Exception as e:
            print(f"positions tab account-mode update error: {e}")

    # -------------------------------------------------------
    # Position close -> Orders CSV -> Journal CSV -> Analytics -> UI
    # (section 3 checklist item 2-4, and section 4/5/6 CSV persistence)
    # -------------------------------------------------------

    def _on_position_closed(self, position):
        """Registered via paper_engine.add_close_listener(). Fires for
        every close regardless of source (manual click, SL/TP hit, or
        the AI auto-trade executor) — that's the single choke point
        that feeds Orders history, the Journal, and Analytics."""

        try:
            self.orders_manager.record_close(position)
        except Exception as e:
            print(f"orders CSV write error: {e}")

        try:
            confidence = int(market.confidence) if position.source == "AI_AUTO" else None
            strategy = "AI OrderFlow (auto)" if position.source == "AI_AUTO" else "Manual"
            market_context = {
                "market_regime": getattr(market, "market_regime", ""),
                "trend": getattr(self, "_latest_ema_trend", ""),
                "vwap_status": getattr(self, "_latest_vwap_status", ""),
                "delta": round(getattr(market, "delta", 0.0), 2),
                "volume": getattr(self, "_latest_volume", ""),
                "liquidity_pct": f"{getattr(market, 'dom_pressure', 0.0):.1f}%",
            }
            self.journal_manager.record_close(
                position, strategy_used=strategy, ai_confidence=confidence,
                market_context=market_context,
            )
        except Exception as e:
            print(f"journal CSV write error: {e}")

        try:
            self.analytics_engine.recompute()
        except Exception as e:
            print(f"analytics recompute error: {e}")

        self.refresh_history_tabs()

    def _on_auto_trade_executed(self, trade: dict):
        """AutoTradeExecutor fired an actual paper order — render it in
        the 'RECENT TRADES' dashboard widget in real time (section 3
        checklist item 4)."""

        try:
            self.dashboard.trades.add_trade(trade["side"], trade["price"], trade["qty"])
        except Exception as e:
            print(f"recent-trades render error (auto trade): {e}")

    def _on_auto_trade_rejected(self, reason: str):
        """AutoTradeExecutor evaluated a confirmed BUY/SELL signal but
        did not trade it — either a hard broker-level rejection
        (insufficient margin, notional over the leverage cap) or one
        of the pre-trade gates skipping it (fee_unjustified,
        confidence_below_threshold, flip_confidence_below_buffer,
        min_hold_not_met). Surfaced in the Trade Setup panel's warning
        banner so this is never invisible — previously only
        discoverable by opening data/auto_trades_log.csv."""

        try:
            self.dashboard.trade_setup.show_rejection(f"AI Auto-Trade not executed: {reason}")
        except Exception as e:
            print(f"auto-trade rejection banner error: {e}")

    def _on_journal_notes_edited(self, trade_id, notes):
        try:
            self.journal_manager.update_notes(trade_id, notes)
            self.refresh_history_tabs()
        except Exception as e:
            print(f"journal notes save error: {e}")

    def _on_view_report(self, trade_id):
        """Journal tab '📄 View Report' button — build the trade's
        structured HTML report (Date/Market/Strategy/Side/Entry/Exit/
        PnL/AI Score/Trend/VWAP/Delta/CVD/Volume/Liquidity/Psychology
        Score) and show it in a pop-up modal."""

        try:
            record = self.journal_manager.get_record(trade_id)
            if not record:
                print(f"⚠️ view report: no journal record for trade_id={trade_id}")
                return

            html = generate_report_html(record)

            try:
                report_path = self.journal_manager.export_report(trade_id)
            except Exception as e:
                print(f"report export error: {e}")
                report_path = ""

            dialog = TradeReportDialog(
                trade_id, html, record.get("notes", ""),
                report_path=report_path, parent=self.dashboard,
            )
            dialog.notes_saved.connect(self._on_journal_notes_edited)
            dialog.exec()
        except Exception as e:
            print(f"view report error: {e}")

    def refresh_history_tabs(self):
        """Populate ORDERS / JOURNAL / ANALYTICS tabs straight from
        their CSVs — called on launch and again every time a position
        closes or the user switches to one of those tabs."""

        try:
            self.dashboard.orders_tab.set_records(self.orders_manager.load_records())
        except Exception as e:
            print(f"orders tab refresh error: {e}")

        try:
            self.dashboard.journal_tab.set_records(self.journal_manager.load_records())
        except Exception as e:
            print(f"journal tab refresh error: {e}")

        try:
            self.dashboard.analytics_tab.set_metrics(self.analytics_engine.latest_saved())
        except Exception as e:
            print(f"analytics tab refresh error: {e}")

    # -------------------------------------------------------
    # Extended indicators (VWAP / EMA trend / RSI / ATR)
    # -------------------------------------------------------

    def update_indicators(self):

        candles = [
            c for c in self.candle_manager.get_candles()
            if c.close is not None
        ]

        if len(candles) < 15:
            return

        try:
            closes = [c.close for c in candles]

            rsi = calculate_rsi(closes, period=14)
            atr = calculate_atr(candles, period=14)
            trend_data = ema_trend(candles, fast=20, slow=50)
            vwap = calculate_vwap(candles)

            # Cached for the executor bridge in refresh_ui() — ATR
            # drives ATR-based SL/TP there instead of a flat percentage.
            self._latest_atr = atr

            current_price = closes[-1]

            vwap_status = "--"
            if vwap is not None:
                vwap_status = "Above" if current_price >= vwap else "Below"

            atr_level = "--"
            if atr is not None and current_price:
                atr_pct = (atr / current_price) * 100
                if atr_pct < 0.1:
                    atr_level = "Low"
                elif atr_pct < 0.3:
                    atr_level = "Medium"
                else:
                    atr_level = "High"

            trend_text = trend_data["trend"] or "--"

            # Cached for JournalManager.record_close() — the Rich Trade
            # Journal report needs "what was VWAP/Trend/Volume at close
            # time", and this is computed once per tick right here.
            self._latest_ema_trend = trend_text
            self._latest_vwap_status = vwap_status
            self._latest_volume = round(sum(c.volume for c in candles[-20:] if c.volume), 2) if candles else ""

            self.dashboard.ai.update_indicators(
                vwap_status=vwap_status,
                ema_trend=trend_text,
                rsi=rsi,
                atr_level=atr_level,
            )

            # ---- AI Engine: Signal Factor Breakdown (spec section 5) ----
            breakdown = compute_factor_breakdown(
                delta=market.delta,
                buy_strength=market.buy_strength,
                sell_strength=market.sell_strength,
                dom_pressure=market.dom_pressure,
                vwap_status=vwap_status,
                ema_trend=trend_text,
                rsi=rsi,
                confidence=market.confidence,
                signal=market.signal,
            )
            self.dashboard.ai.update_factor_breakdown(breakdown)

        except Exception as e:
            print("indicator update error:", e)