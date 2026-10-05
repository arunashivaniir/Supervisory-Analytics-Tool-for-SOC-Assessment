class CapabilityMap:


    def __init__(self):

        self.capabilities = {}



    def add(
            self,
            capability,
            confidence,
            evidence
    ):

        self.capabilities[capability] = {

            "confidence": confidence,

            "evidence": evidence

        }



    def to_dict(self):

        return self.capabilities