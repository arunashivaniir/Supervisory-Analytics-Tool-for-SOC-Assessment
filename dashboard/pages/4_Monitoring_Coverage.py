import streamlit as st
import pandas as pd
import os


st.set_page_config(
    page_title="Monitoring Coverage Assessment",
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
def load_monitoring_data():

    file_path = os.path.join(
        DATA_PATH,
        "negative_space_findings.csv"
    )

    return pd.read_csv(file_path).fillna("")



coverage = load_monitoring_data()



# =====================================================
# HEADER
# =====================================================

st.title(
    "Monitoring Coverage Assessment"
)


st.markdown(
"""
Assessment of security monitoring visibility across
critical assets and identified control coverage gaps.
"""
)


st.divider()



# =====================================================
# SUMMARY
# =====================================================


st.subheader(
"Coverage Assessment Summary"
)



total_gaps = len(coverage)


if "asset_id" in coverage.columns:

    affected_assets = coverage["asset_id"].nunique()

else:

    affected_assets = 0



col1,col2,col3 = st.columns(3)



col1.metric(
    "Monitoring Coverage Gaps",
    total_gaps
)


col2.metric(
    "Affected Assets",
    affected_assets
)


col3.metric(
    "Assessment Status",
    "REVIEW REQUIRED"
)



st.divider()



# =====================================================
# OBSERVATION SUMMARY
# =====================================================


st.subheader(
"Supervisory Observation"
)



st.info(
"""
Monitoring coverage assessment identified assets where
expected security visibility controls require validation.

Entities should review whether appropriate telemetry,
detection controls, and monitoring capabilities are
available for critical assets.
"""
)



st.divider()



# =====================================================
# COVERAGE REGISTER
# =====================================================


st.subheader(
"Monitoring Coverage Register"
)



display_columns = []


possible_columns = [

"cse_id",

"asset_id",

"finding",

"severity",

"evidence"

]



for col in possible_columns:

    if col in coverage.columns:

        display_columns.append(col)



if display_columns:


    st.dataframe(

        coverage[display_columns],

        hide_index=True,

        use_container_width=True

    )


else:

    st.dataframe(

        coverage,

        hide_index=True,

        use_container_width=True

    )



st.divider()



# =====================================================
# ASSET LEVEL REVIEW
# =====================================================


st.subheader(
"Asset Coverage Review"
)



if "asset_id" in coverage.columns:


    selected_asset = st.selectbox(

        "Select Asset",

        coverage["asset_id"].unique()

    )


    asset_data = coverage[

        coverage["asset_id"]

        ==

        selected_asset

    ]



    st.write(

        asset_data.to_dict(

            orient="records"

        )

    )


else:


    st.write(

        "Asset mapping information unavailable."

    )



st.divider()



# =====================================================
# RECOMMENDATION
# =====================================================


st.subheader(
"Recommended Supervisory Action"
)



st.markdown(
"""
• Validate monitoring coverage for identified assets

• Confirm availability of required telemetry sources

• Review detection controls mapped to critical assets

• Ensure visibility gaps are tracked through remediation process
"""
)