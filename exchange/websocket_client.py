import json
import asyncio
import websockets
import time

from core import event_bus


# Delta Exchange India denominates BTCUSD perpetual futures trade
# sizes in CONTRACTS, not raw BTC -- confirmed against a live feed
# sample (raw sizes arriving as whole numbers: 1, 10, 129, 469...) and
# directly against the app's own displayed Recent Trades qty vs
# Delta's own UI for the identical trade (app showed qty=5, Delta's
# UI showed 0.005 BTC for that same print). Every trade tick is
# converted to actual BTC right here, at the single point raw feed
# data enters the app, so every downstream consumer -- candle volume,
# footprint buy/sell size, VWAP, CVD, the orderflow confluence engine,
# and the Recent Trades table -- automatically gets correct BTC units
# without needing its own conversion.
#
# This default is only the FALLBACK. core.websocket_thread.WebSocketThread
# fetches the real, authoritative value from Delta's own product spec
# via exchange.delta_api.fetch_contract_size() at startup and sets it
# on self.contract_size_btc below before this client starts processing
# trades -- see WebSocketThread.run(). This constant only matters if
# that live fetch fails (network issue, endpoint change, etc).
CONTRACT_SIZE_BTC_DEFAULT = 0.001


class DeltaWebSocketClient:

    def __init__(self):

        self.url = "wss://socket.india.delta.exchange"
        self.symbol = "BTCUSD"

        # Contracts -> BTC conversion factor for incoming trade ticks.
        # Starts at the safe fallback; WebSocketThread.run() overwrites
        # this with the live value fetched from Delta's product spec
        # (exchange.delta_api.fetch_contract_size()) before connect()
        # is called, so under normal operation this is the real,
        # exchange-reported contract size, not a guess.
        self.contract_size_btc = CONTRACT_SIZE_BTC_DEFAULT

        # overridden by WebSocketThread so events reach the GUI thread safely
        self.on_event = event_bus.market_update

        # overridden by WebSocketThread to report real connect/disconnect state
        self.on_connection_change = lambda connected: None

    def _contracts_to_btc(self, raw_size):
        """Best-effort conversion using self.contract_size_btc; falls
        back to the raw value untouched if it isn't parseable, so a
        malformed size never crashes the feed -- it'll just be visibly
        wrong instead of silently missing."""
        try:
            return float(raw_size) * self.contract_size_btc
        except (TypeError, ValueError):
            return raw_size

    def _convert_book_levels(self, levels):
        """Apply the SAME contracts->BTC conversion to every price
        level in a raw L2 order-book side (bids or asks), preserving
        each level's original shape -- core.orderbook_engine.
        OrderBookEngine._parse_levels accepts either a dict
        ({"price":..,"size":..}) or a [price, size] pair, so this
        handles both without assuming which one Delta sends.

        This was the missing half of the contract-size fix: the trade
        tick feed (all_trades) was converted, but l2_orderbook's bid/
        ask sizes were left as raw contract counts -- confirmed
        directly against Delta's own Order Book UI (26.559 BTC shown
        on Delta vs 26,559.000 shown in this app's Live Order Book for
        the identical price level; Delta's own quantity panel states
        '1 Lot = 0.001 BTC', matching self.contract_size_btc exactly).
        Left unconverted, every book-derived feature -- bid_liquidity/
        ask_liquidity, spoof_risk, replenishment, the Live Order Book
        panel, and the Microstructure Diagnostics panel's absolute
        size figures -- was reading contract counts as if already BTC.
        (OBI itself is a ratio and was scale-invariant, so it wasn't
        affected.)"""

        converted = []
        for level in levels or []:
            try:
                if isinstance(level, dict):
                    new_level = dict(level)
                    if "size" in new_level:
                        new_level["size"] = self._contracts_to_btc(new_level["size"])
                    elif "quantity" in new_level:
                        new_level["quantity"] = self._contracts_to_btc(new_level["quantity"])
                    converted.append(new_level)
                else:
                    price, size = level[0], level[1]
                    converted.append((price, self._contracts_to_btc(size)))
            except (TypeError, IndexError, KeyError):
                converted.append(level)  # malformed entry -- pass through rather than drop/crash
        return converted


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


                # Delta uses buy/sell -- converted from contracts to
                # BTC per level, see _convert_book_levels().
                "bids": self._convert_book_levels(data.get(
                    "buy",
                    []
                )),


                "asks": self._convert_book_levels(data.get(
                    "sell",
                    []
                )),


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


                    # Converted from contracts to BTC -- see
                    # CONTRACT_SIZE_BTC note at the top of this file.
                    "size": self._contracts_to_btc(trade.get(
                        "size"
                    )),


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


                # Converted from contracts to BTC -- see
                # CONTRACT_SIZE_BTC note at the top of this file.
                "size": self._contracts_to_btc(data.get(
                    "size"
                )),


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
