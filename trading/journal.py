"""
trading/journal.py

JournalManager
--------------
Trading journal persisted to data/trade_journal.csv. Originally this
stored a single free-text `notes` string per trade (things like
"AI Auto-Trade — LONG at 75% confidence"). It now stores a full
structured record of the market context at close time:

    date_time, symbol, side, qty, entry_price, exit_price, pnl_usd,
    pnl_percent, strategy_used, ai_confidence, market_regime, trend,
    vwap_status, delta, cvd, volume, liquidity_pct, psychology_score,
    notes

`trade_id` is prepended (internal-only, not part of the spec'd column
list) so a specific row can be located again — both for the editable
Notes column and for generating that row's HTML report on demand.

Report generation: generate_report_html() renders one trade's full
structured record as a styled, self-contained HTML page (no external
CSS/JS), and JournalManager.export_report() writes it to
data/reports/trade_<id>.html — this is what the Journal tab's
"📄 View Report" button opens.
"""

from pathlib import Path

import pandas as pd

from core.runtime_paths import DATA_DIR
JOURNAL_CSV_PATH = DATA_DIR / "trade_journal.csv"
REPORTS_DIR = DATA_DIR / "reports"

COLUMNS = [
    "trade_id",
    "date_time",
    "symbol",
    "side",
    "qty",
    "entry_price",
    "exit_price",
    "pnl_usd",
    "pnl_percent",
    "strategy_used",
    "ai_confidence",
    "market_regime",
    "trend",
    "vwap_status",
    "delta",
    "cvd",
    "volume",
    "liquidity_pct",
    "psychology_score",
    "notes",
]


class JournalManager:

    def __init__(self, path: Path = JOURNAL_CSV_PATH):
        self.path = Path(path)
        self._ensure_file()
        # Running Cumulative Volume Delta across every trade this
        # JournalManager has recorded — a proper CVD needs continuous
        # tick-level delta, which isn't persisted elsewhere yet, so
        # this is an approximation seeded at each recorded close.
        self._cvd_running_total = 0.0

    def _ensure_file(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            pd.DataFrame(columns=COLUMNS).to_csv(self.path, index=False)

    # ------------------------------------------------------------
    # Writing — called from a PaperTradingEngine close-listener
    # ------------------------------------------------------------

    def record_close(self, position, strategy_used="AI OrderFlow", ai_confidence=None,
                      notes=None, market_context=None):
        """
        market_context: optional dict with any of
            market_regime, trend, vwap_status, delta, volume, liquidity_pct
        — everything the controller already computes each tick for the
        AI Engine panel (core.orderflow_engine "market" + the VWAP/EMA/
        RSI indicators), passed straight through so the journal reflects
        the actual conditions the trade was made under.
        """

        market_context = market_context or {}

        if notes is None or str(notes).strip() == "":
            if strategy_used and "AI" in str(strategy_used).upper():
                if ai_confidence is not None:
                    notes = f"AI Auto-Trade — {position.side} at {ai_confidence}% confidence"
                else:
                    notes = "AI Auto-Trade"
            else:
                notes = "Manual trade"

        delta = market_context.get("delta", 0.0) or 0.0
        self._cvd_running_total += delta

        # Simple discipline heuristic, not a clinical measure: how far
        # the AI's own confidence was from a coin-flip (50%) at the
        # moment of entry — a higher-conviction signal followed through
        # scores higher. Manual trades have no AI confidence to derive
        # this from, so they're left blank rather than guessed at.
        psychology_score = ""
        if ai_confidence is not None:
            psychology_score = round(min(100.0, abs(float(ai_confidence) - 50) * 2), 1)

        row = {
            "trade_id": position.id,
            "date_time": (position.closed_at or position.opened_at).isoformat(sep=" ", timespec="seconds"),
            "symbol": position.symbol,
            "side": position.side,
            "qty": position.size,
            "entry_price": position.entry_price,
            "exit_price": position.exit_price,
            "pnl_usd": round(position.realized_pnl, 4) if position.realized_pnl is not None else "",
            "pnl_percent": round(position.unrealized_pnl_pct(), 4),
            "strategy_used": strategy_used,
            "ai_confidence": ai_confidence if ai_confidence is not None else "",
            "market_regime": market_context.get("market_regime", ""),
            "trend": market_context.get("trend", ""),
            "vwap_status": market_context.get("vwap_status", ""),
            "delta": delta,
            "cvd": round(self._cvd_running_total, 2),
            "volume": market_context.get("volume", ""),
            "liquidity_pct": market_context.get("liquidity_pct", ""),
            "psychology_score": psychology_score,
            "notes": notes,
        }

        self._ensure_file()
        pd.DataFrame([row], columns=COLUMNS).to_csv(
            self.path, mode="a", header=False, index=False
        )
        return row

    # ------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------

    def load_all(self) -> pd.DataFrame:
        self._ensure_file()
        try:
            df = pd.read_csv(self.path)
        except pd.errors.EmptyDataError:
            df = pd.DataFrame(columns=COLUMNS)
        return self._clean(df)

    @staticmethod
    def _clean(df: pd.DataFrame) -> pd.DataFrame:
        """
        Replace NaN / None values left behind by the pandas CSV
        round-trip with a clean empty string, so no cell — the Notes
        column especially — ever renders the literal text 'nan' in the
        Journal tab. A blank CSV cell (e.g. notes="" written at close
        time) reads back as float NaN by default, which str()'s to
        'nan' if passed straight through to the UI.
        """

        if df.empty:
            return df

        return df.where(pd.notnull(df), "")

    def load_records(self) -> list:
        df = self.load_all().sort_values("date_time", ascending=False)
        return df.to_dict(orient="records")

    def get_record(self, trade_id) -> dict:
        df = self.load_all()
        if df.empty:
            return {}
        matches = df[df["trade_id"].astype(str) == str(trade_id)]
        if matches.empty:
            return {}
        return matches.iloc[0].to_dict()

    # ------------------------------------------------------------
    # Editable Notes column — rewrite one row's notes back to disk
    # ------------------------------------------------------------

    def update_notes(self, trade_id, notes: str) -> bool:
        df = self.load_all()

        if df.empty or "trade_id" not in df.columns:
            return False

        mask = df["trade_id"].astype(str) == str(trade_id)
        if not mask.any():
            return False

        df.loc[mask, "notes"] = notes
        df.to_csv(self.path, index=False)
        return True

    # ------------------------------------------------------------
    # Rich HTML trade report ("📄 View Report" button in the Journal tab)
    # ------------------------------------------------------------

    def export_report(self, trade_id) -> str:
        """Render the given trade's structured record as a styled HTML
        file under data/reports/ and return its path."""

        record = self.get_record(trade_id)
        if not record:
            raise ValueError(f"No journal record found for trade_id={trade_id}")

        html = generate_report_html(record)

        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = REPORTS_DIR / f"trade_{trade_id}.html"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html)

        return str(report_path)


