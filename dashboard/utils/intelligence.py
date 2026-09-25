import os
import json
import csv
from collections import Counter, defaultdict

import pandas as pd


# =====================================================================
# SAT-SA Intelligence Builder
#
# Computes the supervisory intelligence signal for every assessed
# entity from the generated SAT-SA datasets under data/generated:
#
#   - cse_risk_profiles.json        (risk score / level, capability)
#   - supervisory_findings.csv      (validated finding observations)
#   - supervisory_recommendations.json (recommended supervisory actions)
#   - monitoring_coverage.csv       (asset-level telemetry visibility)
#   - features_anomaly.csv          (isolation-forest alert anomaly scores)
#
# Outputs per entity:
#   - attention score (0-100, severity + investigation quality weighted)
#   - anomaly score (0-1) and anomaly status
#   - supervisory finding composition
#   - correlated behaviour patterns
#   - ML/Rule recommendations with source attribution
#
# This module is pure Python (no Streamlit dependency) so it can be
# unit-checked with the standard interpreter.
# =====================================================================


BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)


DATA_PATH = os.path.join(
    BASE_DIR,
    "..",
    "data",
    "generated"
)


ANOMALY_THRESHOLD = 0.7

# Aligned with the framework EntityEvaluator severity weighting
SEVERITY_WEIGHT = {
    "4": 40,
    "3": 25,
    "2": 10,
    "1": 5,
}

# Aligned with the framework EntityEvaluator indicator weighting
INDICATOR_WEIGHT = {
    "fast_closure": 15,
    "low_investigation_quality": 20,
    "template_investigation": 10,
    "sla_breach": 5,
    "missing_evidence": 5,
    "missing_escalation": 5,
    "missing_root_cause": 5,
    "missing_remediation": 5,
}

# Correlated pattern labels consistent with the finding correlation layer
FINDING_PATTERNS = {
    "Suspicious Fast Alert Closure": "PREMATURE_ALERT_CLOSURE",
    "Potential Superficial Investigation": "INVESTIGATION_PROCESS_WEAKNESS",
    "Template Driven Investigation Behaviour": "TEMPLATE_INVESTIGATION_PATTERN",
    "Critical Alert Escalation Gap": "CRITICAL_ALERT_ESCALATION_GAP",
}

DRIVER_PATTERNS = (
    (
        (
            "execution gap",
        ),
        "EXECUTION_GAP_CLUSTER",
    ),
    (
        (
            "monitoring coverage",
            "visibility",
        ),
        "VISIBILITY_AND_RESPONSE_GAP",
    ),
    (
        (
            "investigation",
        ),
        "INVESTIGATION_PROCESS_WEAKNESS",
    ),
    (
        (
            "critical asset",
        ),
        "CRITICAL_ASSET_COVERAGE_GAP",
    ),
)

MULTI_CONTROL_PATTERN = "MULTIPLE_CONTROL_WEAKNESSES"

_CACHE = {
    "intelligence": None,
    "snapshot": None,
    "dataframe": None,
}



def _read_json(name):

    with open(
        os.path.join(
            DATA_PATH,
            name
        )
    ) as f:

        return json.load(f)



def _read_csv(name):

    with open(
        os.path.join(
            DATA_PATH,
            name
        )
    ) as f:

        return list(
            csv.DictReader(
                f
            )
        )



def _as_bool(value):

    return str(
        value
    ).strip() in (
        "1",
        "True",
        "true",
        "YES",
        "yes",
    )



