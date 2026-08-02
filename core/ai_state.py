class AIState:

    def __init__(self):

        self.data = {

            "buyer_strength":0,
            "seller_strength":0,
            "confidence":0,
            "delta":0,
            "dom_pressure":0,
            "signal":"WAIT",
            "volume_spike":False,
            "absorption":False

        }


    def update(self, **kwargs):

        self.data.update(kwargs)


    def get(self):

        return self.data



ai_state = AIState()