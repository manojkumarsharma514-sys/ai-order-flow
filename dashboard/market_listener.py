from core import event_bus

from core.ai_state import ai_state




class MarketListener:


    def __init__(self):


        self.price = None


        self.orderbook = {

            "bids":[],
            "asks":[]

        }


        self.buy_volume = 0

        self.sell_volume = 0



        event_bus.subscribe(
            self.on_market_update
        )


        print(
            "✅ Market Listener Started"
        )





    def on_market_update(self,data):


        event=data.get(
            "event"
        )



        # ============================
        # ORDERBOOK
        # ============================


        if event=="orderbook":


            self.orderbook["bids"] = data.get(
                "bids",
                []
            )


            self.orderbook["asks"] = data.get(
                "asks",
                []
            )


            self.calculate_order_imbalance()





        # ============================
        # TRADE
        # ============================


        elif event=="trade":



            price=float(
                data.get("price",0)
            )


            size=float(
                data.get("size",0)
            )



            self.price=price


            ai_state.price=price




            buyer=data.get(
                "buyer_role"
            )


            seller=data.get(
                "seller_role"
            )



            if buyer=="taker":


                self.buy_volume += size



            if seller=="taker":


                self.sell_volume += size




            self.calculate_trade_strength()





    # =================================
    # ORDERBOOK ANALYSIS
    # =================================


    def calculate_order_imbalance(self):


        bid_total=0

        ask_total=0




        for bid in self.orderbook["bids"][:50]:


            try:

                if isinstance(bid,dict):

                    bid_total += float(
                        bid.get("size",0)
                    )

                else:

                    bid_total += float(
                        bid[1]
                    )


            except:

                pass






        for ask in self.orderbook["asks"][:50]:


            try:


                if isinstance(ask,dict):

                    ask_total += float(
                        ask.get("size",0)
                    )


                else:

                    ask_total += float(
                        ask[1]
                    )



            except:

                pass





        ai_state.bid_liquidity = bid_total

        ai_state.ask_liquidity = ask_total




        total = bid_total + ask_total



        if total:


            imbalance=(

                (bid_total-ask_total)

                /

                total

            )*100



            ai_state.dom_pressure=imbalance




            print(
                f"📊 DOM PRESSURE {imbalance:.2f}%"
            )






    # =================================
    # TRADE FLOW
    # =================================


    def calculate_trade_strength(self):



        total=(

            self.buy_volume +

            self.sell_volume

        )



        if total:


            buyer=(

                self.buy_volume /

                total

            )*100



            seller=(

                self.sell_volume /

                total

            )*100





            ai_state.buyer_strength=buyer


            ai_state.seller_strength=seller



            ai_state.delta=(

                self.buy_volume -

                self.sell_volume

            )





            # Simple AI confidence


            confidence=abs(

                buyer-seller

            )



            ai_state.confidence=min(

                int(confidence),

                100

            )






            # Signal


            if buyer>70 and ai_state.delta>0:


                ai_state.signal="🟢 STRONG BUY"



            elif seller>70 and ai_state.delta<0:


                ai_state.signal="🔴 STRONG SELL"



            else:


                ai_state.signal="WAIT"






            print(f"""

========================

🤖 AI ENGINE


BUY:
{buyer:.1f}%


SELL:
{seller:.1f}%


DELTA:
{ai_state.delta:.2f}


CONFIDENCE:
{ai_state.confidence}%


SIGNAL:
{ai_state.signal}


========================

""")







listener=MarketListener()