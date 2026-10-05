import json
import pandas as pd



def generate_recommendations(

        risk_profile_file,

        output_file

):


    print("[+] Loading CSE risk profiles...")


    with open(

        risk_profile_file,

        "r"

    ) as f:

        profiles = json.load(f)



    recommendations = []



    for profile in profiles:


        cse_id = profile["cse_id"]



        overall = profile["overall_risk"]["level"]



        priority = profile["review_priority"]



        capabilities = profile["capability_assessment"]



        drivers = profile["risk_drivers"]



        actions = []

        reasons = []



        # ----------------------------
        # Detection Capability
        # ----------------------------


        if capabilities["detection"]["risk"] == "HIGH":


            actions.append(

                "Review threat detection effectiveness and validate alert coverage"

            )


            reasons.append(

                "High detection risk identified"

            )



        elif capabilities["detection"]["risk"] == "MEDIUM":


            actions.append(

                "Assess detection use cases and alert handling maturity"

            )


            reasons.append(

                "Detection capability requires improvement"

            )



        # ----------------------------
        # Investigation Capability
        # ----------------------------


        if capabilities["investigation"]["risk"] == "HIGH":


            actions.append(

                "Perform SOC investigation workflow review and validate RCA quality"

            )


            reasons.append(

                "Investigation maturity weakness detected"

            )


        elif capabilities["investigation"]["risk"] == "MEDIUM":


            actions.append(

                "Review investigation documentation and evidence collection practices"

            )


            reasons.append(

                "Investigation process requires monitoring"

            )



        # ----------------------------
        # Monitoring Capability
        # ----------------------------


        if capabilities["monitoring"]["risk"] == "HIGH":


            actions.append(

                "Assess critical asset monitoring coverage and telemetry availability"

            )


            reasons.append(

                "Monitoring coverage weakness detected"

            )


        elif capabilities["monitoring"]["risk"] == "MEDIUM":


            actions.append(

                "Review monitoring coverage for important assets"

            )


            reasons.append(

                "Potential visibility gaps detected"

            )



        # ----------------------------
        # Overall Risk
        # ----------------------------


        if overall == "HIGH":


            actions.append(

                "Conduct detailed supervisory examination and sample-based validation"

            )


            reasons.append(

                "Entity requires immediate supervisory attention"

            )



        elif overall == "MEDIUM":


            actions.append(

                "Conduct targeted review of identified control weaknesses"

            )



        if len(actions) == 0:


            actions.append(

                "Continue periodic supervisory monitoring"

            )


            reasons.append(

                "No significant supervisory concern identified"

            )



        recommendation = {


            "cse_id":

                cse_id,


            "risk_level":

                overall,


            "review_priority":

                priority,


            "recommended_actions":

                actions,


            "reason":

                reasons,


            "risk_drivers":

                drivers

        }



        recommendations.append(

            recommendation

        )



    with open(

        output_file,

        "w"

    ) as f:


        json.dump(

            recommendations,

            f,

            indent=4

        )



    print(

        "[+] Supervisory recommendations generated:",

        output_file

    )


    return recommendations