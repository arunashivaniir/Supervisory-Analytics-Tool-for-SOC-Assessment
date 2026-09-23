import statistics



def calculate_detection_score(alerts):


    total = len(alerts)


    if total == 0:
        return 0


    resolved = len(
        [
            a for a in alerts
            if a["status"] == "RESOLVED"
        ]
    )


    return round(
        (resolved / total) * 100,
        2
    )




def calculate_sla_score(alerts):


    total = len(alerts)


    if total == 0:
        return 0


    breaches = len(

        [
            a for a in alerts
            if a["sla_breach"] == True
        ]

    )


    return round(

        ((total-breaches)/total)*100,

        2

    )




def calculate_investigation_quality(investigations):


    scores = [

        i["investigation_quality"]

        for i in investigations

    ]


    if not scores:
        return 0


    return round(

        statistics.mean(scores),

        2

    )




def critical_asset_risks(alerts):


    risks = []


    for alert in alerts:


        if (

            alert["asset_criticality"] == "TIER-0"

            and

            alert["severity"] == "CRITICAL"

            and

            alert["sla_breach"] == True

        ):


            risks.append(

                {

                "alert_id":
                    alert["alert_id"],


                "risk":
                    "CRITICAL ASSET SLA FAILURE"

                }

            )


    return risks




def generate_assessment(alerts, investigations):


    report = {}


    report["detection_score"] = (

        calculate_detection_score(
            alerts
        )

    )


    report["sla_compliance"] = (

        calculate_sla_score(
            alerts
        )

    )


    report["investigation_quality"] = (

        calculate_investigation_quality(
            investigations
        )

    )


    report["critical_asset_risks"] = (

        critical_asset_risks(
            alerts
        )

    )


    return report