import streamlit as st
import json
import os
import pandas as pd


st.set_page_config(
    page_title="Supervisory Findings Register",
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
def load_validation():

    with open(
        os.path.join(
            DATA_PATH,
            "finding_validation.json"
        )
    ) as f:

        return json.load(f)



validation = load_validation()



findings_df = pd.DataFrame(validation)



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


st.subheader(
"Findings Summary"
)


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



col1,col2,col3 = st.columns(3)



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

"confidence_score",

"validation_status"

]



st.dataframe(

findings_df[display_columns],

use_container_width=True,

hide_index=True

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