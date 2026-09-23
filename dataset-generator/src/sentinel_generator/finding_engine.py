import pandas as pd



def generate_findings(
        anomaly_file,
        output_file
):


    df = pd.read_csv(
        anomaly_file
    )


    findings = []


    for _, row in df.iterrows():


        evidence = []

        finding = None

        severity = "LOW"



        # ---------------------------------
        # Rule 1:
        # Superficial Investigation
        # ---------------------------------

        if (

            row["missing_evidence"] == 1

            and

            row["missing_root_cause"] == 1

            and

            row["missing_remediation"] == 1

        ):


            finding = (
                "Potential Superficial Investigation"
            )


            severity = "HIGH"


            evidence.extend([

                "No investigation evidence recorded",

                "Root cause not identified",

                "No remediation action recorded"

            ])



        # ---------------------------------
        # Rule 2:
        # Fast Closure Risk
        # ---------------------------------

        if row["fast_closure"] == 1:


            if finding is None:

                finding = (
                    "Suspicious Fast Alert Closure"
                )


            evidence.append(

                "High severity alert closed unusually quickly"

            )

            severity = "HIGH"



        # ---------------------------------
        # Rule 3:
        # Template Investigation
        # ---------------------------------

        if row["template_investigation"] == 1:


            if finding is None:

                finding = (
                    "Template Driven Investigation Behaviour"
                )


            evidence.append(

                "Investigation notes show high similarity"

            )



            if severity == "LOW":

                severity = "MEDIUM"



        # ---------------------------------
        # Rule 4:
        # Missing Escalation
        # ---------------------------------

        if row["missing_escalation"] == 1:


            if finding is None:

                finding = (
                    "Critical Alert Escalation Gap"
                )


            evidence.append(

                "Critical alert lacks escalation record"

            )


            severity = "CRITICAL"



        # ---------------------------------
        # Add ML Anomaly Evidence
        # ---------------------------------

        if row["anomaly_prediction"] == -1:


            evidence.append(

                "Detected as anomalous by Isolation Forest"

            )


        # ---------------------------------
        # Create Finding
        # ---------------------------------

        if finding is not None:


            findings.append({

                "alert_id":

                    row["alert_id"],


                "finding":

                    finding,


                "severity":

                    severity,


                "anomaly_score":

                    row["anomaly_score"],


                "evidence":

                    " | ".join(evidence)

            })



    findings_df = pd.DataFrame(
        findings
    )


    findings_df.to_csv(

        output_file,

        index=False

    )


    print(

        "[+] Findings generated:",

        output_file

    )


    print(

        "[+] Total findings:",

        len(findings_df)

    )


    return findings_df