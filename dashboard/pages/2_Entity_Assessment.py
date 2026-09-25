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
    page_title="Entity Assessment",
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


intel = intelligence.get(
    selected_cse,
    {}
)


st.divider()



# =====================================================
# RISK SUMMARY
# =====================================================


section_label("Entity Assessment Summary")


col1, col2, col3, col4, col5, col6 = st.columns(6)



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



col4.metric(

    "Attention Score",

    f"{intel.get('attention_score', 0)}/100"

)



col5.metric(

    "Anomaly Score",

    f"{intel.get('anomaly_score', 0):.2f}"

)



col6.metric(

    "Anomaly Status",

    intel.get(
        "anomaly_status",
        "NORMAL"
    )

)



st.divider()



# =====================================================
# SAT-SA INTELLIGENCE ASSESSMENT
# =====================================================

section_label("SAT-SA Intelligence Assessment")


intelligence_rows = []


def _value_cell(value):

    uppercase = str(value).upper()

    if uppercase in (
        "CRITICAL",
        "HIGH",
        "MEDIUM",
        "LOW",
    ):

        return risk_pill(value)

    if uppercase in (
        "ANOMALOUS",
        "NORMAL",
    ):

        return anomaly_pill(value)

    if uppercase in (
        "ML / HYBRID",
        "RULE",
    ):

        return source_pill(value)

    return str(value)


intelligence_rows.append(
    {
        "Signal": "Entity Attention Score",
        "Value": _value_cell(
            f"{intel.get('attention_score', 0)} / 100"
        ),
        "Basis": "Severity-weighted alert behaviour and investigation quality indicators",
    }
)

intelligence_rows.append(
    {
        "Signal": "Anomaly Score",
        "Value": _value_cell(
            f"{intel.get('anomaly_score', 0):.2f}"
        ),
        "Basis": "Isolation-forest assessment of alert behaviour versus assessed population",
    }
)

intelligence_rows.append(
    {
        "Signal": "Anomaly Status",
        "Value": _value_cell(
            intel.get(
                "anomaly_status",
                "NORMAL"
            )
        ),
        "Basis": "Score >= 0.70 flagged as anomalous for supervisory review",
    }
)

intelligence_rows.append(
    {
        "Signal": "Anomalous Alerts",
        "Value": _value_cell(
            f"{intel.get('anomalous_alerts', 0)} of {intel.get('total_alerts', 0)}"
        ),
        "Basis": "Alerts flagged by the isolation-forest model within the entity",
    }
)

intelligence_rows.append(
    {
        "Signal": "Correlated Patterns",
        "Value": _value_cell(
            f"{intel.get('pattern_count', 0)}"
        ),
        "Basis": "Distinct correlated behaviour patterns observed",
    }
)

intelligence_rows.append(
    {
        "Signal": "Recommendation Source",
        "Value": _value_cell(
            intel.get(
                "recommendation_source",
                "Rule"
            )
        ),
        "Basis": "ML/Hybrid where algorithm-assisted findings support the recommendation",
    }
)


intel_view = pd.DataFrame(
    intelligence_rows
)


st.markdown(
    intel_view.to_html(
        escape=False,
        index=False,
    ),
    unsafe_allow_html=True,
)


st.divider()



# =====================================================
# CORRELATED PATTERNS
# =====================================================

section_label("Correlated Behaviour Patterns")


patterns = intel.get(
    "correlated_patterns",
    []
)


if patterns:

    pattern_rows = pd.DataFrame(
        [
            {
                "Correlated Pattern": pattern_pill(pattern),
                "Supporting Signals": count,
            }
            for pattern, count in patterns
        ]
    )

    st.markdown(
        pattern_rows.to_html(
            escape=False,
            index=False,
        ),
        unsafe_allow_html=True,
    )

    if intel.get(
        "multi_control",
        False
    ):

        st.warning(
            "Multiple control weaknesses correlate within this entity. "
            "Patterned supervisory review is recommended alongside "
            "individual finding remediation."
        )

else:

    st.info(
        "No correlated behaviour patterns identified."
    )


st.divider()



# =====================================================
# SUPERVISORY RECOMMENDATIONS
# =====================================================

section_label("Supervisory Recommendations")


recommendations = intel.get(
    "recommendations",
    []
)


if recommendations:

    st.markdown(
        f"**Recommendation Source:** "
        f"{source_pill(intel.get('recommendation_source', 'Rule'))}",
        unsafe_allow_html=True,
    )

    for action in recommendations:

        st.markdown(
            f"•  {action}"
        )

    reasons = intel.get(
        "recommendation_reason",
        []
    )

    if reasons:

        st.subheader(
            "Recommendation Basis"
        )

        for reason in reasons:

            st.write(
                "• " + reason
            )

else:

    st.info(
        "No recommendation options captured for this entity."
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


footnote(
    "Attention and anomaly signals complement risk scoring and are "
    "intended to support, not replace, the examiner's judgement."
)