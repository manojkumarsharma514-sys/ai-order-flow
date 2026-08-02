import asyncio


# Store latest market data
latest_market_data = {}


# Registered listeners
listeners = []



def subscribe(callback):

    """
    Add dashboard/AI listeners
    """

    listeners.append(callback)




def market_update(data):

    """
    Receive exchange data
    Broadcast to all listeners
    """

    global latest_market_data


    event_type = data.get(
        "event"
    )


    latest_market_data[event_type] = data



    print(
        "📡 EVENT:",
        event_type
    )



    for callback in listeners:

        try:

            callback(data)

        except Exception as e:

            print(
                "Listener error:",
                e
            )




def get_latest(event_type=None):

    """
    Get latest stored data
    """

    if event_type:

        return latest_market_data.get(
            event_type
        )


    return latest_market_data