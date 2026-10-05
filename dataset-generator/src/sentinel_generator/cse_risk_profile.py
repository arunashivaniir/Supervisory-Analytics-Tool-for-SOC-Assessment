import pandas as pd
import json



def calculate_capability_risk(value):

    if value >= 40:

        return "HIGH"

    elif value >= 15:

        return "MEDIUM"

    else:

        return "LOW"



def generate_cse_risk_profiles(

        assessment_file,

        output_file

):


    print("[+] Loading CSE assessment...")


    assessment = pd.read_csv(

        assessment_file

    ).fillna(0)



    profiles = []



    for _, row in assessment.iterrows():


        detection_risk = calculate_capability_risk(

            row["execution_risk"]

        )


        investigation_risk = calculate_capability_risk(

            row["investigation_penalty"]

            +

            row["execution_risk"]

        )


        monitoring_risk = calculate_capability_risk(

            row["monitoring_risk"]

        )



        profile = {


            "cse_id":

                row["cse_id"],



            "overall_risk":{


                "score":

                    float(row["risk_score"]),


                "level":

                    row["risk_level"]

            },



            "findings":{


                "total":

                    int(row["total_findings"]),


                "execution_gaps":

                    int(row["execution_gap_count"]),


                "negative_space":

                    int(row["negative_space_count"])

            },



            "capability_assessment":{


                "detection":{

                    "risk":

                        detection_risk

                },


                "investigation":{

                    "risk":

                        investigation_risk

                },


                "monitoring":{

                    "risk":

                        monitoring_risk

                }

            },



            "risk_breakdown":{


                "execution_risk":

                    float(row["execution_risk"]),


                "monitoring_risk":

                    float(row["monitoring_risk"]),


                "investigation_penalty":

                    float(row["investigation_penalty"]),


                "critical_asset_penalty":

                    float(row["critical_monitoring_penalty"])

            },



            "risk_drivers":

                str(row["risk_drivers"]).split("|"),



            "review_priority":

                row["review_priority"]

        }



        profiles.append(profile)



    with open(

        output_file,

        "w"

    ) as f:


        json.dump(

            profiles,

            f,

            indent=4

        )



    print(

        "[+] CSE risk profiles generated:",

        output_file

    )


    return profiles