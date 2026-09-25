import os
import sys

import streamlit as st

sys.path.insert(
    0,
    os.path.dirname(
        os.path.abspath(__file__)
    ),
)

from utils import intelligence as intelligence_util
from utils.portal_style import banner, inject_css, section_label, footnote


st.set_page_config(
    page_title="SAT-SA Supervisory Portal",
    page_icon="🏛️",
    layout="wide"
)


banner()


st.markdown(
"""
### National Critical Information Infrastructure Protection Centre

Supervisory Analytics Tool for SOC Assessment &mdash; select a module from
the left sidebar to review risk posture, entity assessments, findings,
monitoring coverage and supervisory reports.
"""
)


st.divider()


# =====================================================
# SAT-SA INTELLIGENCE SNAPSHOT
# =====================================================

snapshot = intelligence_util.snapshot()


section_label("SAT-SA Intelligence Snapshot")


col1, col2, col3, col4, col5, col6 = st.columns(6)


col1.metric(
    "Entities Assessed",
    snapshot["entities"]
)

col2.metric(
    "Anomalous Entities",
    snapshot["anomalous"]
)

col3.metric(
    "High-Risk Entities",
    snapshot["high_risk"]
)

col4.metric(
    "Supervisory Findings",
    snapshot["total_findings"]
)

col5.metric(
    "Monitoring Gaps",
    snapshot["total_gaps"]
)

col6.metric(
    "ML / Hybrid Recommendations",
    snapshot["ml_hybrid"]
)


st.caption(
    "Anomaly signal derives from isolation-forest assessment of "
    "entity alert behaviour; it complements, and does not replace, "
    "supervisory risk scoring."
)


st.subheader(
    "Entity Intelligence Register"
)


st.dataframe(
    intelligence_util.intelligence_dataframe(),
    use_container_width=True,
    hide_index=True,
)


st.divider()


# =====================================================
# PORTAL MODULES
# =====================================================

section_label("Portal Modules")


st.markdown(
"""
Navigate using the left sidebar.

**1. Assessment Overview**
- Supervisory risk posture and priority review queue
- Entity intelligence register with attention, anomaly and pattern signals

**2. Entity Assessment**
- CSE-level risk assessment and capability maturity
- Entity attention score, anomaly status and ML/Rule recommendations

**3. Findings Register**
- Validated findings with evidence, confidence and correlated patterns

**4. Monitoring Coverage**
- Asset visibility and control coverage gaps

**5. Reports**
- Generate and access supervisory assessment reports
"""
)


st.info(
    "Select a module from the left navigation panel."
)


footnote(
    "SAT-SA assessment outputs support supervisory judgement and "
    "do not replace human review or statutory examination."
)