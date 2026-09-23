import pandas as pd

from sklearn.ensemble import IsolationForest

import joblib



def train_anomaly_model(
        feature_file,
        model_path
):


    print("[+] Loading features...")


    df = pd.read_csv(
        feature_file
    )


    # Remove identifier

    X = df.drop(

        columns=[

            "alert_id",

            "cse_id",

            "asset_id"

        ]

)



    print(
        "[+] Training Isolation Forest..."
    )


    model = IsolationForest(

        n_estimators=200,

        contamination=0.15,

        random_state=42

    )


    model.fit(X)



    # Prediction

    df["anomaly_prediction"] = model.predict(X)


    df["anomaly_score"] = model.decision_function(X)



    # Save model

    joblib.dump(

        model,

        model_path

    )



    output = feature_file.replace(

        ".csv",

        "_anomaly.csv"

    )


    df.to_csv(

        output,

        index=False

    )


    print(
        "[+] Model saved:",
        model_path
    )


    print(
        "[+] Anomaly results:",
        output
    )


    return df