def build_intelligence(
        refresh=False
):

    if (
        _CACHE["intelligence"] is not None
        and not refresh
    ):

        return _CACHE["intelligence"]

    profiles = _read_json(
        "cse_risk_profiles.json"
    )

    entity_rows = _read_csv(
        "cse_entities.csv"
    )

    entities = {
        row["cse_id"]: row
        for row in entity_rows
    }

    findings_rows = _read_csv(
        "supervisory_findings.csv"
    )

    recommendations = {
        row["cse_id"]: row
        for row in _read_json(
            "supervisory_recommendations.json"
        )
    }

    monitoring_rows = _read_csv(
        "monitoring_coverage.csv"
    )

    anomaly_rows = _read_csv(
        "features_anomaly.csv"
    )

    validation = _read_json(
        "finding_validation.json"
    )

    decisions = [
        float(
            row["anomaly_score"]
        )
        for row in anomaly_rows
    ]

    decision_min = min(
        decisions
    )

    decision_max = max(
        decisions
    )

    decision_span = (
        decision_max - decision_min
    ) or 1.0

    def alert_anomaly(decision):

        normalised = (
            float(decision) - decision_min
        ) / decision_span

        return min(
            max(
                1.0 - normalised,
                0.0
            ),
            1.0
        )

    ml_supported_count = Counter()

    for item in validation:

        if _as_bool(
            item.get(
                "ml_supported"
            )
        ):

            ml_supported_count[
                item.get(
                    "cse_id"
                )
            ] += 1

    findings_by_entity = defaultdict(
        list
    )

    anomaly_by_entity = defaultdict(
        list
    )

    monitoring_by_entity = defaultdict(
        list
    )

    for row in findings_rows:

        findings_by_entity[
            row["cse_id"]
        ].append(
            row
        )

    for row in anomaly_rows:

        anomaly_by_entity[
            row["cse_id"]
        ].append(
            row
        )

    for row in monitoring_rows:

        monitoring_by_entity[
            row["cse_id"]
        ].append(
            row
        )

    intelligence = {}

    for profile in profiles:

        cse_id = profile[
            "cse_id"
        ]

        alerts = anomaly_by_entity.get(
            cse_id,
            []
        )

        finding_rows = findings_by_entity.get(
            cse_id,
            []
        )

        monitoring = monitoring_by_entity.get(
            cse_id,
            []
        )

        entity = entities.get(
            cse_id,
            {}
        )

        recommendation = recommendations.get(
            cse_id,
            {}
        )

        # -------------------------------------------------------------
        # Attention score (0-100)
        # -------------------------------------------------------------
        attention_score = 0

        if alerts:

            per_alert = []

            for alert in alerts:

                weight = SEVERITY_WEIGHT.get(
                    alert.get(
                        "severity_score"
                    ),
                    5
                )

                for column, add in INDICATOR_WEIGHT.items():

                    if _as_bool(
                        alert.get(
                            column
                        )
                    ):

                        weight += add

                per_alert.append(
                    min(
                        weight,
                        100
                    )
                )

            attention_score = round(
                sum(per_alert) / len(per_alert)
            )

        # -------------------------------------------------------------
        # Anomaly score (0-1) from isolation-forest decision scores
        # -------------------------------------------------------------
        anomaly_score = 0.0

        anomalous_alerts = 0

        if alerts:

            alert_scores = [
                alert_anomaly(
                    alert["anomaly_score"]
                )
                for alert in alerts
            ]

            anomaly_score = round(
                max(alert_scores),
                2
            )

            anomalous_alerts = sum(
                1
                for alert in alerts
                if str(
                    alert.get(
                        "anomaly_prediction"
                    )
                ) == "-1"
            )

        anomaly_status = (
            "ANOMALOUS"
            if anomaly_score >= ANOMALY_THRESHOLD
            else "NORMAL"
        )

        # -------------------------------------------------------------
        # Supervisory finding composition
        # -------------------------------------------------------------
        severity_count = Counter(
            row.get(
                "severity"
            )
            for row in finding_rows
        )

        # -------------------------------------------------------------
        # Monitoring coverage gaps
        # -------------------------------------------------------------
        gaps = [
            row
            for row in monitoring
            if (
                str(
                    row.get(
                        "telemetry_available",
                        ""
                    )
                ).upper()
                == "NO"
                or not (
                    row.get(
                        "actual_monitoring"
                    )
                    or ""
                ).strip()
            )
        ]

        # -------------------------------------------------------------
        # Correlated behaviour patterns
        # -------------------------------------------------------------
        patterns = Counter()

        for row in finding_rows:

            pattern = FINDING_PATTERNS.get(
                row.get(
                    "finding"
                )
            )

            if pattern:

                patterns[pattern] += 1

        for driver in profile.get(
            "risk_drivers",
            []
        ):

            driver_text = str(
                driver
            ).lower()

            for keywords, pattern in DRIVER_PATTERNS:

                if any(
                    keyword in driver_text
                    for keyword in keywords
                ):

                    patterns[pattern] += 1

        correlated_patterns = sorted(
            patterns.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )

        if correlated_patterns:

            primary_pattern = correlated_patterns[0][0]

        else:

            primary_pattern = None

        multi_control = (
            len(correlated_patterns) >= 2
        )

        # -------------------------------------------------------------
        # Recommendations and source attribution
        # -------------------------------------------------------------
        recommendation_source = (
            "ML / Hybrid"
            if ml_supported_count.get(
                cse_id,
                0
            ) > 0
            else "Rule"
        )

        intelligence[cse_id] = {
            "cse_id": cse_id,
            "sector": entity.get(
                "sector",
                ""
            ),
            "organisation": entity.get(
                "organisation_name",
                ""
            ),
            "risk_score": profile["overall_risk"]["score"],
            "risk_level": profile["overall_risk"]["level"],
            "review_priority": profile.get(
                "review_priority",
                ""
            ),
            "capability": profile.get(
                "capability_assessment",
                {}
            ),
            "attention_score": attention_score,
            "anomaly_score": anomaly_score,
            "anomaly_status": anomaly_status,
            "anomalous_alerts": anomalous_alerts,
            "total_alerts": len(alerts),
            "monitoring_gaps": len(gaps),
            "findings_total": len(finding_rows),
            "findings_severity": dict(
                severity_count
            ),
            "correlated_patterns": correlated_patterns,
            "primary_pattern": primary_pattern,
            "pattern_count": len(
                correlated_patterns
            ),
            "multi_control": multi_control,
            "recommendations": recommendation.get(
                "recommended_actions",
                []
            ),
            "recommendation_reason": recommendation.get(
                "reason",
                []
            ),
            "recommendation_source": recommendation_source,
        }

    _CACHE["intelligence"] = intelligence

    return intelligence



