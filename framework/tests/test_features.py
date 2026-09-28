from framework.features.adaptive_feature_engine import (
    AdaptiveFeatureEngine
)



sample = {


"alert_context":{

    "severity":"HIGH",

    "timestamp":
    "2026-09-24"

},


"response_context":{

    "resolution_time":30

},


"investigation_context":{

    "notes":
    "Investigation completed",

    "root_cause_identified":
    True,

    "evidence_available":
    True

},


"asset_context":{

    "criticality":
    "TIER-1"

}

}



engine = AdaptiveFeatureEngine()


result = engine.evaluate_available_features(
    sample
)


for feature in result:

    print(feature)