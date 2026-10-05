from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle
)

from reportlab.lib.styles import getSampleStyleSheet

from datetime import datetime

import json
import pandas as pd



def generate_supervisory_report(

        risk_profile_file,

        recommendation_file,

        peer_file,

        findings_file,

        negative_space_file,

        validation_file,

        output_file

):


    print("[+] Loading assessment data...")



    with open(risk_profile_file) as f:

        risk_profiles = json.load(f)



    with open(recommendation_file) as f:

        recommendations = json.load(f)



    with open(peer_file) as f:

        peer_results = json.load(f)



    with open(validation_file) as f:

        validation_results = json.load(f)



    findings = pd.read_csv(

        findings_file

    ).fillna("")



    negative = pd.read_csv(

        negative_space_file

    ).fillna("")




    doc = SimpleDocTemplate(

        output_file

    )



    styles = getSampleStyleSheet()

    content = []



    # ==================================================
    # Cover Page
    # ==================================================


    content.append(

        Paragraph(

            "National Critical Information Infrastructure Protection Centre",

            styles["Title"]

        )

    )


    content.append(Spacer(1,20))


    content.append(

        Paragraph(

            "Supervisory Analytics Tool for SOC Assessment (SAT-SA)",

            styles["Heading2"]

        )

    )


    content.append(Spacer(1,20))


    content.append(

        Paragraph(

            "SOC Supervisory Assessment Report",

            styles["Heading1"]

        )

    )


    content.append(

        Paragraph(

            f"Generated Date: {datetime.now()}",

            styles["Normal"]

        )

    )


    content.append(Spacer(1,40))



    # ==================================================
    # Global Validation Summary
    # ==================================================


    total_validation = len(validation_results)


    supported = len(

        [

            x for x in validation_results

            if x["validation_status"]

            ==

            "EVIDENCE_SUPPORTED"

        ]

    )


    review_required = len(

        [

            x for x in validation_results

            if x["validation_status"]

            ==

            "REQUIRES_REVIEW"

        ]

    )


    average_confidence = round(

        sum(

            x["confidence_score"]

            for x in validation_results

        )

        /

        total_validation,

        2

    ) if total_validation else 0



    content.append(

        Paragraph(

            "Validation & Explainability Summary",

            styles["Heading1"]

        )

    )


    validation_summary = [

        [

            "Metric",

            "Value"

        ],

        [

            "Total Findings",

            str(total_validation)

        ],

        [

            "Evidence Supported",

            str(supported)

        ],

        [

            "Requires Review",

            str(review_required)

        ],

        [

            "Average Confidence",

            f"{average_confidence}%"

        ]

    ]



    table = Table(

        validation_summary

    )


    table.setStyle(

        TableStyle(

            [

                ("GRID",(0,0),(-1,-1),0.5,None)

            ]

        )

    )


    content.append(table)

    content.append(Spacer(1,30))



    # ==================================================
    # Entity Assessment
    # ==================================================


    for profile in risk_profiles:


        cse_id = profile["cse_id"]



        content.append(

            Paragraph(

                f"Entity Assessment: {cse_id}",

                styles["Heading1"]

            )

        )



        risk = profile["overall_risk"]



        content.append(

            Paragraph(

                f"""

                Overall Risk Score:
                {risk['score']}/100

                <br/>

                Risk Level:
                {risk['level']}

                <br/>

                Review Priority:
                {profile['review_priority']}

                """,

                styles["Normal"]

            )

        )



        content.append(

            Spacer(1,15)

        )



        # ==================================================
        # Capability Assessment
        # ==================================================


        content.append(

            Paragraph(

                "Capability Assessment",

                styles["Heading2"]

            )

        )



        capability_data = [

            [

                "Capability",

                "Risk"

            ],

            [

                "Detection",

                profile["capability_assessment"]

                ["detection"]

                ["risk"]

            ],

            [

                "Investigation",

                profile["capability_assessment"]

                ["investigation"]

                ["risk"]

            ],

            [

                "Monitoring",

                profile["capability_assessment"]

                ["monitoring"]

                ["risk"]

            ]

        ]



        table = Table(

            capability_data

        )


        table.setStyle(

            TableStyle(

                [

                    ("GRID",(0,0),(-1,-1),0.5,None)

                ]

            )

        )


        content.append(table)



        content.append(

            Spacer(1,20)

        )



        # ==================================================
        # Risk Drivers
        # ==================================================


        content.append(

            Paragraph(

                "Risk Drivers",

                styles["Heading2"]

            )

        )


        for driver in profile["risk_drivers"]:


            content.append(

                Paragraph(

                    "• " + driver,

                    styles["Normal"]

                )

            )



        content.append(

            Spacer(1,20)

        )



        # ==================================================
        # Validation Findings for CSE
        # ==================================================


        content.append(

            Paragraph(

                "Finding Validation",

                styles["Heading2"]

            )

        )



        cse_validations = [

            x for x in validation_results

            if cse_id in str(x)

        ]



        if cse_validations:


            for finding in cse_validations:


                content.append(

                    Paragraph(

                        f"""

                        Finding:

                        {finding['finding']}

                        <br/>

                        Alert:

                        {finding['alert_id']}

                        <br/>

                        Confidence:

                        {finding['confidence_score']}%

                        <br/>

                        Status:

                        {finding['validation_status']}

                        <br/>

                        Evidence:

                        {finding['evidence']}

                        """,

                        styles["Normal"]

                    )

                )

                content.append(

                    Spacer(1,10)

                )


        else:


            content.append(

                Paragraph(

                    "No validated findings mapped.",

                    styles["Normal"]

                )

            )



        content.append(

            Spacer(1,20)

        )



        # ==================================================
        # Recommendations
        # ==================================================


        content.append(

            Paragraph(

                "Recommended Supervisory Actions",

                styles["Heading2"]

            )

        )



        rec = next(

            (

                r for r in recommendations

                if r["cse_id"] == cse_id

            ),

            None

        )



        if rec:


            for action in rec["recommended_actions"]:


                content.append(

                    Paragraph(

                        "• " + action,

                        styles["Normal"]

                    )

                )



        content.append(

            Spacer(1,20)

        )



        # ==================================================
        # Peer Benchmarking
        # ==================================================


        content.append(

            Paragraph(

                "Peer Benchmarking",

                styles["Heading2"]

            )

        )


        peer = next(

            (

                p for p in peer_results

                if p["cse_id"] == cse_id

            ),

            None

        )


        if peer:


            for finding in peer["peer_findings"]:


                content.append(

                    Paragraph(

                        "• " + finding,

                        styles["Normal"]

                    )

                )



        content.append(

            Spacer(1,30)

        )



    doc.build(content)



    print(

        "[+] SAT-SA Supervisory Report generated:",

        output_file

    )