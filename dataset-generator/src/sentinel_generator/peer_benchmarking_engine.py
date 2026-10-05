import json
import statistics



def generate_peer_benchmark(

        risk_profile_file,

        output_file

):


    print("[+] Loading CSE risk profiles...")


    with open(

        risk_profile_file,

        "r"

    ) as f:

        profiles = json.load(f)



    if len(profiles) < 2:

        raise Exception(

            "Peer benchmarking requires multiple entities"

        )



    # -------------------------------
    # Calculate Peer Baselines
    # -------------------------------


    avg_risk = statistics.mean(

        [

            p["overall_risk"]["score"]

            for p in profiles

        ]

    )


    avg_execution = statistics.mean(

        [

            p["findings"]["execution_gaps"]

            for p in profiles

        ]

    )


    avg_negative = statistics.mean(

        [

            p["findings"]["negative_space"]

            for p in profiles

        ]

    )



    results = []



    for profile in profiles:


        findings = []



        risk_score = profile["overall_risk"]["score"]


        execution_gap = profile["findings"]["execution_gaps"]


        negative_space = profile["findings"]["negative_space"]



        risk_deviation = (

            risk_score - avg_risk

        )



        execution_deviation = (

            execution_gap - avg_execution

        )



        negative_deviation = (

            negative_space - avg_negative

        )



        # -------------------------------
        # Peer Deviations
        # -------------------------------


        if risk_deviation > 20:


            findings.append(

                "Overall risk significantly above peer baseline"

            )



        if execution_deviation > 5:


            findings.append(

                "Execution gap concentration higher than peer entities"

            )



        if negative_deviation > 3:


            findings.append(

                "Monitoring coverage weakness exceeds peer baseline"

            )



        if len(findings) == 0:


            findings.append(

                "No significant deviation from peer baseline"

            )



        result = {


            "cse_id":

                profile["cse_id"],



            "peer_baseline":{


                "average_risk_score":

                    round(avg_risk,2),


                "average_execution_gaps":

                    round(avg_execution,2),


                "average_negative_space":

                    round(avg_negative,2)

            },



            "entity_metrics":{


                "risk_score":

                    risk_score,


                "execution_gaps":

                    execution_gap,


                "negative_space":

                    negative_space

            },



            "deviation":{


                "risk_score_difference":

                    round(risk_deviation,2),


                "execution_gap_difference":

                    round(execution_deviation,2),


                "negative_space_difference":

                    round(negative_deviation,2)

            },



            "peer_findings":

                findings

        }



        results.append(result)



    with open(

        output_file,

        "w"

    ) as f:


        json.dump(

            results,

            f,

            indent=4

        )



    print(

        "[+] Peer benchmarking generated:",

        output_file

    )


    return results