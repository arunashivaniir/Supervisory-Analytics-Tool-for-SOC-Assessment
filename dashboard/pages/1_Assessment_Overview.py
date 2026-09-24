import streamlit as st
import pandas as pd
import json
import os


# =====================================================
# PAGE CONFIG
# =====================================================

st.set_page_config(

    page_title="SAT-SA Assessment Overview",

    layout="wide"

)



# =====================================================
# DATA PATH
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


st.markdown(
"""
# National Critical Information Infrastructure Protection Centre

## Supervisory Analytics Tool for SOC Assessment (SAT-SA)

### SOC Capability and Control Maturity Assessment

**Assessment Cycle:** September 2026

"""
)



st.divider()



# =====================================================
# SUMMARY CALCULATION
# =====================================================


total_entities = len(profiles)


high_entities = [

    x for x in profiles

    if x["overall_risk"]["level"] == "HIGH"

]


medium_entities = [

    x for x in profiles

    if x["overall_risk"]["level"] == "MEDIUM"

]


low_entities = [

    x for x in profiles

    if x["overall_risk"]["level"] == "LOW"

]


immediate_entities = [

    x for x in profiles

    if x["review_priority"]

    ==

    "IMMEDIATE REVIEW"

]


targeted_entities = [

    x for x in profiles

    if x["review_priority"]

    ==

    "TARGETED REVIEW"

]



# =====================================================
# ASSESSMENT SUMMARY
# =====================================================


st.subheader(
"Assessment Summary"
)



summary = pd.DataFrame(

{

"Assessment Indicator":

[

"Total Entities Assessed",

"Entities Requiring Immediate Review",

"Entities Requiring Targeted Review",

"Total High Risk Entities",

"Total Medium Risk Entities",

"Total Low Risk Entities"

],


"Count":

[

total_entities,

len(immediate_entities),

len(targeted_entities),

len(high_entities),

len(medium_entities),

len(low_entities)

]

}

)



st.table(summary)



# =====================================================
# OVERALL POSTURE
# =====================================================


st.subheader(
"Overall Security Posture"
)



if len(high_entities) > 0:

    posture = "HIGH RISK"

elif len(medium_entities) > 0:

    posture = "MEDIUM RISK"

else:

    posture = "LOW RISK"



if posture == "HIGH RISK":

    st.error(posture)


elif posture == "MEDIUM RISK":

    st.warning(posture)


else:

    st.success(posture)



st.write(

"""
The assessment indicates varying levels of SOC capability maturity
across evaluated entities. Selected entities require supervisory
attention based on identified control execution gaps, investigation
quality concerns, and monitoring coverage observations.
"""

)



st.divider()



# =====================================================
# RISK CLASSIFICATION
# =====================================================


st.subheader(

"Entity Risk Classification"

)



risk_table = pd.DataFrame(

{

"Risk Category":

[

"HIGH",

"MEDIUM",

"LOW"

],


"Number of Entities":

[

len(high_entities),

len(medium_entities),

len(low_entities)

]

}

)



st.table(risk_table)



# =====================================================
# PRIORITY QUEUE
# =====================================================


st.subheader(

"Priority Review Queue"

)



priority_data = []



for entity in sorted(

    profiles,

    key=lambda x:

    x["overall_risk"]["score"],

    reverse=True

):


    if entity["review_priority"] != "ROUTINE REVIEW":


        priority_data.append(

        {

        "Entity":

        entity["cse_id"],


        "Risk Level":

        entity["overall_risk"]["level"],


        "Risk Score":

        entity["overall_risk"]["score"],


        "Review Priority":

        entity["review_priority"]

        }

        )



if len(priority_data) > 0:


    st.dataframe(

        pd.DataFrame(priority_data),

        hide_index=True,

        use_container_width=True

    )

else:

    st.info(

        "No entities require supervisory attention."

    )



st.divider()



# =====================================================
# CONTROL OBSERVATIONS
# =====================================================


st.subheader(

"Key Control Observations"

)



st.markdown(

"""
**Detection Capability**

Multiple entities require assessment of detection
coverage and alert handling effectiveness.


<br>

**Investigation Capability**

Investigation documentation, root cause analysis,
and remediation tracking require supervisory review.


<br>

**Monitoring Coverage**

Visibility gaps have been identified across
selected critical assets requiring coverage validation.

""",

unsafe_allow_html=True

)



st.divider()



# =====================================================
# SUMMARY NOTE
# =====================================================


st.subheader(

"Supervisory Assessment Summary"

)



st.info(

"""
The SAT-SA assessment provides an entity-level view of
SOC operational maturity, control effectiveness, and
potential supervisory focus areas.

Entities identified under higher risk categories should
undergo detailed validation of security monitoring,
investigation practices, and response processes.
"""

)