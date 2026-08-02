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


=================================

""")





orderflow_engine=OrderFlowEngine()