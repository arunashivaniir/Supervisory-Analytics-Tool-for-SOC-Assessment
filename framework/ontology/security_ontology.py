"""
SAT-SA Security Ontology

Defines standard supervisory security concepts
used internally by the framework.

External datasets are mapped into these concepts.
"""


SAT_SA_CONCEPTS = {


    "DETECTION": {

        "description":
        "Ability to identify security events and threats",

        "indicators": [

            "alert_generation",
            "detection_coverage",
            "threat_identification",
            "alert_quality"

        ]

    },


    "INVESTIGATION": {

        "description":
        "Quality and completeness of security investigation",

        "indicators": [

            "investigation_notes",
            "root_cause",
            "analysis_quality",
            "evidence_collection"

        ]

    },


    "ESCALATION": {

        "description":
        "Effectiveness of alert escalation processes",

        "indicators": [

            "escalation_status",
            "approval_flow",
            "severity_handling"

        ]

    },


    "INCIDENT_RESPONSE": {

        "description":
        "Response and remediation capability",

        "indicators": [

            "response_time",
            "resolution_time",
            "remediation_action"

        ]

    },


    "SECURITY_OPERATIONS": {

        "description":
        "Operational discipline of SOC processes",

        "indicators": [

            "closure_behaviour",
            "workflow_execution",
            "case_management"

        ]

    },


    "MONITORING_COVERAGE": {

        "description":
        "Visibility and telemetry coverage",

        "indicators": [

            "telemetry",
            "logging",
            "coverage",
            "visibility"

        ]

    },


    "ASSET_CONTEXT": {

        "description":
        "Criticality and importance of monitored assets",

        "indicators": [

            "asset_id",
            "asset_type",
            "criticality"

        ]

    },


    "GOVERNANCE": {

        "description":
        "Oversight and control maturity",

        "indicators": [

            "policy",
            "compliance",
            "review"

        ]

    }

}


def get_concepts():

    return SAT_SA_CONCEPTS