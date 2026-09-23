def generate_risk_explanation(
        assessment,
        risk_assessment
):

    explanations = []


    # SLA Analysis

    if assessment["sla_compliance"] < 50:

        explanations.append({

            "factor":
                "SLA Compliance",

            "value":
                f'{assessment["sla_compliance"]}%',

            "impact":
                "HIGH",

            "reason":
                "SOC response timelines are frequently breached"

        })


    # Detection Analysis

    if assessment["detection_score"] < 50:

        explanations.append({

            "factor":
                "Detection Effectiveness",

            "value":
                f'{assessment["detection_score"]}%',

            "impact":
                "HIGH",

            "reason":
                "Low percentage of alerts are successfully resolved"

        })


    # Investigation

    if assessment["investigation_quality"] < 3.5:

        explanations.append({

            "factor":
                "Investigation Quality",

            "value":
                str(
                    assessment["investigation_quality"]
                ),

            "impact":
                "MEDIUM",

            "reason":
                "Investigation maturity requires improvement"

        })


    # Critical Assets

    if len(
        assessment["critical_asset_risks"]
    ) > 0:


        explanations.append({

            "factor":
                "Critical Asset Protection",

            "value":
                str(
                    len(
                    assessment["critical_asset_risks"]
                    )
                ),

            "impact":
                "CRITICAL",

            "reason":
                "Critical assets experienced delayed incident response"

        })


    return {


        "risk_score":
            risk_assessment["risk_score"],


        "risk_level":
            risk_assessment["risk_level"],


        "risk_drivers":
            explanations

    }