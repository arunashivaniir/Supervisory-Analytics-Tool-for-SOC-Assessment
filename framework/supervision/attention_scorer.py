class AttentionScorer:



    SEVERITY_WEIGHTS = {


        "HIGH": 25,

        "MEDIUM": 15,

        "LOW": 5

    }




    def calculate(
            self,
            findings
    ):


        score = 0


        indicators = []



        for finding in findings:


            severity = finding.get(

                "severity",

                "LOW"

            )


            score += self.SEVERITY_WEIGHTS.get(

                severity,

                5

            )


            indicators.append(

                finding.get(

                    "indicator"

                )

            )



        score = min(

            score,

            100

        )



        if score >= 70:

            risk = "HIGH"


        elif score >= 40:

            risk = "MEDIUM"


        else:

            risk = "LOW"



        return {


            "attention_score":

            score,


            "risk_level":

            risk,


            "risk_indicators":

            list(set(indicators))

        }