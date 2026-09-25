import os
import sys

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
    page_title="SAT-SA Assessment Overview",
    layout="wide"
)


inject_css()


# =====================================================
# LOAD DATA
# =====================================================

@st.cache_data
def load_profiles():

    from utils.data_loader import load_profiles as _loader

    return _loader()


profiles = load_profiles()

intelligence = intelligence_util.build_intelligence()

intelligence_df = intelligence_util.intelligence_dataframe()

snapshot = intelligence_util.snapshot()



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


section_label("Assessment Summary")


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
# SAT-SA INTELLIGENCE SIGNAL
# =====================================================

section_label("SAT-SA Intelligence Signal")


col1, col2, col3, col4 = st.columns(4)


col1.metric(
    "Anomalous Entities",
    f"{snapshot['anomalous']} of {snapshot['entities']}"
)

col2.metric(
    "Supervisory Findings",
    snapshot["total_findings"]
)

col3.metric(
    "Monitoring Coverage Gaps",
    snapshot["total_gaps"]
)

col4.metric(
    "ML / Hybrid Recommendations",
    snapshot["ml_hybrid"]
)


st.subheader(
    "Entity Intelligence Register"
)


register_display = intelligence_df.copy()

register_display["Risk Level"] = register_display[
    "Risk Level"
].map(
    lambda value: risk_pill(value)
)

register_display["Anomaly Status"] = register_display[
    "Anomaly Status"
].map(
    lambda value: anomaly_pill(value)
)

register_display["Recommendation"] = register_display[
    "Recommendation"
].map(
    lambda value: source_pill(value)
)

register_display["Primary Pattern"] = register_display[
    "Primary Pattern"
].map(
    lambda value: pattern_pill(value)
)


st.markdown(
    register_display.to_html(
        escape=False,
        index=False,
    ),
    unsafe_allow_html=True,
)


st.caption(
    "Table ordered by anomaly score, then risk score. "
    "Attention score reflects severity-weighted alert and "
    "investigation quality signals on a 0-100 scale."
)


st.divider()


# =====================================================
# ANOMALY WATCHLIST
# =====================================================

section_label("Anomaly Watchlist")


anomalous_entities = [

    e for e in intelligence.values()

    if e["anomaly_status"] == "ANOMALOUS"

]


if anomalous_entities:

    watchlist = pd.DataFrame(
        [
            {
                "Entity": e["cse_id"],
                "Sector": e["sector"],
                "Risk Level": risk_pill(e["risk_level"]),
                "Attention Score": e["attention_score"],
                "Anomaly Score": e["anomaly_score"],
                "Anomaly Status": anomaly_pill(e["anomaly_status"]),
                "Anomalous Alerts": f"{e['anomalous_alerts']} / {e['total_alerts']}",
                "Primary Pattern": pattern_pill(
                    e["primary_pattern"]
                ),
            }
            for e in sorted(
                anomalous_entities,
                key=lambda item: (
                    -item["anomaly_score"],
                    -item["risk_score"],
                ),
            )
        ]
    )

    st.markdown(
        watchlist.to_html(
            escape=False,
            index=False,
        ),
        unsafe_allow_html=True,
    )

    st.info(
        "Entities on the anomaly watchlist exhibited alert behaviour "
        "deviating from the assessed population and warrant prioritised "
        "supervisory review."
    )

else:

    st.success(
        "No entity currently exceeds the anomaly threshold."
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

        risk_pill(entity["overall_risk"]["level"]),


        "Risk Score":

        entity["overall_risk"]["score"],


        "Review Priority":

        entity["review_priority"]

        }

        )



if len(priority_data) > 0:

    priority_frame = pd.DataFrame(
        priority_data
    )

    priority_frame["Risk Level"] = priority_frame[
        "Risk Level"
    ].map(
        lambda value: risk_pill(value)
    )

    st.markdown(
        priority_frame.to_html(
            escape=False,
            index=False,
        ),
        unsafe_allow_html=True,
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
SOC operational maturity, control effectiveness, anomaly
signals, and potential supervisory focus areas.

Entities identified under higher risk categories should
undergo detailed validation of security monitoring,
investigation practices, and response processes.
"""

)


footnote(
    "SAT-SA intelligence integrates supervised risk scoring with "
    "anomaly detection and correlated pattern signals; it assists, "
    "and does not replace, human examiners."
)