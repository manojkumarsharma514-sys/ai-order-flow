"""
trading/exit_manager.py

ExitManager
-----------
Phase 1 of the 3-phase improvement plan (see audit: 87/99 trades closed
via ai_signal_flip, median hold 4.27 min, 76.5% of total loss was fee
drag from over-trading). This class adds two hard gates in front of
any AI-driven flip-close, called from AutoTradeExecutor.evaluate()
before it's allowed to close an open AI_AUTO position on an opposite
signal:

    1. Minimum Hold Time Guard
       An opposite-direction signal cannot flip-close a position until
       it has been open for >= min_hold_minutes. Blocked flips are
       logged as SIGNAL_BLOCKED_MIN_HOLD; the existing position stays
       open and untouched.

    2. Flip-Confidence Buffer
       Even after the minimum hold has elapsed, the incoming opposite
       signal's confidence must exceed the position's own entry
       confidence by >= flip_confidence_delta percentage points.
       Blocked flips are logged as SIGNAL_BLOCKED_LOW_CONFIDENCE.

Neither gate touches Stop Loss / Take Profit — those are enforced
independently and continuously by PaperTradingEngine.mark_to_market()
on every tick, regardless of what this class decides. A position that
ExitManager keeps open can still close normally via SL/TP hit; this
class only ever blocks or allows the *ai_signal_flip* exit path.

Deliberately has zero Qt/PyQt dependency (no signals, no QObject) so
it can be unit-tested standalone and reused outside the dashboard
event loop if needed — AutoTradeExecutor owns one instance and calls
into it synchronously from evaluate().
"""

import csv
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

FLIP_LOG_PATH = Path("data") / "flip_decisions_log.csv"
FLIP_LOG_COLUMNS = [
    "timestamp", "position_id", "symbol", "side", "opposite_signal_side",
    "decision", "reason", "duration_seconds", "min_hold_seconds_required",
    "entry_confidence", "new_confidence", "confidence_delta",
    "flip_confidence_delta_required",
]

logger = logging.getLogger("trading.exit_manager")
if not logger.handlers:
    # Standalone formatter so these decisions are readable in the
    # console/app log even if the host app hasn't configured logging
    # itself — mirrors the structured detail the CSV row carries.
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


@dataclass
class FlipDecision:
    """Result of ExitManager.evaluate_flip() — everything the caller
    (AutoTradeExecutor) needs to either proceed with the flip or skip
    it and keep the existing position open."""

    allowed: bool
    reason: str                     # "flip_approved" | "SIGNAL_BLOCKED_MIN_HOLD" | "SIGNAL_BLOCKED_LOW_CONFIDENCE"
    duration_seconds: float
    min_hold_seconds_required: float
    entry_confidence: Optional[float]
    new_confidence: float
    confidence_delta: Optional[float]
    flip_confidence_delta_required: float


def _resolve_setting(env_var: str, explicit, config_key: str, default: float,
                      config_dict: Optional[dict] = None) -> float:
    """
    Resolution order, highest priority first:
        1. Explicit constructor argument (caller passed a value directly)
        2. Environment variable (e.g. MIN_HOLD_MINUTES=20)
        3. config/settings.json, if a config_dict was supplied
        4. Hard-coded default

    Lets the guard be tuned per the task's "configurable via
    environment/config file" requirement without needing a restart-free
    reload mechanism — env var and config file are both checked once at
    construction time.
    """

    if explicit is not None:
        return float(explicit)

    env_val = os.environ.get(env_var)
    if env_val is not None:
        try:
            return float(env_val)
        except ValueError:
            logger.warning(
                "Invalid %s=%r in environment, ignoring and falling back",
                env_var, env_val,
            )

    if config_dict is not None and config_key in config_dict and config_dict[config_key] is not None:
        try:
            return float(config_dict[config_key])
        except (TypeError, ValueError):
            pass

    return float(default)


