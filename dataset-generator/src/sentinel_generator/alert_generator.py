import random
from datetime import datetime, timedelta


ALERT_TYPES = [

    "MALWARE",
    "PHISHING",
    "RANSOMWARE",
    "UNAUTHORIZED_ACCESS",
    "DATA_EXFILTRATION",
    "PRIVILEGE_ESCALATION",
    "DDoS",
    "CONFIGURATION_CHANGE"

]


SEVERITY = [

    "LOW",
    "MEDIUM",
    "HIGH",
    "CRITICAL"

]


SOURCES = [

    "SIEM",
    "IDS",
    "FIREWALL",
    "ENDPOINT_AGENT",
    "THREAT_INTELLIGENCE"

]


STATUS = [

    "OPEN",
    "INVESTIGATING",
    "RESOLVED",
    "FALSE_POSITIVE"

]


def generate_alerts(assets, analysts, count=200):


    alerts = []


    for i in range(count):


        asset = random.choice(assets)

        analyst = random.choice(analysts)


        severity = random.choices(

            [
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL"
            ],

            weights=[
                40,
                35,
                20,
                5
            ]

        )[0]



        created_time = datetime.now() - timedelta(

            minutes=random.randint(
                10,
                5000
            )

        )


        # Simulate SOC response delay

        response_minutes = random.randint(
            5,
            600
        )


        sla_limit = {


            "LOW":240,

            "MEDIUM":120,

            "HIGH":60,

            "CRITICAL":30

        }


        sla_breach = (

            response_minutes >
            sla_limit[severity]

        )


        alert = {


            "alert_id":

                f"ALERT_{str(i+1).zfill(5)}",


            "asset_id":

                asset["asset_id"],



            "cse_id":

                asset["cse_id"],



            "asset_criticality":

                asset["criticality"],



            "alert_type":

                random.choice(
                    ALERT_TYPES
                ),



            "severity":

                severity,



            "source":

                random.choice(
                    SOURCES
                ),



            "assigned_analyst":

                analyst["analyst_id"],



            "status":

                random.choice(
                    STATUS
                ),



            "response_time_minutes":

                response_minutes,



            "sla_breach":

                sla_breach,


            "created_time":

                created_time.isoformat()

        }


        alerts.append(alert)



    return alerts