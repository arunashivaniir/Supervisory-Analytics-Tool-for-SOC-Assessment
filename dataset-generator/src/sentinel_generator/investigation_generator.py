import random

from sentinel_generator.soc_behavior import get_soc_behavior


EVIDENCE_TYPES = [

    "SIEM_LOGS",
    "FIREWALL_LOG",
    "ENDPOINT_LOGS",
    "NETWORK_CAPTURE",
    "USER_ACTIVITY_LOGS",
    "MALWARE_ANALYSIS"

]


ROOT_CAUSES = [

    "COMPROMISED_CREDENTIALS",
    "MALWARE_INFECTION",
    "MISCONFIGURATION",
    "INSIDER_ACTIVITY",
    "UNPATCHED_SYSTEM",
    "UNKNOWN"

]


REMEDIATION_ACTIONS = [

    "PASSWORD_RESET",
    "PATCH_APPLIED",
    "ACCESS_REVOKED",
    "MALWARE_REMOVED",
    "CONFIGURATION_UPDATED",
    "NO_ACTION"

]


NOTE_TEMPLATES = [

    "Reviewed logs and closed the alert",

    "Checked activity and resolved issue",

    "Investigation completed successfully",

    "Analysed event and closed case",

    "Reviewed evidence and performed remediation"

]



def generate_investigations(
        alerts,
        analysts,
        count=None
):


    investigations = []


    if count is None:

        count = len(alerts)



    for i in range(count):


        alert = alerts[i % len(alerts)]

        analyst = random.choice(analysts)


        soc_profile = alert["soc_profile"]


        behaviour = get_soc_behavior(
            soc_profile
        )



        # -------------------------------
        # Investigation Duration
        # -------------------------------

        if random.random() < behaviour["fast_closure_probability"]:


            investigation_time = random.randint(
                1,
                10
            )


        else:

            investigation_time = random.randint(
                30,
                300
            )



        # -------------------------------
        # Evidence Collection
        # -------------------------------


        if random.random() < behaviour["evidence_probability"]:


            evidence_count = random.randint(
                3,
                len(EVIDENCE_TYPES)
            )


            evidence_collected = random.sample(

                EVIDENCE_TYPES,

                k=evidence_count

            )


        else:


            evidence_count = random.randint(
                0,
                1
            )


            if evidence_count > 0:

                evidence_collected = random.sample(

                    EVIDENCE_TYPES,

                    k=evidence_count

                )

            else:

                evidence_collected = []



        # -------------------------------
        # Root Cause Analysis
        # -------------------------------


        root_cause_identified = (

            random.random()
            <
            behaviour["evidence_probability"]

        )


        if root_cause_identified:

            root_cause = random.choice(
                ROOT_CAUSES
            )

        else:

            root_cause = "UNKNOWN"



        # -------------------------------
        # Remediation
        # -------------------------------


        remediation_recorded = (

            random.random()
            <
            behaviour["remediation_probability"]

        )


        if remediation_recorded:

            remediation_action = random.choice(
                REMEDIATION_ACTIONS
            )

        else:

            remediation_action = "NO_ACTION"



        # -------------------------------
        # Investigation Notes Behaviour
        # -------------------------------


        if soc_profile == "KPI_OPTIMIZED":


            note_similarity = round(

                random.uniform(
                    0.85,
                    1.0
                ),

                2

            )


            investigation_notes = random.choice(
                NOTE_TEMPLATES
            )


        elif soc_profile == "MATURE":


            note_similarity = round(

                random.uniform(
                    0.10,
                    0.40
                ),

                2

            )


            investigation_notes = (

                "Detailed investigation performed "
                "with evidence validation, "
                "root cause analysis and remediation tracking"

            )


        else:


            note_similarity = round(

                random.uniform(
                    0.40,
                    0.80
                ),

                2

            )


            investigation_notes = random.choice(
                NOTE_TEMPLATES
            )



        # -------------------------------
        # Investigation Quality Score
        # -------------------------------


        quality_score = 0


        if evidence_count >= 3:

            quality_score += 2


        if root_cause_identified:

            quality_score += 1


        if remediation_recorded:

            quality_score += 1


        if investigation_time >= 30:

            quality_score += 1



        quality_score = min(
            quality_score,
            5
        )



        # -------------------------------
        # Investigation Object
        # -------------------------------


        investigation = {


            "investigation_id":

                f"INV_{str(i+1).zfill(5)}",



            "alert_id":

                alert["alert_id"],



            "analyst_id":

                analyst["analyst_id"],



            "cse_id":

                alert["cse_id"],



            "soc_profile":

                soc_profile,



            "investigation_quality":

                quality_score,



            "investigation_time_minutes":

                investigation_time,



            "evidence_count":

                evidence_count,



            "evidence_collected":

                ",".join(
                    evidence_collected
                ),



            "root_cause_identified":

                root_cause_identified,



            "root_cause":

                root_cause,



            "remediation_recorded":

                remediation_recorded,



            "remediation_action":

                remediation_action,



            "investigation_notes":

                investigation_notes,



            "note_similarity":

                note_similarity

        }



        investigations.append(
            investigation
        )



    return investigations

import pandas as pd



SEVERITY_MAP = {

    "LOW":1,
    "MEDIUM":2,
    "HIGH":3,
    "CRITICAL":4

}


ASSET_MAP = {

    "TIER-3":1,
    "TIER-2":2,
    "TIER-1":3,
    "TIER-0":4

}



def generate_features(
        alerts_file,
        investigations_file,
        assets_file,
        output_file
):


    alerts = pd.read_csv(
        alerts_file
    )


    investigations = pd.read_csv(
        investigations_file
    )


    assets = pd.read_csv(
        assets_file
    )



    # Merge alert + investigation

    data = alerts.merge(

        investigations,

        on="alert_id",

        how="left"

    )



    # Merge asset information

    data = data.merge(

        assets[
            [
                "asset_id",
                "criticality"
            ]
        ],

        on="asset_id",

        how="left"

    )



    # Severity encoding

    data["severity_score"] = (

        data["severity"]
        .map(SEVERITY_MAP)

    )



    # Asset criticality

    data["asset_criticality_score"] = (

        data["criticality"]
        .map(ASSET_MAP)

    )



    # Fast closure

    data["fast_closure"] = (

        (
            data["severity"]
            .isin(
                ["HIGH","CRITICAL"]
            )
        )

        &

        (
            data["closure_time_minutes"] < 10
        )

    ).astype(int)



    # Missing evidence

    data["missing_evidence"] = (

        data["evidence_count"] == 0

    ).astype(int)



    # Missing RCA

    data["missing_root_cause"] = (

        data["root_cause_identified"] == False

    ).astype(int)



    # Missing remediation

    data["missing_remediation"] = (

        data["remediation_recorded"] == False

    ).astype(int)



    # Missing escalation

    data["missing_escalation"] = (

        (
            data["severity"]
            ==
            "CRITICAL"
        )

        &

        (
            data["escalated"] == False
        )

    ).astype(int)



    features = data[

        [

        "alert_id",

        "severity_score",

        "asset_criticality_score",

        "response_time_minutes",

        "fast_closure",

        "sla_breach",

        "evidence_count",

        "missing_evidence",

        "missing_root_cause",

        "missing_remediation",

        "note_similarity",

        "investigation_time_minutes",

        "missing_escalation"

        ]

    ]



    features.to_csv(

        output_file,

        index=False

    )


    print(
        "[+] Feature dataset generated:",
        output_file
    )