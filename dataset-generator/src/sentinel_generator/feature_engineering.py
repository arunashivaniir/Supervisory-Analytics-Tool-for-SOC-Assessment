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

    ).fillna("")



    investigations = pd.read_csv(

        investigations_file

    ).fillna("")



    assets = pd.read_csv(

        assets_file

    ).fillna("")



    # --------------------------------
    # Merge Alert + Investigation
    # --------------------------------


    data = alerts.merge(

        investigations,

        on="alert_id",

        how="left"

    )



    # --------------------------------
    # Restore CSE ID
    # --------------------------------


    if "cse_id_x" in data.columns:

        data["cse_id"] = data["cse_id_x"]


    elif "cse_id_y" in data.columns:

        data["cse_id"] = data["cse_id_y"]


    else:

        data["cse_id"] = "UNKNOWN"



    # --------------------------------
    # Merge Asset Information
    # --------------------------------


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



    # --------------------------------
    # Feature Creation
    # --------------------------------


    data["severity_score"] = (

        data["severity"]

        .map(SEVERITY_MAP)

        .fillna(0)

    )



    data["asset_criticality_score"] = (

        data["criticality"]

        .map(ASSET_MAP)

        .fillna(0)

    )



    # --------------------------------
    # Execution Gap Features
    # --------------------------------


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

            <

            10

        )

    ).astype(int)



    data["missing_evidence"] = (

        data["evidence_count"]

        .fillna(0)

        ==

        0

    ).astype(int)



    data["missing_root_cause"] = (

        data["root_cause_identified"]

        .astype(str)

        .str.lower()

        ==

        "false"

    ).astype(int)



    data["missing_remediation"] = (

        data["remediation_recorded_y"]

        .astype(str)

        .str.lower()

        ==

        "false"

    ).astype(int)



    data["missing_escalation"] = (

        (

            data["severity"]

            ==

            "CRITICAL"

        )

        &

        (

            data["escalated"]

            .astype(str)

            .str.lower()

            ==

            "false"

        )

    ).astype(int)



    # Investigation quality

    data["investigation_quality"] = (

        data["investigation_quality"]

        .fillna(0)

    )



    data["low_investigation_quality"] = (

        data["investigation_quality"]

        <

        3

    ).astype(int)



    data["investigation_time_minutes"] = (

        data["investigation_time_minutes"]

        .fillna(0)

    )



    data["short_investigation"] = (

        data["investigation_time_minutes"]

        <

        10

    ).astype(int)



    data["note_similarity"] = (

        data["note_similarity"]

        .fillna(0)

    )



    data["template_investigation"] = (

        data["note_similarity"]

        >

        0.85

    ).astype(int)



    # --------------------------------
    # Final Feature Dataset
    # --------------------------------


    features = data[

        [

            "alert_id",

            "cse_id",

            "asset_id",

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



    features = features.fillna(0)



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