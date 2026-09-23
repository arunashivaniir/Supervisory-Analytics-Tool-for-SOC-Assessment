import pandas as pd



def generate_findings(

        anomaly_file,

        output_file

):


    df = pd.read_csv(

        anomaly_file

    ).fillna(0)



    findings = []



    for _, row in df.iterrows():


        evidence = []

        finding = None

        severity = "LOW"



        # --------------------------------
        # 1. Potential Superficial Investigation
        # --------------------------------


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




        # --------------------------------
        # 2. Suspicious Fast Closure
        # --------------------------------


        if row["fast_closure"] == 1:


            if finding is None:

                finding = (

                    "Suspicious Fast Alert Closure"

                )


            evidence.append(

                "High severity alert closed unusually quickly"

            )


            severity = "HIGH"




        # --------------------------------
        # 3. Template Driven Investigation
        # --------------------------------


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





        # --------------------------------
        # 4. Missing Escalation
        # --------------------------------


        if row["missing_escalation"] == 1:


            if finding is None:

                finding = (

                    "Critical Alert Escalation Gap"

                )


            evidence.append(

                "Critical alert lacks escalation record"

            )


            severity = "CRITICAL"





        # --------------------------------
        # 5. ML Anomaly Evidence
        # --------------------------------


        if row["anomaly_prediction"] == -1:


            evidence.append(

                "Detected as anomalous by Isolation Forest"

            )




        # --------------------------------
        # Create Finding
        # --------------------------------


        if finding is not None:


            findings.append({

                "alert_id":

                    row["alert_id"],



                "cse_id":

                    row["cse_id"],



                "asset_id":

                    row["asset_id"],



                "finding":

                    finding,



                "severity":

                    severity,



                "anomaly_score":

                    row["anomaly_score"],



                "evidence":

                    " | ".join(evidence)

            })




    result = pd.DataFrame(

        findings

    )



    result.to_csv(

        output_file,

        index=False

    )



    print(

        "[+] Findings generated:",

        output_file

    )


    print(

        "[+] Total findings:",

        len(result)

    )



    return result