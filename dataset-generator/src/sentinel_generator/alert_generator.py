import random
from datetime import datetime, timedelta

from sentinel_generator.soc_behavior import get_soc_behavior


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


def generate_alerts(
        entities,
        assets,
        analysts,
        count=200
):


    alerts = []


    # Map CSE -> SOC behaviour profile

    entity_profiles = {}

    for entity in entities:

        entity_profiles[
            entity["cse_id"]
        ] = entity["soc_profile"]



    for i in range(count):


        # Select asset

        asset = random.choice(
            assets
        )


        # Select analyst

        analyst = random.choice(
            analysts
        )


        # Get SOC behaviour

        soc_profile = entity_profiles[
            asset["cse_id"]
        ]


        behaviour = get_soc_behavior(
            soc_profile
        )


        # Generate severity

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



        created_time = (
            datetime.now()
            -
            timedelta(
                minutes=random.randint(
                    10,
                    5000
                )
            )
        )



        # --------------------------------
        # SOC Behaviour Based Response
        # --------------------------------


        # KPI Optimized SOC:
        # suspiciously fast closure

        if random.random() < behaviour["fast_closure_probability"]:

            response_minutes = random.randint(
                1,
                10
            )

        else:

            response_minutes = random.randint(
                30,
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



        # Escalation behaviour

        escalated = (

            random.random()
            <
            behaviour["escalation_probability"]

        )



        # Remediation behaviour

        remediation_recorded = (

            random.random()
            <
            behaviour["remediation_probability"]

        )



        # Alert status

        status = random.choice(
            STATUS
        )


        # --------------------------------
        # Alert Object
        # --------------------------------


        alert = {


            "alert_id":

                f"ALERT_{str(i+1).zfill(5)}",



            "cse_id":

                asset["cse_id"],



            "asset_id":

                asset["asset_id"],



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



            "soc_profile":

                soc_profile,



            "status":

                status,



            "response_time_minutes":

                response_minutes,



            "closure_time_minutes":

                response_minutes,



            "sla_breach":

                sla_breach,



            "escalated":

                escalated,



            "remediation_recorded":

                remediation_recorded,



            "created_time":

                created_time.isoformat()


        }



        alerts.append(
            alert
        )



    return alerts