"""
SAT-SA Feature Registry

Defines available supervisory analytics features
and their evidence requirements.
"""


FEATURE_REGISTRY = {


    "FAST_CLOSURE_RISK": {

        "description":
        "Identifies unusually fast alert closure behaviour",

        "category":
        "SECURITY_OPERATIONS",

        "required_fields": [

            "alert_context.timestamp",

            "response_context.resolution_time"

        ]

    },


    "SEVERITY_RISK": {

        "description":
        "Evaluates risk based on alert severity",

        "category":
        "DETECTION",

        "required_fields": [

            "alert_context.severity"

        ]

    },


    "INVESTIGATION_QUALITY": {

        "description":
        "Evaluates investigation completeness",

        "category":
        "INVESTIGATION",

        "required_fields": [

            "investigation_context.notes",

            "investigation_context.root_cause_identified",

            "investigation_context.evidence_available"

        ]

    },


    "ESCALATION_GAP": {

        "description":
        "Detects missing escalation evidence",

        "category":
        "ESCALATION",

        "required_fields": [

            "response_context.escalation_status",

            "alert_context.severity"

        ]

    },


    "ASSET_CRITICALITY_RISK": {

        "description":
        "Evaluates impact based on asset importance",

        "category":
        "ASSET_CONTEXT",

        "required_fields": [

            "asset_context.criticality"

        ]

    },


    "MONITORING_VISIBILITY_GAP": {

        "description":
        "Identifies monitoring coverage weakness",

        "category":
        "MONITORING_COVERAGE",

        "required_fields": [

            "monitoring_context.telemetry_available"

        ]

    }


}


def get_feature_registry():

    return FEATURE_REGISTRY