class ExitManager:

    DEFAULT_MIN_HOLD_MINUTES = 15.0
    DEFAULT_FLIP_CONFIDENCE_DELTA = 15.0

    def __init__(self, min_hold_minutes: float = None, flip_confidence_delta: float = None,
                 config_dict: dict = None, log_path: Path = FLIP_LOG_PATH):
        """
        min_hold_minutes / flip_confidence_delta: explicit overrides,
        highest priority. Leave None to resolve from environment
        variables (MIN_HOLD_MINUTES, FLIP_CONFIDENCE_DELTA) or
        config_dict (typically core.config.ConfigManager().load()),
        falling back to the class defaults above.
        """

        self.min_hold_minutes = _resolve_setting(
            env_var="MIN_HOLD_MINUTES", explicit=min_hold_minutes,
            config_key="min_hold_minutes", default=self.DEFAULT_MIN_HOLD_MINUTES,
            config_dict=config_dict,
        )
        self.flip_confidence_delta = _resolve_setting(
            env_var="FLIP_CONFIDENCE_DELTA", explicit=flip_confidence_delta,
            config_key="flip_confidence_delta", default=self.DEFAULT_FLIP_CONFIDENCE_DELTA,
            config_dict=config_dict,
        )

        self.log_path = Path(log_path)
        self._ensure_log_file()

        logger.info(
            "ExitManager initialized: min_hold_minutes=%.1f flip_confidence_delta=%.1f",
            self.min_hold_minutes, self.flip_confidence_delta,
        )

    # ------------------------------------------------------------
    # Runtime reconfiguration (e.g. from the Settings tab, if wired up)
    # ------------------------------------------------------------

    def set_min_hold_minutes(self, minutes: float):
        self.min_hold_minutes = max(0.0, float(minutes))
        logger.info("min_hold_minutes updated -> %.1f", self.min_hold_minutes)

    def set_flip_confidence_delta(self, delta: float):
        self.flip_confidence_delta = max(0.0, float(delta))
        logger.info("flip_confidence_delta updated -> %.1f", self.flip_confidence_delta)

    # ------------------------------------------------------------
    # Core decision
    # ------------------------------------------------------------

    def evaluate_flip(self, position, new_side: str, new_confidence: float,
                       now: datetime = None) -> FlipDecision:
        """
        position:       the currently open trading.positions.Position
                         that an opposite-direction signal wants to
                         close (source == "AI_AUTO", side == opposite
                         of new_side — the caller is responsible for
                         only calling this when that's already true).
        new_side:       "LONG" | "SHORT" — the side of the INCOMING
                         opposite signal that would replace `position`.
        new_confidence: orderflow_engine.confidence at the moment of
                         evaluation (raw float, not the UI's
                         truncated/rounded display value).
        now:            injectable for testing; defaults to
                         datetime.now().

        Returns a FlipDecision. Does NOT close or open anything itself
        — purely a decision function. The caller (AutoTradeExecutor)
        acts on `.allowed`. Every call is logged, both via the CSV
        audit trail and the module logger, whether allowed or blocked.
        """

        now = now or datetime.now()

        opened_at = getattr(position, "opened_at", None)
        duration_seconds = (now - opened_at).total_seconds() if opened_at else 0.0
        min_hold_seconds_required = self.min_hold_minutes * 60.0

        entry_confidence = getattr(position, "entry_confidence", None)
        confidence_delta = (
            (new_confidence - entry_confidence) if entry_confidence is not None else None
        )

        # ---- Gate 1: Minimum Hold Time ----
        if duration_seconds < min_hold_seconds_required:
            decision = FlipDecision(
                allowed=False,
                reason="SIGNAL_BLOCKED_MIN_HOLD",
                duration_seconds=duration_seconds,
                min_hold_seconds_required=min_hold_seconds_required,
                entry_confidence=entry_confidence,
                new_confidence=new_confidence,
                confidence_delta=confidence_delta,
                flip_confidence_delta_required=self.flip_confidence_delta,
            )
            self._log(position, new_side, decision)
            return decision

        # ---- Gate 2: Flip-Confidence Buffer ----
        # A position with no recorded entry_confidence (e.g. a manual
        # trade that later gets flip-evaluated) can't have a
        # confidence delta computed — fail safe by blocking the flip
        # rather than allowing it on an undefined comparison.
        if entry_confidence is None or confidence_delta < self.flip_confidence_delta:
            decision = FlipDecision(
                allowed=False,
                reason="SIGNAL_BLOCKED_LOW_CONFIDENCE",
                duration_seconds=duration_seconds,
                min_hold_seconds_required=min_hold_seconds_required,
                entry_confidence=entry_confidence,
                new_confidence=new_confidence,
                confidence_delta=confidence_delta,
                flip_confidence_delta_required=self.flip_confidence_delta,
            )
            self._log(position, new_side, decision)
            return decision

        # ---- Both gates cleared ----
        decision = FlipDecision(
            allowed=True,
            reason="flip_approved",
            duration_seconds=duration_seconds,
            min_hold_seconds_required=min_hold_seconds_required,
            entry_confidence=entry_confidence,
            new_confidence=new_confidence,
            confidence_delta=confidence_delta,
            flip_confidence_delta_required=self.flip_confidence_delta,
        )
        self._log(position, new_side, decision)
        return decision

    # ------------------------------------------------------------
    # Structured logging — console/log file AND CSV audit trail
    # ------------------------------------------------------------

    def _log(self, position, new_side: str, decision: FlipDecision):

        position_id = getattr(position, "id", "?")
        symbol = getattr(position, "symbol", "?")
        side = getattr(position, "side", "?")

        if decision.allowed:
            logger.info(
                "FLIP_APPROVED position_id=%s symbol=%s side=%s->%s "
                "duration=%.1fs (>=%.0fs required) "
                "entry_conf=%s new_conf=%.1f delta=%s (>=%.1f required)",
                position_id, symbol, side, new_side,
                decision.duration_seconds, decision.min_hold_seconds_required,
                f"{decision.entry_confidence:.1f}" if decision.entry_confidence is not None else "?",
                decision.new_confidence,
                f"{decision.confidence_delta:.1f}" if decision.confidence_delta is not None else "?",
                decision.flip_confidence_delta_required,
            )
        elif decision.reason == "SIGNAL_BLOCKED_MIN_HOLD":
            logger.info(
                "SIGNAL_BLOCKED_MIN_HOLD position_id=%s symbol=%s side=%s "
                "opposite_signal=%s duration=%.1fs (< %.0fs required, %.1fs remaining) "
                "-> keeping existing position open, SL/TP unaffected",
                position_id, symbol, side, new_side,
                decision.duration_seconds, decision.min_hold_seconds_required,
                max(0.0, decision.min_hold_seconds_required - decision.duration_seconds),
            )
        else:  # SIGNAL_BLOCKED_LOW_CONFIDENCE
            logger.info(
                "SIGNAL_BLOCKED_LOW_CONFIDENCE position_id=%s symbol=%s side=%s "
                "opposite_signal=%s duration=%.1fs entry_conf=%s new_conf=%.1f "
                "delta=%s (< %.1f required) -> keeping existing position open, SL/TP unaffected",
                position_id, symbol, side, new_side,
                decision.duration_seconds,
                f"{decision.entry_confidence:.1f}" if decision.entry_confidence is not None else "?",
                decision.new_confidence,
                f"{decision.confidence_delta:.1f}" if decision.confidence_delta is not None else "?",
                decision.flip_confidence_delta_required,
            )

        self._append_csv_row(position_id, symbol, side, new_side, decision)

    def _ensure_log_file(self):
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.log_path.exists():
            with open(self.log_path, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(FLIP_LOG_COLUMNS)

    def _append_csv_row(self, position_id, symbol, side, new_side, decision: FlipDecision):
        self._ensure_log_file()
        with open(self.log_path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                datetime.now().isoformat(sep=" ", timespec="seconds"),
                position_id,
                symbol,
                side,
                new_side,
                "ALLOWED" if decision.allowed else "BLOCKED",
                decision.reason,
                round(decision.duration_seconds, 1),
                round(decision.min_hold_seconds_required, 1),
                decision.entry_confidence,
                decision.new_confidence,
                decision.confidence_delta,
                decision.flip_confidence_delta_required,
            ])