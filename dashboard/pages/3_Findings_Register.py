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
    pattern_pill,
    section_label,
    footnote,
)


st.set_page_config(
    page_title="Supervisory Findings Register",
    layout="wide"
)


inject_css()


# =====================================================
# LOAD DATA
# =====================================================

@st.cache_data
def load_validation():

    from utils.data_loader import load_validation as _loader

    return _loader()


validation = load_validation()


findings_df = pd.DataFrame(validation)


# attach correlated pattern label (text based, shared mapping)
findings_df["correlated_pattern"] = findings_df[
    "finding"
].map(
    intelligence_util.correlate_finding_pattern
)


# =====================================================
# HEADER
# =====================================================


st.title(
    "Supervisory Findings Register"
)


st.markdown(
"""
Validated security observations identified during
SOC capability assessment.
"""
)


st.divider()



# =====================================================
# SUMMARY
# =====================================================


section_label("Findings Summary")


total = len(findings_df)


supported = len(
    findings_df[
        findings_df["validation_status"]
        ==
        "EVIDENCE_SUPPORTED"
    ]
)


review = len(
    findings_df[
        findings_df["validation_status"]
        ==
        "REQUIRES_REVIEW"
    ]
)


col1, col2, col3 = st.columns(3)



col1.metric(
    "Total Findings",
    total
)


col2.metric(
    "Evidence Supported",
    supported
)


col3.metric(
    "Requires Review",
    review
)



st.divider()



# =====================================================
# SEVERITY SUMMARY
# =====================================================


st.subheader(
"Severity Distribution"
)


severity_table = (

findings_df

["severity"]

.value_counts()

.reset_index()

)

severity_table.columns = [

"Severity",

"Count"

]


st.table(
    severity_table
)



st.divider()



# =====================================================
# CORRELATED PATTERN SUMMARY
# =====================================================

section_label("Findings by Correlated Pattern")


pattern_summary = findings_df[
    "correlated_pattern"
].value_counts()

pattern_table = pattern_summary.reset_index()

pattern_table.columns = [
    "Correlated Pattern",
    "Finding Count"
]

pattern_table["Correlated Pattern"] = pattern_table[
    "Correlated Pattern"
].map(
    lambda value: pattern_pill(value)
)


st.markdown(
    pattern_table.to_html(
        escape=False,
        index=False,
    ),
    unsafe_allow_html=True,
)


st.caption(
    "Pattern labels are derived from the correlated finding "
    "behaviour observed for each validated finding."
)


st.divider()



# =====================================================
# FINDINGS REGISTER
# =====================================================


st.subheader(
"Finding Register"
)


display_columns = [

"finding_id",

"alert_id",

"finding",

"severity",

"correlated_pattern",

"confidence_score",

"validation_status"

]



st.dataframe(

findings_df[display_columns],

use_container_width=True,

hide_index=True,

column_config={
    "finding_id": "Finding ID",
    "alert_id": "Alert Reference",
    "finding": "Finding",
    "severity": "Severity",
    "correlated_pattern": "Correlated Pattern",
    "confidence_score": "Confidence (%)",
    "validation_status": "Validation Status",
}

)



st.divider()



# =====================================================
# FINDING DETAIL
# =====================================================


st.subheader(
"Finding Assessment"
)



selected_id = st.selectbox(

"Select Finding",

findings_df["finding_id"]

)



finding = findings_df[

findings_df["finding_id"]

==

selected_id

].iloc[0]


st.markdown(

f"""
### {finding['finding']}


**Finding ID**

{finding['finding_id']}


**Alert Reference**

{finding['alert_id']}


**Severity**

{finding['severity']}


**Confidence Assessment**

{finding['confidence_score']}%


**Validation Status**

{finding['validation_status']}


**Correlated Pattern**

{finding['correlated_pattern']}

"""
)



st.subheader(
"Assessment Evidence"
)



st.info(

finding["evidence"]

)



st.divider()



# =====================================================
# EXPLAINABILITY
# =====================================================


st.subheader(
"Detection Support"
)



if finding["ml_supported"]:

    st.warning(

"""
This finding was supported by
algorithm-assisted anomaly detection.
Human validation remains required.
"""

    )

else:

    st.write(

"""
This finding was generated from
rule-based supervisory indicators.
"""

    )


footnote(
    "Correlated patterns group related findings across control areas "
    "to support supervisory pattern review."
)