def generate_report_html(record: dict) -> str:
    """Self-contained (no external CSS/JS) HTML trade report covering
    every field in the structured journal record: Date, Market,
    Strategy, Side, Entry, Exit, PnL, AI Score, Trend, VWAP, Delta,
    CVD, Volume, Liquidity, Psychology Score."""

    def g(key, default="—"):
        val = record.get(key, "")
        if val == "" or val is None or (isinstance(val, float) and val != val):
            return default
        return val

    side = g("side", "")
    side_color = "#2ecc71" if side == "LONG" else "#e74c3c"

    pnl = g("pnl_usd", 0)
    try:
        pnl_val = float(pnl)
    except (TypeError, ValueError):
        pnl_val = 0.0
    pnl_color = "#2ecc71" if pnl_val >= 0 else "#e74c3c"

    def row(label, value):
        return f"""
        <tr>
          <td class="label">{label}</td>
          <td class="value">{value}</td>
        </tr>"""

    rows = "".join([
        row("Date / Time", g("date_time")),
        row("Market", g("symbol")),
        row("Strategy", g("strategy_used")),
        row("Side", f'<span style="color:{side_color}; font-weight:bold;">{side}</span>'),
        row("Entry Price", g("entry_price")),
        row("Exit Price", g("exit_price")),
        row("PnL ($)", f'<span style="color:{pnl_color}; font-weight:bold;">{pnl_val:,.2f}</span>'),
        row("PnL (%)", g("pnl_percent")),
        row("AI Score / Confidence", f"{g('ai_confidence')}%" if g("ai_confidence") != "—" else "—"),
        row("Trend", g("trend")),
        row("Market Regime", g("market_regime")),
        row("VWAP", g("vwap_status")),
        row("Delta", g("delta")),
        row("CVD (Cumulative Volume Delta)", g("cvd")),
        row("Volume", g("volume")),
        row("Liquidity", g("liquidity_pct")),
        row("Psychology Score", g("psychology_score")),
    ])

    notes = g("notes", "")

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Trade Report — {g('symbol')} {side} #{g('trade_id')}</title>
<style>
  body {{
    background:#0b0e14; color:#e1e4ea; font-family:'Segoe UI', Arial, sans-serif;
    margin:0; padding:24px;
  }}
  .card {{
    max-width:640px; margin:0 auto; background:#131722; border:1px solid #1E222D;
    border-radius:10px; padding:24px;
  }}
  h1 {{ color:#00FF88; font-size:18px; margin:0 0 4px 0; }}
  .subtitle {{ color:#7b8191; font-size:12px; margin-bottom:18px; }}
  table {{ width:100%; border-collapse:collapse; }}
  td {{ padding:8px 6px; border-bottom:1px solid #1E222D; font-size:13px; }}
  td.label {{ color:#7b8191; width:45%; }}
  td.value {{ color:#e1e4ea; font-weight:600; text-align:right; }}
  .notes {{
    margin-top:18px; padding:12px; background:#0b0e14; border:1px solid #1E222D;
    border-radius:6px; color:#c7cbd6; font-size:13px; line-height:1.5;
  }}
  .notes-label {{ color:#00FF88; font-weight:bold; font-size:12px; margin-bottom:6px; }}
</style>
</head>
<body>
  <div class="card">
    <h1>📄 Trade Report — {g('symbol')} {side}</h1>
    <div class="subtitle">Trade ID #{g('trade_id')}</div>
    <table>
      {rows}
    </table>
    <div class="notes">
      <div class="notes-label">Notes</div>
      {notes}
    </div>
  </div>
</body>
</html>"""
