import random


MONITORING_TYPES = [

    "MALWARE",
    "PHISHING",
    "RANSOMWARE",
    "UNAUTHORIZED_ACCESS",
    "DATA_EXFILTRATION",
    "PRIVILEGE_ESCALATION",
    "NETWORK_ANOMALY"

]



def generate_monitoring_coverage(
        assets
):


    coverage = []


    for asset in assets:


        expected = random.sample(

            MONITORING_TYPES,

            k=random.randint(2,4)

        )


        # Simulate blind spots

        telemetry_available = random.choices(

            [
                "YES",
                "NO"
            ],

            weights=[
                85,
                15
            ]

        )[0]


        actual = expected.copy()


        if telemetry_available == "NO":

            actual = []



        coverage.append({

            "asset_id":

                asset["asset_id"],


            "cse_id":

                asset["cse_id"],


            "criticality":

                asset["criticality"],


            "expected_monitoring":

                "|".join(expected),


            "actual_monitoring":

                "|".join(actual),


            "telemetry_available":

                telemetry_available

        })


    return coverage