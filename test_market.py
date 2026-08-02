import asyncio

from exchange.websocket_client import DeltaWebSocketClient
from core.orderflow_engine import orderflow_engine

from core import event_bus


print("✅ Market Listener Started")
print("🤖 AI Order Flow Engine Started")


def market_handler(data):

    print(
        "📡 EVENT:",
        data["event"]
    )

    orderflow_engine.process(data)



# attach normal function
event_bus.market_update = market_handler



async def main():

    client = DeltaWebSocketClient()

    await client.connect()



if __name__ == "__main__":

    asyncio.run(main())