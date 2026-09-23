import pandas as pd



def generate_negative_space_findings(

        coverage_file,

        alerts_file,

        output_file

):


    coverage = pd.read_csv(

        coverage_file

    ).fillna("")



    alerts = pd.read_csv(

        alerts_file

    ).fillna("")



    findings = []



    for _, row in coverage.iterrows():


        asset_id = row["asset_id"]

        cse_id = row["cse_id"]



        asset_alerts = alerts[

            alerts["asset_id"]

            ==

            asset_id

        ]



        # --------------------------------
        # 1. Missing Telemetry Detection
        # --------------------------------

        if (

            row["telemetry_available"]

            ==

            "NO"

            and

            row["criticality"]

            in

            [

                "TIER-0",

                "TIER-1"

            ]

        ):


            findings.append({

                "asset_id":

                    asset_id,

                
                "cse_id":

                    cse_id,


                "finding":

                    "Potential Monitoring Blind Spot",


                "severity":

                    "HIGH",


                "evidence":

                    "Critical asset has no telemetry availability"

            })



        # --------------------------------
        # 2. Unexpectedly Low Activity
        # --------------------------------

        if (

            len(asset_alerts)

            ==

            0

            and

            row["criticality"]

            ==

            "TIER-0"

        ):


            findings.append({

                "asset_id":

                    asset_id,


                "cse_id":

                    cse_id,


                "finding":

                    "Unexpectedly Low Security Activity",


                "severity":

                    "MEDIUM",


                "evidence":

                    "Critical asset generated no security alerts"

            })



        # --------------------------------
        # 3. Missing Monitoring Coverage
        # --------------------------------


        expected_monitoring = str(

            row["expected_monitoring"]

        )


        actual_monitoring = str(

            row["actual_monitoring"]

        )



        if expected_monitoring in ["nan", ""]:

            expected_monitoring = ""



        if actual_monitoring in ["nan", ""]:

            actual_monitoring = ""



        expected = set(

            filter(

                None,

                expected_monitoring.split("|")

            )

        )


        actual = set(

            filter(

                None,

                actual_monitoring.split("|")

            )

        )



        missing_controls = expected - actual



        if len(missing_controls) > 0:


            findings.append({

                "asset_id":

                    asset_id,


                "cse_id":

                    cse_id,


                "finding":

                    "Missing Monitoring Coverage",


                "severity":

                    "HIGH",


                "evidence":

                    "Missing controls: "

                    +

                    ",".join(

                        missing_controls

                    )

            })



    result = pd.DataFrame(

        findings

    )



    result.to_csv(

        output_file,

        index=False

    )



    print(

        "[+] Negative space findings:",

        len(result)

    )



    return result