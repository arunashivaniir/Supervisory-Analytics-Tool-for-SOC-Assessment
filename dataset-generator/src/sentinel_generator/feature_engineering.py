import pandas as pd



SEVERITY_MAP = {

    "LOW": 1,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4

}


ASSET_MAP = {

    "TIER-3": 1,
    "TIER-2": 2,
    "TIER-1": 3,
    "TIER-0": 4

}



def generate_features(
        alerts_file,
        investigations_file,
        assets_file,
        output_file
):


    print("[+] Loading datasets...")


    alerts = pd.read_csv(
        alerts_file
    )


    investigations = pd.read_csv(
        investigations_file
    )


    assets = pd.read_csv(
        assets_file
    )



    # -----------------------------------
    # Merge Alert + Investigation Data
    # -----------------------------------

    data = alerts.merge(

        investigations,

        on="alert_id",

        how="left",

        suffixes=(

            "_alert",

            "_investigation"

        )

    )



    # -----------------------------------
    # Merge Asset Information
    # -----------------------------------

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



    # -----------------------------------
    # Severity Encoding
    # -----------------------------------

    data["severity_score"] = (

        data["severity"]

        .map(SEVERITY_MAP)

        .fillna(0)

    )



    # -----------------------------------
    # Asset Criticality Encoding
    # -----------------------------------

    data["asset_criticality_score"] = (

        data["criticality"]

        .map(ASSET_MAP)

        .fillna(0)

    )



    # -----------------------------------
    # Fast Closure Detection
    # -----------------------------------

    data["fast_closure"] = (

        (

            data["severity"]

            .isin(

                [

                    "HIGH",

                    "CRITICAL"

                ]

            )

        )

        &

        (

            data["closure_time_minutes"]

            < 10

        )

    ).astype(int)



    # -----------------------------------
    # Missing Evidence
    # -----------------------------------

    data["missing_evidence"] = (

        data["evidence_count"]

        == 0

    ).astype(int)



    # -----------------------------------
    # Missing Root Cause
    # -----------------------------------

    data["missing_root_cause"] = (

        data["root_cause_identified"]

        == False

    ).astype(int)



    # -----------------------------------
    # Missing Remediation
    # Use investigation data
    # -----------------------------------

    data["missing_remediation"] = (

        data["remediation_recorded_investigation"]

        == False

    ).astype(int)



    # -----------------------------------
    # Missing Escalation
    # -----------------------------------

    data["missing_escalation"] = (

        (

            data["severity"]

            == "CRITICAL"

        )

        &

        (

            data["escalated"]

            == False

        )

    ).astype(int)



    # -----------------------------------
    # Investigation Weakness
    # -----------------------------------

    data["low_investigation_quality"] = (

        data["investigation_quality"]

        < 3

    ).astype(int)



    # -----------------------------------
    # Short Investigation Time
    # -----------------------------------

    data["short_investigation"] = (

        data["investigation_time_minutes"]

        < 10

    ).astype(int)



    # -----------------------------------
    # Template Investigation Behaviour
    # -----------------------------------

    data["template_investigation"] = (

        data["note_similarity"]

        > 0.85

    ).astype(int)



    # -----------------------------------
    # Select ML Features
    # -----------------------------------

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

            "missing_escalation",

            "investigation_quality",

            "low_investigation_quality",

            "investigation_time_minutes",

            "short_investigation",

            "note_similarity",

            "template_investigation"

        ]

    ]



    # -----------------------------------
    # Convert Boolean Columns
    # -----------------------------------

    boolean_columns = [

        "sla_breach"

    ]


    for column in boolean_columns:

        features[column] = (

            features[column]

            .astype(int)

        )



    # -----------------------------------
    # Save Feature Dataset
    # -----------------------------------

    features.to_csv(

        output_file,

        index=False

    )


    print(

        "[+] Feature dataset generated:",

        output_file

    )


    print(

        "[+] Total feature rows:",

        len(features)

    )


    return features