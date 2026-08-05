"""
core/app_state.py

AppStateHandler
---------------
Serializes/restores everything the user expects to "resume exactly
where they left off":

    - AUTO_MODE / AI_AUTO_TRADING toggle states
    - Selected symbol + chart timeframe
    - Active indicator toggles
    - Trade Setup fields (entry/SL/TP/size/RR)
    - Paper/live mode + paper balance

State lives in config/app_state.json. This module only knows how to
read/write that file and how to pull a snapshot dict out of / push a
snapshot dict into the live widget tree — it does not decide *when*
to save (that's Dashboard.closeEvent) or *when* to load (that's
Dashboard.__init__, after the controller exists).
"""

import json
import os
from pathlib import Path

from core.runtime_paths import CONFIG_DIR
APP_STATE_PATH = CONFIG_DIR / "app_state.json"

DEFAULT_STATE = {
    "auto_mode": True,
    "ai_auto_trading": True,
    "symbol": "BTCUSD",
    "timeframe_label": "15m",
    "timeframe_seconds": 900,
    "active_indicators": [],
    "trade_setup": {
        "entry_price": 0.0,
        "stop_loss": 0.0,
        "take_profit": 0.0,
        "size": 1.0,
    },
    "trading_mode": "paper",   # "paper" | "demo" | "live"
    "paper_balance": 10000.0,
}


class AppStateHandler:
    """Static-style helper — no instance state of its own beyond the path."""

    def __init__(self, path: Path = APP_STATE_PATH):
        self.path = Path(path)

    # ------------------------------------------------------------------
    # Low level read / write
    # ------------------------------------------------------------------

    def load_raw(self) -> dict:
        """Read config/app_state.json, falling back to defaults if the
        file doesn't exist yet or is corrupted."""

        if not self.path.exists():
            return dict(DEFAULT_STATE)

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ app_state.json unreadable ({e}) — using defaults")
            return dict(DEFAULT_STATE)

        # merge onto defaults so newly-added keys don't KeyError on an
        # older state file written by a previous app version
        merged = dict(DEFAULT_STATE)
        merged.update(data)
        merged["trade_setup"] = {
            **DEFAULT_STATE["trade_setup"],
            **data.get("trade_setup", {}),
        }
        return merged

    def save_raw(self, state: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        tmp_path = self.path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

        # atomic-ish replace so a crash mid-write can't corrupt the file
        os.replace(tmp_path, self.path)

    # ------------------------------------------------------------------
    # High level: pull a snapshot out of the live UI
    # ------------------------------------------------------------------

    def capture_state(self, dashboard) -> dict:
        """Read the current widget state off `dashboard` (the Dashboard
        QMainWindow) into a plain dict ready for save_raw()."""

        ts = dashboard.trade_setup
        controller = dashboard.controller
        paper_engine = controller.paper_engine

        state = {
            "auto_mode": ts.auto_mode_btn.property("active") == "true",
            "ai_auto_trading": ts.ai_trading_btn.property("active") == "true",
            "symbol": getattr(paper_engine, "symbol", "BTCUSD"),
            "timeframe_label": getattr(dashboard.timeframe, "current_label", "15m"),
            "timeframe_seconds": getattr(
                controller.candle_manager, "timeframe_seconds", 900
            ),
            "active_indicators": sorted(getattr(dashboard, "active_indicators", set())),
            "trade_setup": {
                "entry_price": ts.entry_price.value(),
                "stop_loss": ts.stop_loss.value(),
                "take_profit": ts.take_profit.value(),
                "size": ts.size.value(),
            },
            "trading_mode": getattr(controller, "trading_mode", "paper"),
            "paper_balance": paper_engine.balance,
        }

        return state

    def save_state(self, dashboard) -> None:
        try:
            state = self.capture_state(dashboard)
            self.save_raw(state)
            print(f"💾 App state saved -> {self.path}")
        except Exception as e:
            # Never let a save failure block application shutdown
            print(f"⚠️ Failed to save app state: {e}")

    # ------------------------------------------------------------------
    # High level: push a saved snapshot back into the live UI
    # ------------------------------------------------------------------

    def restore_state(self, dashboard) -> None:
        """Apply config/app_state.json onto `dashboard`. Safe to call
        even if the file doesn't exist (falls back to DEFAULT_STATE,
        which matches the widgets' own hard-coded defaults)."""

        state = self.load_raw()
        ts = dashboard.trade_setup
        controller = dashboard.controller

        try:
            # --- Trade Setup fields ---
            tsd = state.get("trade_setup", {})
            if tsd.get("entry_price"):
                ts.entry_price.setValue(tsd["entry_price"])
            if tsd.get("stop_loss"):
                ts.stop_loss.setValue(tsd["stop_loss"])
            if tsd.get("take_profit"):
                ts.take_profit.setValue(tsd["take_profit"])
            if tsd.get("size"):
                ts.size.setValue(tsd["size"])

            # --- AUTO_MODE / AI_AUTO_TRADING toggles ---
            # _apply_toggle_state flips the button only if the saved
            # value differs from the widget's current default, and
            # (re)emits the signal so downstream UI-locking logic and
            # the executor both pick it up.
            self._apply_toggle_state(
                ts.auto_mode_btn, state.get("auto_mode", True), ts.auto_mode_toggled
            )
            self._apply_toggle_state(
                ts.ai_trading_btn, state.get("ai_auto_trading", True), ts.ai_trading_toggled
            )

            # --- Timeframe ---
            tf_label = state.get("timeframe_label", "15m")
            if hasattr(dashboard.timeframe, "set_timeframe_label"):
                dashboard.timeframe.set_timeframe_label(tf_label)

            # --- Indicators ---
            for code in state.get("active_indicators", []):
                dashboard._on_indicator_toggled(code, code, True)

            # --- Paper balance / trading mode ---
            # starting_balance is a preference owned by config/settings.json
            # ("Starting Paper Balance" in the Settings tab, applied via
            # ConfigManager -> DashboardController._apply_settings_to_live_controls
            # at construction time, before restore_state ever runs). It must
            # NOT be overwritten here — app_state.json only resumes the
            # CURRENT balance from wherever the last session left off; it
            # has no business deciding what a future RESET BALANCE targets.
            # (Previously this also set starting_balance from the same
            # "paper_balance" key, which silently reverted a trader's
            # deliberately-configured Starting Paper Balance back to their
            # last live balance on every relaunch.)
            controller.paper_engine.balance = state.get(
                "paper_balance", controller.paper_engine.balance
            )
            controller.set_account_mode(state.get("trading_mode", "paper"))

            print(f"✅ App state restored from {self.path}")

        except Exception as e:
            print(f"⚠️ Failed to restore app state: {e}")

    @staticmethod
    def _apply_toggle_state(button, saved_value: bool, signal) -> None:
        current_value = button.property("active") == "true"

        if current_value == saved_value:
            # still emit once so listeners (UI lock, executor enable
            # flag) sync to the restored value on startup
            signal.emit(saved_value)
            return

        button.setProperty("active", str(saved_value).lower())
        button.setText("ON" if saved_value else "OFF")
        button.style().unpolish(button)
        button.style().polish(button)
        signal.emit(saved_value)