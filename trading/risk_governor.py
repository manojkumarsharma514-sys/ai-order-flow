"""
trading/risk_governor.py

RiskGovernor
------------
Phase 2 of the 3-phase improvement plan. Audit baseline: 117 legacy
trades (pre-Phase-1) lost -$7,671.69 with no daily loss limit or
consecutive-loss circuit breaker anywhere in the codebase — a losing
streak could run indefinitely within a session. This class adds that
missing backstop:

    1. Daily Loss Limit
       Once realized PnL for the current calendar day reaches
       -max_daily_loss_usd, all further AI auto-trading is blocked
       until the day rolls over (local midnight). Manual trading and
       existing open positions' SL/TP are completely unaffected — this
       only blocks AutoTradeExecutor from opening new AI_AUTO positions.

    2. Max Consecutive Losses
       Once `max_consecutive_losses` losing trades have closed in a
       row (any win resets the counter to 0), auto-trading is blocked
       for the remainder of the day.

Both counters reset automatically at the first check/update after
local midnight — no separate scheduler needed.

Self-contained: `AutoTradeExecutor` registers `on_trade_closed` as a
PaperTradingEngine close-listener directly (via `paper_engine.
add_close_listener`), so RiskGovernor sees every close — manual, SL/TP,
or AI_AUTO — the same way Orders/Journal/Analytics already do. Only
AI_AUTO-sourced closes count toward the streak/daily-loss figures,
since a manual trade going wrong shouldn't silently disable the bot
(and vice versa: this governor only ever blocks *auto* trading, so
whether manual closes count doesn't change what it's protecting).

Zero Qt/PyQt dependency, same as ExitManager — plain Python + logging
+ CSV audit trail, easy to unit test and reuse outside the dashboard
event loop.
"""

import csv
import logging
import os
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Optional

GOVERNOR_LOG_PATH = Path("data") / "risk_governor_log.csv"
GOVERNOR_LOG_COLUMNS = [
    "timestamp", "event", "trading_day", "daily_pnl_usd", "consecutive_losses",
    "max_daily_loss_usd", "max_consecutive_losses", "blocked", "reason",
]

logger = logging.getLogger("trading.risk_governor")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


@dataclass
class GovernorDecision:
    allowed: bool
    reason: str  # "trading_allowed" | "CIRCUIT_BREAKER_DAILY_LOSS_LIMIT" | "CIRCUIT_BREAKER_MAX_CONSECUTIVE_LOSSES"
    daily_pnl_usd: float
    consecutive_losses: int


def _resolve_setting(env_var: str, explicit, config_key: str, default: float,
                      config_dict: Optional[dict] = None) -> float:
    """Same resolution order as trading.exit_manager._resolve_setting:
    explicit arg > env var > config_dict > hard-coded default."""

    if explicit is not None:
        return float(explicit)

    env_val = os.environ.get(env_var)
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            logger.warning("Invalid %s=%r in environment, ignoring", env_var, env_val)

    if config_dict is not None and config_key in config_dict and config_dict[config_key] is not None:
        try:
            return float(config_dict[config_key])
        except (TypeError, ValueError):
            pass

    return float(default)


