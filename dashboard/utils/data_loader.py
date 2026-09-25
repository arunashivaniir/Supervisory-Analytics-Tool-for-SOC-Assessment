import os
import json
import pandas as pd


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



def load_profiles():

    with open(
        os.path.join(
            DATA_PATH,
            "cse_risk_profiles.json"
        )
    ) as f:

        return json.load(f)



def load_validation():

    with open(
        os.path.join(
            DATA_PATH,
            "finding_validation.json"
        )
    ) as f:

        return json.load(f)



def load_findings():

    return pd.read_csv(
        os.path.join(
            DATA_PATH,
            "supervisory_findings.csv"
        )
    )



def load_negative_space():

    return pd.read_csv(
        os.path.join(
            DATA_PATH,
            "negative_space_findings.csv"
        )
    )



def load_recommendations():

    with open(
        os.path.join(
            DATA_PATH,
            "supervisory_recommendations.json"
        )
    ) as f:

        return json.load(f)



def load_anomaly_features():

    return pd.read_csv(
        os.path.join(
            DATA_PATH,
            "features_anomaly.csv"
        )
    )



def load_monitoring_coverage():

    return pd.read_csv(
        os.path.join(
            DATA_PATH,
            "monitoring_coverage.csv"
        )
    )



def load_cse_entities():

    return pd.read_csv(
        os.path.join(
            DATA_PATH,
            "cse_entities.csv"
        )
    )