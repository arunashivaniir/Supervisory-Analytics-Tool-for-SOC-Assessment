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
    page_title="Monitoring Coverage Assessment",
    layout="wide"
)


inject_css()


# =====================================================
# LOAD DATA
# =====================================================

@st.cache_data
def load_monitoring_data():

    from utils.data_loader import load_monitoring_coverage as _loader

    return _loader().fillna("")


@st.cache_data
def load_negative_space():

    from utils.data_loader import load_negative_space as _loader

    return _loader().fillna("")


coverage = load_monitoring_data()

negative_space = load_negative_space()

intelligence = intelligence_util.build_intelligence()


def is_gap(row):

    telemetry = str(
        row.get(
            "telemetry_available",
            ""
        )
    ).upper()

    actual = str(
        row.get(
            "actual_monitoring",
            ""
        )
    ).strip()

    return telemetry == "NO" or actual == ""


gaps = coverage[
    coverage.apply(
        is_gap,
        axis=1,
    )
]


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


section_label("Coverage Assessment Summary")


total_assets = len(coverage)

total_gaps = len(gaps)

affected_cses = gaps["cse_id"].nunique() if total_gaps else 0


col1, col2, col3, col4 = st.columns(4)



col1.metric(
    "Assets Assessed",
    total_assets
)


col2.metric(
    "Coverage Gaps",
    total_gaps
)


col3.metric(
    "Affected Assets",
    total_assets - total_gaps
)


col4.metric(
    "Entities Affected",
    affected_cses
)



st.divider()



# =====================================================
# COVERAGE REGISTER
# =====================================================

section_label("Monitoring Coverage Register")


coverage_display = coverage.copy()

if "criticality" in coverage.columns:

    coverage_display["criticality"] = coverage_display[
        "criticality"
    ].astype(str)

coverage_columns = [
    col
    for col in (
        "asset_id",
        "cse_id",
        "criticality",
        "expected_monitoring",
        "actual_monitoring",
        "telemetry_available",
    )
    if col in coverage.columns
]


st.dataframe(

    coverage_display[coverage_columns],

    hide_index=True,

    use_container_width=True,

    column_config={
        "asset_id": "Asset",
        "cse_id": "Entity",
        "criticality": "Criticality",
        "expected_monitoring": "Expected Coverage",
        "actual_monitoring": "Actual Coverage",
        "telemetry_available": "Telemetry",
    }

)


st.markdown(
    f"### Coverage Gap Register ({total_gaps} assets)"
)

st.warning(
    "Assets listed below lack required telemetry or actual monitoring "
    "coverage against their expected detection use cases."
)


if total_gaps:

    gap_display = gaps[coverage_columns]

    if "cse_id" in gap_display.columns:

        gap_display["entity_pattern"] = gap_display[
            "cse_id"
        ].map(
            lambda cse: intelligence.get(
                cse,
                {},
            ).get(
                "primary_pattern",
                "None",
            )
        )

        gap_columns = coverage_columns + [
            "entity_pattern"
        ]

    else:

        gap_columns = coverage_columns

    gap_display = gap_display[gap_columns]

    if "entity_pattern" in gap_display.columns:

        gap_display["entity_pattern"] = gap_display[
            "entity_pattern"
        ].map(
            lambda value: pattern_pill(value)
        )

    st.markdown(
        gap_display.to_html(
            escape=False,
            index=False,
        ),
        unsafe_allow_html=True,
    )

    st.info(
        "Coverage gaps correlate with the "
        "**VISIBILITY_AND_RESPONSE_GAP** supervisory pattern where "
        "detection use cases are mapped but telemetry is unavailable."
    )

else:

    st.success(
        "No monitoring coverage gaps identified."
    )



st.divider()



# =====================================================
# NEGATIVE SPACE REGISTER
# =====================================================

section_label("Negative Space Observations")


if not negative_space.empty:

    st.write(
        "Assets presenting negative-space observations (expected "
        "activity with no corresponding detection record)."
    )

    ns_columns = []

    for col in (
        "cse_id",
        "asset_id",
        "finding",
        "severity",
        "evidence",
    ):

        if col in negative_space.columns:

            ns_columns.append(col)

    st.dataframe(

        negative_space[ns_columns],

        hide_index=True,

        use_container_width=True,

    )

else:

    st.write(
        "No negative-space observations recorded."
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


    st.dataframe(

        asset_data.to_dict(
            orient="records"
        ),

        hide_index=True,

        use_container_width=True,

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


footnote(
    "Coverage analysis is combined with correlated pattern intelligence "
    "to prioritise telemetry remediation across entities."
)