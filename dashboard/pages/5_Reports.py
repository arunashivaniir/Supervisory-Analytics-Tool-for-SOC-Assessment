import streamlit as st
import os
import json
from datetime import datetime


st.set_page_config(
    page_title="Assessment Reports",
    layout="wide"
)


# =====================================================
# PATH
# =====================================================

BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.abspath(__file__)
    )
)


DATA_PATH = os.path.join(
    BASE_DIR,
    "..",
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


st.subheader(
"Report Repository"
)



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