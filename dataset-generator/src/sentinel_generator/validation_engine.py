import pandas as pd
import json



# ==================================================
# FINDING CONFIDENCE CALCULATION ENGINE
# ==================================================

def calculate_confidence(row):

    score = 0


    finding = str(
        row.get(
            "finding",
            ""
        )
    ).lower()


    evidence = str(
        row.get(
            "evidence",
            ""
        )
    ).lower()


    severity = str(
        row.get(
            "severity",
            ""
        )
    ).upper()



    # Severity Weight

    if severity == "CRITICAL":

        score += 30


    elif severity == "HIGH":

        score += 20


    elif severity == "MEDIUM":

        score += 10



    # Missing Control Evidence

    missing_control_keywords = [

        "missing evidence",
        "root cause",
        "remediation",
        "escalation record",
        "escalation gap",
        "lacks escalation",
        "no escalation",
        "without escalation",
        "not escalated",
        "missing investigation"

    ]


    if any(

        keyword in evidence

        or

        keyword in finding

        for keyword in missing_control_keywords

    ):

        score += 25



    # Investigation Weakness

    investigation_keywords = [

        "superficial investigation",
        "template",
        "template driven",
        "similarity",
        "repetitive",
        "duplicate",
        "poor investigation"

    ]


    if any(

        keyword in finding

        or

        keyword in evidence

        for keyword in investigation_keywords

    ):

        score += 25



    # Fast Closure Behaviour

    fast_closure_keywords = [

        "fast closure",
        "quickly",
        "unusually quickly",
        "rapid closure",
        "short investigation"

    ]


    if any(

        keyword in finding

        or

        keyword in evidence

        for keyword in fast_closure_keywords

    ):

        score += 20



    # Negative Space Indicators

    negative_space_keywords = [

        "no telemetry",
        "missing monitoring",
        "blind spot",
        "coverage gap",
        "no security alerts"

    ]


    if any(

        keyword in finding

        or

        keyword in evidence

        for keyword in negative_space_keywords

    ):

        score += 20



    # ML Support

    if row.get(

        "ml_supported",

        False

    ):

        score += 25



    return min(

        score,

        95

    )





# ==================================================
# CONFIDENCE LEVEL
# ==================================================

def get_confidence_level(score):


    if score >= 85:

        return "VERY_HIGH"


    elif score >= 70:

        return "HIGH"


    elif score >= 50:

        return "MEDIUM"


    else:

        return "LOW"





# ==================================================
# VALIDATION REPORT GENERATOR
# ==================================================

def generate_validation_report(

        findings_file,

        anomaly_file,

        alerts_file,

        output_file

):


    print(

        "[+] Loading findings..."

    )



    findings = pd.read_csv(

        findings_file

    ).fillna("")



    anomalies = pd.read_csv(

        anomaly_file

    ).fillna("")



    alerts = pd.read_csv(

        alerts_file

    ).fillna("")



    # ----------------------------------------------
    # Alert Mapping
    # ----------------------------------------------

    alert_mapping = alerts.set_index(

        "alert_id"

    )[

        [

            "cse_id",

            "asset_id"

        ]

    ].to_dict(

        "index"

    )



    # ----------------------------------------------
    # Isolation Forest Alerts
    # ----------------------------------------------

    anomaly_alerts = set(

        anomalies[

            anomalies[

                "anomaly_prediction"

            ]

            ==

            -1

        ]

        [

            "alert_id"

        ]

        .tolist()

    )



    validation_results = []



    for index, row in findings.iterrows():



        alert_id = row.get(

            "alert_id",

            ""

        )



        ml_detected = (

            alert_id

            in anomaly_alerts

        )



        cse_details = alert_mapping.get(

            alert_id,

            {}

        )



        confidence_score = calculate_confidence(

            {

                **row.to_dict(),

                "ml_supported":

                    ml_detected

            }

        )



        confidence_level = get_confidence_level(

            confidence_score

        )



        if confidence_score >= 60:

            validation_status = (

                "EVIDENCE_SUPPORTED"

            )

        else:

            validation_status = (

                "REQUIRES_REVIEW"

            )



        validation_results.append(

            {


                "finding_id":

                    f"FINDING_{str(index+1).zfill(5)}",



                "cse_id":

                    cse_details.get(

                        "cse_id",

                        ""

                    ),



                "asset_id":

                    cse_details.get(

                        "asset_id",

                        ""

                    ),



                "alert_id":

                    alert_id,



                "finding":

                    row.get(

                        "finding",

                        ""

                    ),



                "severity":

                    row.get(

                        "severity",

                        ""

                    ),



                "confidence_score":

                    confidence_score,



                "confidence_level":

                    confidence_level,



                "ml_supported":

                    ml_detected,



                "validation_status":

                    validation_status,



                "evidence":

                    row.get(

                        "evidence",

                        ""

                    )

            }

        )



    result = pd.DataFrame(

        validation_results

    )



    result.to_json(

        output_file,

        orient="records",

        indent=4

    )



    print(

        "[+] Validation report generated:",

        output_file

    )


    print(

        "[+] Total validated findings:",

        len(result)

    )



    return result