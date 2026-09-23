def calculate_risk_score(assessment):


    # Detection Risk

    detection_risk = (
        100 -
        assessment["detection_score"]
    )


    # Response Risk

    response_risk = (
        100 -
        assessment["sla_compliance"]
    )


    # Investigation Risk

    investigation_percentage = (

        assessment["investigation_quality"]
        /
        5
    ) * 100


    investigation_risk = (
        100 -
        investigation_percentage
    )


    # Critical Asset Risk

    critical_asset_risk = 0


    if len(
        assessment["critical_asset_risks"]
    ) > 0:

        critical_asset_risk = 100



    # Weighted score


    risk_score = (

        detection_risk * 0.30

        +

        response_risk * 0.40

        +

        investigation_risk * 0.20

        +

        critical_asset_risk * 0.10

    )


    risk_score = round(
        risk_score,
        2
    )


    return risk_score



def classify_risk(score):


    if score >= 75:

        return "CRITICAL"


    elif score >= 50:

        return "HIGH"


    elif score >= 25:

        return "MEDIUM"


    else:

        return "LOW"



def generate_risk_assessment(assessment):


    score = calculate_risk_score(
        assessment
    )


    return {


        "risk_score":
            score,


        "risk_level":
            classify_risk(score)

    }