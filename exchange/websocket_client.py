import json
import asyncio
import websockets
import time

from core import event_bus


class DeltaWebSocketClient:

    def __init__(self):

        self.url = "wss://socket.india.delta.exchange"
        self.symbol = "BTCUSD"

        # overridden by WebSocketThread so events reach the GUI thread safely
        self.on_event = event_bus.market_update

        # overridden by WebSocketThread to report real connect/disconnect state
        self.on_connection_change = lambda connected: None


    async def connect(self):

        while True:

            try:

                async with websockets.connect(
                    self.url,
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:


                    print("✅ Delta WebSocket Connected")

                    self.on_connection_change(True)


                    subscribe_message = {

                        "type": "subscribe",

                        "payload": {

                            "channels": [

                                {
                                    "name": "l2_orderbook",
                                    "symbols": [
                                        self.symbol
                                    ]
                                },

                                {
                                    "name": "all_trades",
                                    "symbols": [
                                        self.symbol
                                    ]
                                }

                            ]

                        }

                    }


                    await ws.send(
                        json.dumps(subscribe_message)
                    )


                    print(
                        f"📡 Subscribed: {self.symbol}"
                    )


                    while True:

                        message = await ws.recv()

                        data = json.loads(message)


                        await self.process_message(
                            data
                        )



            except Exception as e:

                self.on_connection_change(False)

                print(
                    "⚠️ WebSocket Error:",
                    e
                )

                print(
                    "🔄 Reconnecting after 5 seconds..."
                )


                await asyncio.sleep(5)




    async def process_message(self, data):


        message_type = data.get(
            "type"
        )


        # =====================================
        # SUBSCRIPTION RESPONSE
        # =====================================

        if message_type == "subscriptions":

            print(
                "ℹ️ Subscription Status OK"
            )

            return



        # =====================================
        # HEARTBEAT
        # =====================================

        if message_type == "heartbeat":

            return



        # =====================================
        # ORDER BOOK / DOM
        # =====================================

        if message_type == "l2_orderbook":


            orderbook_data = {


                "event": "orderbook",

                "symbol": self.symbol,


                # Delta uses buy/sell
                "bids": data.get(
                    "buy",
                    []
                ),


                "asks": data.get(
                    "sell",
                    []
                ),


                "spread": data.get(
                    "spread"
                ),

                # Preserve exchange ordering metadata when Delta sends it.
                # The feature engines still use local receipt time as the
                # normalized clock because the exact exchange field varies by
                # feed version, but retaining this makes later sequence-gap
                # detection possible without another transport change.
                "exchange_timestamp": data.get("timestamp") or data.get("time"),
                "sequence": data.get("sequence") or data.get("seq_no"),


                "timestamp": time.time()

            }



            print(
                "📚 ORDERBOOK:",
                "Bids:",
                len(orderbook_data["bids"]),
                "Asks:",
                len(orderbook_data["asks"])
            )


            self.on_event(
                orderbook_data
            )



        # =====================================
        # TRADE SNAPSHOT
        # =====================================

        elif message_type == "all_trades_snapshot":


            trades = data.get(
                "trades",
                []
            )


            for trade in trades:


                trade_data = {


                    "event": "trade",

                    "symbol": self.symbol,


                    "price": trade.get(
                        "price"
                    ),


                    "size": trade.get(
                        "size"
                    ),


                    "buyer_role": trade.get(
                        "buyer_role"
                    ),


                    "seller_role": trade.get(
                        "seller_role"
                    ),


                    "timestamp": time.time()

                }


                self.on_event(
                    trade_data
                )



        # =====================================
        # LIVE TRADE
        # =====================================

        elif message_type == "all_trades":


            trade_data = {


                "event": "trade",

                "symbol": self.symbol,


                "price": data.get(
                    "price"
                ),


                "size": data.get(
                    "size"
                ),


                "buyer_role": data.get(
                    "buyer_role"
                ),


                "seller_role": data.get(
                    "seller_role"
                ),


                    "timestamp": time.time()

            }



            print(
                "💹 TRADE:",
                trade_data
            )


            self.on_event(
                trade_data
            )



        else:


            print(
                "ℹ️ OTHER MESSAGE:",
                data
            )






async def start():


    client = DeltaWebSocketClient()


    await client.connect()





if __name__ == "__main__":


    asyncio.run(
        start()
    )