def intelligence_dataframe():

    if _CACHE["dataframe"] is not None:

        return _CACHE["dataframe"]

    intelligence = build_intelligence()

    rows = []

    for entity in intelligence.values():

        rows.append(
            {
                "Entity": entity["cse_id"],
                "Sector": entity["sector"],
                "Organisation": entity["organisation"],
                "Risk Score": entity["risk_score"],
                "Risk Level": entity["risk_level"],
                "Attention Score": entity["attention_score"],
                "Anomaly Score": entity["anomaly_score"],
                "Anomaly Status": entity["anomaly_status"],
                "Findings": entity["findings_total"],
                "Monitoring Gaps": entity["monitoring_gaps"],
                "Primary Pattern": entity["primary_pattern"]
                or "None",
                "Recommendation": entity["recommendation_source"],
                "Review Priority": entity["review_priority"],
            }
        )

    frame = pd.DataFrame(
        rows
    ).sort_values(
        by=[
            "Anomaly Score",
            "Risk Score",
        ],
        ascending=[
            False,
            False,
        ],
    ).reset_index(
        drop=True
    )

    _CACHE["dataframe"] = frame

    return frame



def snapshot():

    if _CACHE["snapshot"] is not None:

        return _CACHE["snapshot"]

    intelligence = build_intelligence()

    entities = list(
        intelligence.values()
    )

    _CACHE["snapshot"] = {
        "entities": len(entities),
        "anomalous": sum(
            1
            for e in entities
            if e["anomaly_status"] == "ANOMALOUS"
        ),
        "high_risk": sum(
            1
            for e in entities
            if e["risk_level"] == "HIGH"
        ),
        "total_findings": sum(
            e["findings_total"]
            for e in entities
        ),
        "total_gaps": sum(
            e["monitoring_gaps"]
            for e in entities
        ),
        "total_alerts": sum(
            e["total_alerts"]
            for e in entities
        ),
        "ml_hybrid": sum(
            1
            for e in entities
            if e["recommendation_source"]
            == "ML / Hybrid"
        ),
    }

    return _CACHE["snapshot"]



def correlate_finding_pattern(
        finding_text
):

    return FINDING_PATTERNS.get(
        finding_text
    )