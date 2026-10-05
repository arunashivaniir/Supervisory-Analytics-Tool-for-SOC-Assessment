class RiskScoring:


    def __init__(self):

        self.weights = {

            "FAST_CLOSURE_RISK": 20,

            "INVESTIGATION_QUALITY": 25,

            "ESCALATION_GAP": 30,

            "ASSET_CRITICALITY_RISK": 15,

            "MONITORING_VISIBILITY_GAP": 20

        }



    def calculate_score(self, findings):


        score = 0


        for finding in findings:


            score += self.weights.get(
                finding,
                0
            )


        if score > 100:

            score = 100


        return score



    def risk_level(self, score):


        if score >= 70:

            return "HIGH"


        elif score >= 40:

            return "MEDIUM"


        else:

            return "LOW"