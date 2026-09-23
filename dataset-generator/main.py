import sys

sys.path.append("src")

from sentinel_generator.monitoring_generator import generate_monitoring_coverage
from sentinel_generator.negative_space_engine import generate_negative_space_findings
from sentinel_generator.finding_engine import generate_findings
from sentinel_generator.anomaly_detector import train_anomaly_model
from sentinel_generator.feature_engineering import generate_features
from sentinel_generator.entity_generator import generate_entities
from sentinel_generator.asset_generator import generate_assets
from sentinel_generator.analyst_generator import generate_analysts
from sentinel_generator.alert_generator import generate_alerts
from sentinel_generator.exporter import export_csv
from sentinel_generator.investigation_generator import generate_investigations
import statistics
from sentinel_generator.risk_scoring_engine import generate_risk_assessment
from sentinel_generator.risk_explanation_engine import generate_risk_explanation

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

# 1. Generate CSE entities

entities = generate_entities(20)



# 2. Generate assets linked to CSE

assets = generate_assets(
    entities
)

monitoring = generate_monitoring_coverage(
    assets
)

# 3. Generate SOC analysts

analysts = generate_analysts(
    50
)



# 4. Generate alerts linked to assets and analysts

alerts = generate_alerts(
    entities,
    assets,
    analysts,
    500
)

investigations = generate_investigations(
    alerts,
    analysts
)

assessment = generate_assessment(

    alerts,

    investigations

)

risk = generate_risk_assessment(
    assessment
)


explanation = generate_risk_explanation(
    assessment,
    risk
)

# 5. Export datasets


export_csv(
    entities,
    "../data/generated/cse_entities.csv"
)


export_csv(
    assets,
    "../data/generated/assets.csv"
)


export_csv(
    analysts,
    "../data/generated/analysts.csv"
)



export_csv(
    alerts,
    "../data/generated/alerts.csv"
)

export_csv(

    investigations,

    "../data/generated/investigations.csv"

)

print("\nRISK ASSESSMENT")

print(risk)

print("\nRISK EXPLANATION")

print(explanation)

generate_features(

    "../data/generated/alerts.csv",

    "../data/generated/investigations.csv",

    "../data/generated/assets.csv",

    "../data/generated/features.csv"

)

train_anomaly_model(

    "../data/generated/features.csv",

    "../data/generated/isolation_forest.pkl"

)

generate_findings(

    "../data/generated/features_anomaly.csv",

    "../data/generated/supervisory_findings.csv"

)

export_csv(

    monitoring,

    "../data/generated/monitoring_coverage.csv"

)

generate_negative_space_findings(

    "../data/generated/monitoring_coverage.csv",

    "../data/generated/alerts.csv",

    "../data/generated/negative_space_findings.csv"

)