"""
core/config.py

ConfigManager — persists user *preferences* (as opposed to core/app_state.py,
which persists session/runtime *state* like toggle positions and the
last symbol/timeframe) to config/settings.json:

    - Default Leverage
    - Capital Allocation %  (used by the quick %-size buttons / auto-sizing)
    - Trade Risk %          (% of balance risked per auto-trade)
    - Minimum Hold Time (Phase 1) / Flip-Confidence Buffer (Phase 1)

plus the existing AI Auto Trading risk parameters already exposed in
ui/settings.py, so "Save Settings" persists everything on that screen
in one place.

Separate from AppStateHandler on purpose: app_state.json changes on
every close (it's "where you left off"), while settings.json only
changes when the trader explicitly clicks "Save Settings" — a restart
should never silently overwrite a preference the trader set on purpose.
"""

import json
import os
from pathlib import Path

SETTINGS_PATH = Path("config") / "settings.json"

DEFAULT_SETTINGS = {
    "default_leverage": 25,
    "capital_allocation_pct": 50.0,
    "trade_risk_pct": 2.0,
    "auto_trade_size_btc": 1.0,
    "default_stop_loss_pct": 0.5,
    "default_take_profit_pct": 1.5,
    "min_ai_confidence_pct": 55,
    "cooldown_seconds": 20,

    # Phase 1 — signal-flip execution controls (see trading/exit_manager.py).
    # trading.exit_manager.ExitManager reads these via its config_dict
    # param at construction; environment variables MIN_HOLD_MINUTES /
    # FLIP_CONFIDENCE_DELTA take priority over these if both are set.
    "min_hold_minutes": 15.0,
    "flip_confidence_delta": 15.0,

    # Phase 2 — entry-quality gates + circuit breaker (see
    # trading/executor.py gates 1 & 2, and trading/risk_governor.py).
    "block_sideways_regime": True,
    "min_atr_fee_multiple": 3.0,
    "max_daily_loss_usd": 300.0,
    "max_consecutive_losses": 4,
}


class ConfigManager:

    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = Path(path)

    def load(self) -> dict:
        """Read config/settings.json, merged onto DEFAULT_SETTINGS so a
        file from an older app version (missing newer keys) still
        loads cleanly instead of KeyError-ing."""

        if not self.path.exists():
            return dict(DEFAULT_SETTINGS)

        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ settings.json unreadable ({e}) — using defaults")
            return dict(DEFAULT_SETTINGS)

        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        return merged

    def save(self, settings: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        merged = dict(DEFAULT_SETTINGS)
        merged.update(settings)

        tmp_path = self.path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        os.replace(tmp_path, self.path)

        print(f"💾 Settings saved -> {self.path}")