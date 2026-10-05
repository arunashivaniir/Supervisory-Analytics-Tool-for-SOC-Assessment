import streamlit as st
import json
import os
import pandas as pd


st.set_page_config(
    page_title="Entity Assessment",
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
# LOAD DATA
# =====================================================

@st.cache_data
def load_profiles():

    with open(
        os.path.join(
            DATA_PATH,
            "cse_risk_profiles.json"
        )
    ) as f:

        return json.load(f)



profiles = load_profiles()



# =====================================================
# HEADER
# =====================================================


st.title(
    "Entity Risk Assessment"
)


st.markdown(
"""
Detailed supervisory assessment of individual
Critical Sector Entities (CSEs).
"""
)


st.divider()



# =====================================================
# ENTITY SELECT
# =====================================================


selected_cse = st.selectbox(

    "Select Entity",

    [
        x["cse_id"]
        for x in profiles
    ]

)



entity = next(

    x for x in profiles

    if x["cse_id"] == selected_cse

)



# =====================================================
# RISK SUMMARY
# =====================================================


st.subheader(
"Assessment Summary"
)



col1,col2,col3 = st.columns(3)



col1.metric(

    "Risk Score",

    f'{entity["overall_risk"]["score"]}/100'

)



col2.metric(

    "Risk Level",

    entity["overall_risk"]["level"]

)



col3.metric(

    "Review Priority",

    entity["review_priority"]

)



st.divider()



# =====================================================
# CAPABILITY ASSESSMENT
# =====================================================


st.subheader(

"Capability Assessment"

)



capability = pd.DataFrame(

[

{

"Capability":

"Detection",

"Assessment":

entity["capability_assessment"]
["detection"]
["risk"]

},


{

"Capability":

"Investigation",

"Assessment":

entity["capability_assessment"]
["investigation"]
["risk"]

},


{

"Capability":

"Monitoring",

"Assessment":

entity["capability_assessment"]
["monitoring"]
["risk"]

}

]

)



st.table(capability)



st.divider()



# =====================================================
# KEY OBSERVATIONS
# =====================================================


st.subheader(

"Key Observations"

)



for driver in entity["risk_drivers"]:

    st.write(

        "• " + driver

    )



st.divider()



# =====================================================
# SUPERVISORY ACTION
# =====================================================


st.subheader(

"Supervisory Assessment"

)



if entity["review_priority"] == "IMMEDIATE REVIEW":

    st.error(

"""
This entity requires immediate supervisory review.
Detailed validation of SOC processes, control effectiveness,
and operational maturity is recommended.
"""

    )


elif entity["review_priority"] == "TARGETED REVIEW":

    st.warning(

"""
This entity requires targeted review of identified
control weaknesses and capability gaps.
"""

    )


else:

    st.success(

"""
Entity remains under routine supervisory monitoring.
"""

    )



st.divider()



# =====================================================
# CONTROL MATURITY SUMMARY
# =====================================================


st.subheader(

"Control Maturity Summary"

)


st.markdown(

"""
**Detection Capability**

Assessment based on alert coverage, detection use cases,
and security monitoring effectiveness.


<br>

**Investigation Capability**

Assessment based on investigation workflow,
evidence collection, and root cause analysis.


<br>

**Monitoring Coverage**

Assessment based on visibility across critical assets
and required security controls.

""",

unsafe_allow_html=True

)