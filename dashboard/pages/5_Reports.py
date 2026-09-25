import os
import sys
import json
from datetime import datetime

import streamlit as st
import pandas as pd

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    ),
)

from utils import intelligence as intelligence_util
from utils.portal_style import (
    inject_css,
    risk_pill,
    anomaly_pill,
    source_pill,
    pattern_pill,
    section_label,
    footnote,
)


st.set_page_config(
    page_title="Assessment Reports",
    layout="wide"
)


inject_css()


# =====================================================
# PATH
# =====================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    )
)


DATA_PATH = os.path.join(
    BASE_DIR,
    "data",
    "generated"
)



# =====================================================
# HEADER
# =====================================================

st.title(
    "Assessment Reports"
)


st.markdown(
"""
Supervisory assessment reports generated from
SAT-SA evaluation results.
"""
)


st.divider()



# =====================================================
# REPORT STATUS
# =====================================================


section_label("Report Repository")



report_file = os.path.join(

    DATA_PATH,

    "SAT_SA_Supervisory_Assessment_Report.pdf"

)



if os.path.exists(report_file):


    st.success(
        "Supervisory Assessment Report Available"
    )


    file_size = round(

        os.path.getsize(report_file)
        /
        1024,

        2

    )


    st.write(
        f"Report Size: {file_size} KB"
    )


    st.write(
        f"Generated: {datetime.fromtimestamp(os.path.getmtime(report_file))}"
    )


else:

    st.warning(
        "Assessment report not generated yet."
    )



st.divider()



# =====================================================
# DOWNLOAD REPORT
# =====================================================


st.subheader(
"Download Reports"
)



if os.path.exists(report_file):


    with open(
        report_file,
        "rb"
    ) as f:


        st.download_button(

            label="Download SAT-SA Supervisory Assessment Report",

            data=f,

            file_name=
            "SAT-SA_Supervisory_Assessment_Report.pdf",

            mime="application/pdf"

        )



else:

    st.info(
        "Generate the report from assessment engine before downloading."
    )



st.divider()



# =====================================================
# RECOMMENDATION REGISTER
# =====================================================

section_label("Supervisory Recommendation Register")


intelligence = intelligence_util.build_intelligence()


register_rows = []

for entity in sorted(
    intelligence.values(),
    key=lambda item: (
        -item["anomaly_score"],
        -item["risk_score"],
    ),
):

    register_rows.append(
        {
            "Entity": entity["cse_id"],
            "Risk Level": risk_pill(entity["risk_level"]),
            "Anomaly Status": anomaly_pill(entity["anomaly_status"]),
            "Primary Pattern": pattern_pill(
                entity["primary_pattern"]
                or "None"
            ),
            "Recommendation Source": source_pill(
                entity["recommendation_source"]
            ),
        }
    )


register_view = pd.DataFrame(
    register_rows
)


st.markdown(
    register_view.to_html(
        escape=False,
        index=False,
    ),
    unsafe_allow_html=True,
)


st.caption(
    "Detailed recommended actions per entity are provided below."
)


for entity in sorted(
    intelligence.values(),
    key=lambda item: (
        -item["anomaly_score"],
        -item["risk_score"],
    ),
):

    with st.expander(
        f"{entity['cse_id']} — {entity['risk_level']} / "
        f"{entity['anomaly_status']}"
    ):

        st.markdown(
            f"**Recommendation Source:** "
            f"{source_pill(entity['recommendation_source'])}",
            unsafe_allow_html=True,
        )

        for action in entity.get(
            "recommendations",
            [],
        ):

            st.markdown(
                f"•  {action}"
            )

        reasons = entity.get(
            "recommendation_reason",
            [],
        )

        if reasons:

            st.markdown(
                "**Basis:** "
                + " ; ".join(
                    reasons
                )
            )


st.divider()



# =====================================================
# AVAILABLE REPORT TYPES
# =====================================================


st.subheader(
"Available Assessment Documents"
)



reports = [

{

"Report":

"Consolidated Supervisory Assessment Report",

"Purpose":

"Overall assessment of SOC capability maturity across evaluated entities."

},


{

"Report":

"Entity Assessment Report",

"Purpose":

"Detailed assessment of individual CSE risk posture and observations."

},


{

"Report":

"Findings Evidence Annexure",

"Purpose":

"Supporting evidence and validation details for identified findings."

}

]



for report in reports:


    with st.expander(
        report["Report"]
    ):


        st.write(
            report["Purpose"]
        )


footnote(
    "The recommendation register consolidates anomaly, pattern and "
    "ML/Rule signals to support report preparation."
)