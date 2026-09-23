import pandas as pd



SEVERITY_WEIGHT = {

    "LOW": 1,
    "MEDIUM": 3,
    "HIGH": 5,
    "CRITICAL": 10

}



def risk_level(score):

    if score >= 61:

        return "HIGH"

    elif score >= 31:

        return "MEDIUM"

    else:

        return "LOW"




def generate_entity_assessment(

        execution_file,

        negative_space_file,

        output_file

):


    print("[+] Loading supervisory findings...")



    execution = pd.read_csv(

        execution_file

    ).fillna("")



    negative = pd.read_csv(

        negative_space_file

    ).fillna("")



    # -----------------------------
    # Execution Gap Analysis
    # -----------------------------


    execution["weight"] = (

        execution["severity"]

        .map(SEVERITY_WEIGHT)

        .fillna(1)

    )


    execution_summary = (

        execution

        .groupby("cse_id")

        .agg(

            execution_gap_count=(

                "finding",

                "count"

            ),

            execution_gap_score=(

                "weight",

                "sum"

            )

        )

        .reset_index()

    )



    # -----------------------------
    # Negative Space Analysis
    # -----------------------------


    negative["weight"] = (

        negative["severity"]

        .map(SEVERITY_WEIGHT)

        .fillna(1)

    )


    negative_summary = (

        negative

        .groupby("cse_id")

        .agg(

            negative_space_count=(

                "finding",

                "count"

            ),

            negative_space_score=(

                "weight",

                "sum"

            )

        )

        .reset_index()

    )



    # -----------------------------
    # Merge
    # -----------------------------


    result = execution_summary.merge(

        negative_summary,

        on="cse_id",

        how="outer"

    ).fillna(0)



    result["total_findings"] = (

        result["execution_gap_count"]

        +

        result["negative_space_count"]

    )



    # -----------------------------
    # Domain Risk
    # -----------------------------


    result["execution_risk"] = (

        result["execution_gap_score"]

        *

        0.7

    ).clip(

        upper=50

    )



    result["monitoring_risk"] = (

        result["negative_space_score"]

        *

        0.8

    ).clip(

        upper=30

    )



    result["investigation_penalty"] = (

        result["execution_gap_count"]

        .apply(

            lambda x:

            10 if x >= 15

            else

            5 if x >= 5

            else 0

        )

    )



    result["critical_monitoring_penalty"] = (

        result["negative_space_count"]

        .apply(

            lambda x:

            10 if x >= 5

            else

            5 if x >= 2

            else 0

        )

    )



    # -----------------------------
    # Final Risk Score
    # -----------------------------


    result["risk_score"] = (

        result["execution_risk"]

        +

        result["monitoring_risk"]

        +

        result["investigation_penalty"]

        +

        result["critical_monitoring_penalty"]

    ).clip(

        upper=100

    )



    result["risk_score"] = (

        result["risk_score"]

        .round(2)

    )



    result["risk_level"] = (

        result["risk_score"]

        .apply(risk_level)

    )



    # -----------------------------
    # Supervisory Drivers
    # -----------------------------


    drivers = []



    for _, row in result.iterrows():

        reasons = []


        if row["execution_gap_count"] > 0:

            reasons.append(

                f"{int(row['execution_gap_count'])} execution gap indicators"

            )


        if row["negative_space_count"] > 0:

            reasons.append(

                f"{int(row['negative_space_count'])} monitoring coverage gaps"

            )


        if row["investigation_penalty"] > 0:

            reasons.append(

                "Investigation maturity concerns"

            )


        if row["critical_monitoring_penalty"] > 0:

            reasons.append(

                "Critical asset visibility concerns"

            )


        drivers.append(

            " | ".join(reasons)

        )



    result["risk_drivers"] = drivers



    # -----------------------------
    # Review Priority
    # -----------------------------


    result["review_priority"] = result.apply(

        lambda row:

        "IMMEDIATE REVIEW"

        if (

            row["risk_level"] == "HIGH"

            or

            row["investigation_penalty"] >= 10

        )

        else

        (

            "TARGETED REVIEW"

            if row["risk_level"] == "MEDIUM"

            else

            "ROUTINE REVIEW"

        ),

        axis=1

    )



    result.to_csv(

        output_file,

        index=False

    )



    print(

        "[+] Entity Risk Assessment v3 generated:",

        output_file

    )


    return result