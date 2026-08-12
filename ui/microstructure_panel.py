from PyQt6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel


def _stat(label_text):
    """Small 'label on top, value below' block — same pattern as
    ui/header.py's _stat_block, reused here for the diagnostics grid."""

    box = QVBoxLayout()
    box.setSpacing(2)

    label = QLabel(label_text)
    label.setStyleSheet("QLabel{color:#7b8191; font-size:10px; font-weight:600;}")

    value = QLabel("--")
    value.setStyleSheet("QLabel{color:#e1e4ea; font-size:13px; font-weight:bold;}")
    value.setWordWrap(True)

    box.addWidget(label)
    box.addWidget(value)

    return box, value


class MicrostructurePanel(QWidget):
    """
    'Microstructure Diagnostics' section — surfaces the raw order-book /
    trade-flow / price-reaction features that drive
    core.orderflow_features.OrderFlowFeaturePipeline's entry decisions
    (see core/orderbook_engine.py, core/trade_flow_engine.py,
    core/price_reaction_engine.py), so the numbers behind a
    WAIT / STRONG BUY / STRONG SELL read can be inspected directly on
    the dashboard instead of only being visible after the fact in
    data/microstructure_log.csv (core/microstructure_logger.py).

    Purely a display widget — update_features() is called once per UI
    refresh tick by DashboardController, mirroring how ui/ai_panel.py's
    update_ai() / update_indicators() are driven.
    """

    def __init__(self):
        super().__init__()

        self.setStyleSheet("""
        QWidget{
            background:#131722;
            border:1px solid #1E222D;
            border-radius:8px;
        }
        QLabel#title{
            color:#00FF88;
            font-size:13px;
            font-weight:bold;
            padding:10px 10px 4px 10px;
        }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 8)
        outer.setSpacing(4)

        title = QLabel("🔬 MICROSTRUCTURE DIAGNOSTICS")
        title.setObjectName("title")
        outer.addWidget(title)

        grid = QGridLayout()
        grid.setContentsMargins(10, 0, 10, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        outer.addLayout(grid)

        # (display label, internal key) — two columns, one row per pair
        fields = [
            ("OBI (near)", "obi_near"),
            ("OBI (weighted)", "obi_weighted"),
            ("Bid Added / Cancelled", "bid_flow"),
            ("Ask Added / Cancelled", "ask_flow"),
            ("Bid Pull % / Ask Pull %", "pull_scores"),
            ("Replenishment (Bid/Ask)", "replenishment"),
            ("Spoof Risk (Bid/Ask)", "spoof_risk"),
            ("Delta 1s / 5s / 15s", "delta_fast"),
            ("Delta 30s / 60s", "delta_slow"),
            ("CVD", "cvd"),
            ("Buy % / Sell % Aggression", "aggression"),
            ("Return 1s / 5s", "returns"),
            ("Absorption", "absorption"),
            ("Flow Confirmed", "confirmed"),
            ("Entry Decision", "decision"),
        ]

        self._values = {}
        for i, (label_text, key) in enumerate(fields):
            box, value_label = _stat(label_text)
            grid.addLayout(box, i // 2, i % 2)
            self._values[key] = value_label

        self._default_value_style = "QLabel{color:#e1e4ea; font-size:13px; font-weight:bold;}"

    def _set(self, key, text, color=None):
        label = self._values.get(key)
        if label is None:
            return
        label.setText(text)
        label.setStyleSheet(
            f"QLabel{{color:{color}; font-size:13px; font-weight:bold;}}"
            if color else self._default_value_style
        )

    def update_features(self, book, flow=None, reaction=None, decision=None):
        """
        book:     core.orderbook_engine.BookFeatures (e.g.
                  pipeline.book.latest). Required — nothing is updated
                  if it's missing or not yet valid (book.valid False
                  means bids/asks haven't both been observed yet).
        flow:     core.trade_flow_engine.TradeFlowFeatures (e.g.
                  pipeline.flow.latest), optional.
        reaction: core.price_reaction_engine.PriceReaction (e.g.
                  pipeline.reaction.latest), optional.
        decision: core.orderflow_features.EntryDecision, optional.
        """

        if book is None or not getattr(book, "valid", False):
            return

        def _signed_color(v):
            return "#2ecc71" if v > 0 else ("#e74c3c" if v < 0 else "#e1e4ea")

        self._set("obi_near", f"{book.obi_near:+.2f}", _signed_color(book.obi_near))
        self._set("obi_weighted", f"{book.obi_weighted:+.2f}", _signed_color(book.obi_weighted))
        self._set("bid_flow", f"{book.bid_added:,.1f} / {book.bid_cancelled:,.1f}")
        self._set("ask_flow", f"{book.ask_added:,.1f} / {book.ask_cancelled:,.1f}")
        self._set("pull_scores", f"{book.bid_pull_score:.0%} / {book.ask_pull_score:.0%}")
        self._set(
            "replenishment",
            f"{book.bid_replenishment:,.1f} / {book.ask_replenishment:,.1f}",
        )

        spoof = max(book.spoof_risk_bid, book.spoof_risk_ask)
        spoof_color = "#e74c3c" if spoof >= 0.5 else ("#e67e22" if spoof > 0 else "#e1e4ea")
        self._set(
            "spoof_risk",
            f"{book.spoof_risk_bid:.0%} / {book.spoof_risk_ask:.0%}",
            spoof_color,
        )

        if flow is not None:
            self._set(
                "delta_fast",
                f"{flow.delta_1s:+.1f} / {flow.delta_5s:+.1f} / {flow.delta_15s:+.1f}",
            )
            self._set("delta_slow", f"{flow.delta_30s:+.1f} / {flow.delta_60s:+.1f}")
            self._set("cvd", f"{flow.cvd:+,.1f}", _signed_color(flow.cvd))
            self._set("aggression", f"{flow.buy_aggression:.0%} / {flow.sell_aggression:.0%}")

        if reaction is not None:
            self._set(
                "returns",
                f"{reaction.return_1s * 100:+.3f}% / {reaction.return_5s * 100:+.3f}%",
            )

            absorb_tags = []
            if reaction.buyer_absorption:
                absorb_tags.append("BUYER")
            if reaction.seller_absorption:
                absorb_tags.append("SELLER")
            self._set(
                "absorption",
                " / ".join(absorb_tags) if absorb_tags else "None",
                "#00FF88" if absorb_tags else None,
            )

            confirm_tags = []
            if reaction.buy_confirmed:
                confirm_tags.append("BUY")
            if reaction.sell_confirmed:
                confirm_tags.append("SELL")
            self._set(
                "confirmed",
                " / ".join(confirm_tags) if confirm_tags else "None",
                "#00FF88" if confirm_tags else None,
            )

        if decision is not None:
            side_text = decision.side or "—"
            side_color = (
                "#2ecc71" if decision.side == "LONG"
                else "#e74c3c" if decision.side == "SHORT"
                else "#7b8191"
            )
            confirmed_tag = " (confirmed)" if getattr(decision, "confirmed", False) else ""
            self._set(
                "decision",
                f"{side_text} {decision.confidence:.0f}%{confirmed_tag} — {decision.reason}",
                side_color,
            )