class RiskGovernor:

    DEFAULT_MAX_DAILY_LOSS_USD = 300.0
    DEFAULT_MAX_CONSECUTIVE_LOSSES = 4

    def __init__(self, max_daily_loss_usd: float = None, max_consecutive_losses: float = None,
                 config_dict: dict = None, log_path: Path = GOVERNOR_LOG_PATH):

        self.max_daily_loss_usd = _resolve_setting(
            env_var="MAX_DAILY_LOSS_USD", explicit=max_daily_loss_usd,
            config_key="max_daily_loss_usd", default=self.DEFAULT_MAX_DAILY_LOSS_USD,
            config_dict=config_dict,
        )
        self.max_consecutive_losses = int(_resolve_setting(
            env_var="MAX_CONSECUTIVE_LOSSES", explicit=max_consecutive_losses,
            config_key="max_consecutive_losses", default=self.DEFAULT_MAX_CONSECUTIVE_LOSSES,
            config_dict=config_dict,
        ))

        self.log_path = Path(log_path)
        self._ensure_log_file()

        self._trading_day = date.today()
        self.daily_pnl = 0.0
        self.consecutive_losses = 0

        logger.info(
            "RiskGovernor initialized: max_daily_loss_usd=%.2f max_consecutive_losses=%d",
            self.max_daily_loss_usd, self.max_consecutive_losses,
        )

    # ------------------------------------------------------------
    # Runtime reconfiguration (pushed from Settings load/save, mirrors
    # ExitManager.set_min_hold_minutes / set_flip_confidence_delta)
    # ------------------------------------------------------------

    def set_max_daily_loss_usd(self, value: float):
        self.max_daily_loss_usd = max(0.0, float(value))
        logger.info("max_daily_loss_usd updated -> %.2f", self.max_daily_loss_usd)

    def set_max_consecutive_losses(self, value: int):
        self.max_consecutive_losses = max(0, int(value))
        logger.info("max_consecutive_losses updated -> %d", self.max_consecutive_losses)

    # ------------------------------------------------------------
    # Daily rollover
    # ------------------------------------------------------------

    def _maybe_roll_day(self, today: date = None):
        today = today or date.today()
        if today != self._trading_day:
            logger.info(
                "New trading day (%s -> %s) — resetting daily_pnl and consecutive_losses",
                self._trading_day, today,
            )
            self._trading_day = today
            self.daily_pnl = 0.0
            self.consecutive_losses = 0

    # ------------------------------------------------------------
    # Core checks — called by AutoTradeExecutor.evaluate()
    # ------------------------------------------------------------

    def trading_allowed(self) -> GovernorDecision:
        self._maybe_roll_day()

        if self.daily_pnl <= -self.max_daily_loss_usd:
            decision = GovernorDecision(
                allowed=False, reason="CIRCUIT_BREAKER_DAILY_LOSS_LIMIT",
                daily_pnl_usd=self.daily_pnl, consecutive_losses=self.consecutive_losses,
            )
            self._log("CHECK_BLOCKED", decision)
            return decision

        if self.consecutive_losses >= self.max_consecutive_losses:
            decision = GovernorDecision(
                allowed=False, reason="CIRCUIT_BREAKER_MAX_CONSECUTIVE_LOSSES",
                daily_pnl_usd=self.daily_pnl, consecutive_losses=self.consecutive_losses,
            )
            self._log("CHECK_BLOCKED", decision)
            return decision

        return GovernorDecision(
            allowed=True, reason="trading_allowed",
            daily_pnl_usd=self.daily_pnl, consecutive_losses=self.consecutive_losses,
        )

    # ------------------------------------------------------------
    # Position-close hook — register directly with
    # PaperTradingEngine.add_close_listener() so this sees every close
    # (manual, SL/TP, or AI_AUTO) the same way Orders/Journal do.
    # ------------------------------------------------------------

    def on_position_closed(self, position):
        """Only AI_AUTO closes count toward the streak/daily-loss
        figures this governor protects — a manual trade's outcome
        shouldn't silently disable or re-enable the automated system."""

        if getattr(position, "source", None) != "AI_AUTO":
            return

        pnl = getattr(position, "realized_pnl", None)
        if pnl is None:
            return

        self.on_trade_closed(float(pnl))

    def on_trade_closed(self, pnl_usd: float):
        self._maybe_roll_day()

        self.daily_pnl += pnl_usd
        self.consecutive_losses = self.consecutive_losses + 1 if pnl_usd < 0 else 0

        logger.info(
            "Trade closed: pnl=%.2f -> daily_pnl=%.2f consecutive_losses=%d/%d",
            pnl_usd, self.daily_pnl, self.consecutive_losses, self.max_consecutive_losses,
        )
        self._log("TRADE_CLOSED", GovernorDecision(
            allowed=True, reason="trade_recorded",
            daily_pnl_usd=self.daily_pnl, consecutive_losses=self.consecutive_losses,
        ))

    # ------------------------------------------------------------
    # Structured logging — console/log AND CSV audit trail
    # ------------------------------------------------------------

    def _log(self, event: str, decision: GovernorDecision):
        if event == "CHECK_BLOCKED":
            logger.warning(
                "%s: daily_pnl=%.2f (limit -%.2f) consecutive_losses=%d (limit %d)",
                decision.reason, decision.daily_pnl_usd, self.max_daily_loss_usd,
                decision.consecutive_losses, self.max_consecutive_losses,
            )
        self._append_csv_row(event, decision)

    def _ensure_log_file(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(GOVERNOR_LOG_COLUMNS)

    def _append_csv_row(self, event: str, decision: GovernorDecision):
        self._ensure_log_file()
        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.now().isoformat(sep=" ", timespec="seconds"),
                event,
                self._trading_day.isoformat(),
                round(decision.daily_pnl_usd, 2),
                decision.consecutive_losses,
                self.max_daily_loss_usd,
                self.max_consecutive_losses,
                not decision.allowed,
                decision.reason,
            ])
