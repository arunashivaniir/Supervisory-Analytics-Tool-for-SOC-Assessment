import random


ROOT_CAUSES = [

    "Compromised Credentials",

    "Malware Infection",

    "Misconfiguration",

    "Insider Activity",

    "Unknown"

]


EVIDENCE_TYPES = [

    "Firewall Logs",

    "SIEM Logs",

    "Endpoint Logs",

    "Network Capture",

    "User Activity Logs"

]


REMEDIATION_ACTIONS = [

    "Password Reset",

    "Patch Applied",

    "Access Revoked",

    "Malware Removed",

    "Configuration Updated"

]


CLOSURE_STATUS = [

    "RESOLVED",

    "FALSE_POSITIVE",

    "ESCALATED",

    "OPEN"

]


NOTE_QUALITY = [

    "POOR",

    "AVERAGE",

    "GOOD",

    "EXCELLENT"

]


def generate_investigations(alerts, analysts):


    investigations = []


    for i, alert in enumerate(alerts):


        analyst = random.choice(analysts)


        investigation_time = random.randint(
            10,
            720
        )


        # Simulate investigation quality

        quality_score = random.randint(
            1,
            5
        )


        investigation = {


            "investigation_id":
                f"INV_{str(i+1).zfill(5)}",


            "alert_id":
                alert["alert_id"],


            "analyst_id":
                analyst["analyst_id"],


            "investigation_quality":
                quality_score,


            "evidence_collected":
                random.choice(
                    EVIDENCE_TYPES
                ),


            "root_cause":
                random.choice(
                    ROOT_CAUSES
                ),


            "remediation":
                random.choice(
                    REMEDIATION_ACTIONS
                ),


            "closure_status":
                random.choice(
                    CLOSURE_STATUS
                ),


            "investigation_time_minutes":
                investigation_time,


            "notes_quality":
                random.choice(
                    NOTE_QUALITY
                )

        }


        investigations.append(
            investigation
        )


    return investigations