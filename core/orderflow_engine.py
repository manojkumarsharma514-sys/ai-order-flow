from collections import deque
import time


class OrderFlowEngine:


    def __init__(self):

        self.trades = deque(maxlen=200)

        self.buy_volume = 0
        self.sell_volume = 0

        self.delta = 0

        self.last_price=None
        self.price_change=0


        self.bid_liquidity=0
        self.ask_liquidity=0

        self.dom_pressure=0


        self.volume_spike=False

        self.whale=False

        self.absorption=False

        self.smart_money="NORMAL"

        self.signal="WAIT"

        # ------------------------------------------------------------
        # Signal persistence ("confirmed_signal")
        # ------------------------------------------------------------
        # `self.signal` above is recomputed from scratch on every single
        # trade tick and can flip between STRONG BUY / WATCH / WAIT /
        # ABSORPTION multiple times per second on a noisy tape — that's
        # fine for the dashboard's live AI ENGINE readout, which
        # repaints every tick anyway, but it's *not* fine for anything
        # that only samples the signal periodically (AutoTradeExecutor
        # is polled once every 250ms by the UI timer in
        # controller/dashboard_controller.py). A STRONG BUY/SELL that's
        # only "true" for one or two ticks (often well under 250ms on a
        # fast tape) can flicker in and out between polls and simply
        # never get seen by the executor at all — which is exactly what
        # was happening: STRONG SELL fired in the raw engine, but
        # data/auto_trades_log.csv never got a row for it, because by
        # the time evaluate() ran, self.signal had already reverted.
        #
        # `confirmed_signal` fixes this: once an actionable signal
        # (STRONG BUY / STRONG SELL) fires, it's HELD at that value for
        # `signal_hold_seconds` seconds regardless of what self.signal
        # does tick-to-tick in the meantime, giving a 250ms poller ~12
        # chances to catch it before it reverts to WAIT. A *new*
        # actionable signal (including the opposite direction) always
        # immediately overrides and restarts the hold — it never masks
        # a fresh flip, only bridges the gaps between an executor's
        # polling interval and this engine's per-tick recompute.
        self.confirmed_signal = "WAIT"
        self.signal_hold_seconds = 3.0
        self._last_actionable_signal_time = None

        self.price=0

        self.confidence=0

        self.buy_strength=0
        self.sell_strength=0

        self.market_regime="UNKNOWN"



    # ==================================
    # EVENT ROUTER
    # ==================================

    def process(self,data):


        if data["event"]=="trade":

            self.process_trade(data)


        elif data["event"]=="orderbook":

            self.process_orderbook(data)





    # ==================================
    # TRADE ENGINE
    # ==================================

    def process_trade(self,data):


        price=float(data["price"])
        size=float(data["size"])



        if self.last_price:

            self.price_change=price-self.last_price



        self.last_price=price



        buyer = data.get("buyer_role")
        seller = data.get("seller_role")

        side = None
        if buyer == "taker":
            side = "buy"
        elif seller == "taker":
            side = "sell"

        self.trades.append({

            "price":price,
            "size":size,
            "time":time.time(),
            "side":side,

        })



        # Recompute from the rolling `self.trades` window (capped at
        # maxlen=200) instead of accumulating buy_volume/sell_volume/
        # delta forever from app launch. An unbounded cumulative total
        # (a) eventually swamps every score derived from it, so signal
        # factor bars saturate to fully empty/full instead of tracking
        # what's actually happening right now, and (b) makes the AI
        # Signal / Confidence gauge steadily "stickier" the longer a
        # session runs, since new trades get diluted by an ever-larger
        # historical base.
        self.buy_volume = sum(t["size"] for t in self.trades if t["side"] == "buy")
        self.sell_volume = sum(t["size"] for t in self.trades if t["side"] == "sell")
        self.delta = self.buy_volume - self.sell_volume



        self.calculate()





    # ==================================
    # ORDERBOOK ENGINE
    # ==================================

    def process_orderbook(self,data):


        bids=data.get("bids",[])
        asks=data.get("asks",[])


        bid=0
        ask=0



        for x in bids[:50]:

            try:

                if isinstance(x,dict):

                    bid+=float(x.get("size",0))

                else:

                    bid+=float(x[1])

            except:

                pass



        for x in asks[:50]:

            try:

                if isinstance(x,dict):

                    ask+=float(x.get("size",0))

                else:

                    ask+=float(x[1])

            except:

                pass



        self.bid_liquidity=bid
        self.ask_liquidity=ask



        total=bid+ask


        if total:


            self.dom_pressure=(

                (bid-ask)/total

            )*100






    # ==================================
    # AI MODEL
    # ==================================

    def calculate(self):


        total=self.buy_volume+self.sell_volume


        if total==0:

            return



        buy_flow=(self.buy_volume/total)*100

        sell_flow=(self.sell_volume/total)*100

        self.buy_strength=buy_flow
        self.sell_strength=sell_flow

        if self.last_price is not None:
            self.price=self.last_price




        # volume detection


        avg=sum(

            t["size"] for t in self.trades

        ) / max(len(self.trades),1)



        current=self.trades[-1]["size"]



        self.volume_spike=False


        if current > avg*3:

            self.volume_spike=True






        # whale detection


        self.whale=False


        if current>50:


            self.whale=True



            if buy_flow>60:

                self.smart_money="WHALE BUY"


            elif sell_flow>60:

                self.smart_money="WHALE SELL"







        # absorption


        self.absorption=False



        if self.volume_spike and self.whale:


            if abs(self.price_change)<2:


                self.absorption=True







        buy_score=0
        sell_score=0




        # ==========================
        # BUY LOGIC
        # ==========================


        if buy_flow>60:

            buy_score+=25


        if self.delta>0:

            buy_score+=20



        if self.price_change>=0:

            buy_score+=10



        if self.volume_spike:

            buy_score+=20



        if self.whale and buy_flow>60:

            buy_score+=20




        # ignore fake sell wall


        if self.dom_pressure>20:

            buy_score+=10





        # ==========================
        # SELL LOGIC
        # ==========================


        if sell_flow>60:

            sell_score+=25


        if self.delta<0:

            sell_score+=20



        if self.price_change<=0:

            sell_score+=10



        if self.volume_spike:

            sell_score+=20



        if self.whale and sell_flow>60:

            sell_score+=20




        if self.dom_pressure<-20:

            sell_score+=10






        confidence=max(

            buy_score,
            sell_score

        )

        # buy_score/sell_score are an unbounded sum of additive
        # factors (up to 105 when every factor fires at once, as seen
        # in the console log — e.g. "CONFIDENCE: 105%"). Clamped here
        # so nothing downstream (gauges, the executor's confidence
        # threshold/flip-buffer comparisons) ever sees a > 100 value.
        confidence = min(confidence, 100)



        signal="WAIT"



        # FINAL AI DECISION


        if self.absorption:

            signal="⚠️ ABSORPTION"



        elif buy_score>=75:


            signal="🟢 STRONG BUY"



        elif sell_score>=75:


            signal="🔴 STRONG SELL"



        elif buy_score>=60:


            signal="WATCH BUY"



        elif sell_score>=60:


            signal="WATCH SELL"





        self.signal=signal

        self.confidence=confidence

        self.market_regime=self.smart_money

        # ------------------------------------------------------------
        # Update confirmed_signal — see the explanation in __init__.
        # Only STRONG BUY / STRONG SELL are "actionable" here (matching
        # AutoTradeExecutor.SIGNAL_SIDE_MAP); ABSORPTION/WATCH/WAIT are
        # informational only and never drive a trade, so they don't
        # extend or start a hold.
        # ------------------------------------------------------------

        now = time.time()
        actionable = signal in ("🟢 STRONG BUY", "🔴 STRONG SELL")

        if actionable:
            self.confirmed_signal = signal
            self._last_actionable_signal_time = now
        elif (
            self._last_actionable_signal_time is not None
            and (now - self._last_actionable_signal_time) < self.signal_hold_seconds
        ):
            # still within the hold window — keep the previously
            # confirmed signal so a slow poller doesn't miss it
            pass
        else:
            self.confirmed_signal = "WAIT"
            self._last_actionable_signal_time = None


        print(f"""

=================================

🤖 AI ORDER FLOW PRO v7.0


REGIME:
SMART MONEY FLOW



BUY FLOW:
{buy_flow:.1f}%


SELL FLOW:
{sell_flow:.1f}%



DELTA:
{self.delta:.2f}



PRICE MOVE:
{self.price_change:.2f}



ORDERBOOK


BID:
{self.bid_liquidity:.0f}


ASK:
{self.ask_liquidity:.0f}



DOM PRESSURE:
{self.dom_pressure:.2f}%



SMART MONEY:

{self.smart_money}



WHALE:

{self.whale}



ABSORPTION:

{self.absorption}



VOLUME SPIKE:

{self.volume_spike}




BUY SCORE:

{buy_score}



SELL SCORE:

{sell_score}



CONFIDENCE:

{confidence}%



SIGNAL:


{signal}


CONFIRMED SIGNAL (held {self.signal_hold_seconds:.0f}s):

{self.confirmed_signal}


=================================

""")





orderflow_engine=OrderFlowEngine()