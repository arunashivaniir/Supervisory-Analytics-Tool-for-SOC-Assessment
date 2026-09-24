import streamlit as st


st.set_page_config(
    page_title="SAT-SA Supervisory Portal",
    page_icon="🏛️",
    layout="wide"
)


st.title(
    "SAT-SA"
)


st.subheader(
    "Supervisory Analytics Tool for SOC Assessment"
)


st.markdown(
"""
### National Critical Information Infrastructure Protection Centre

SOC capability and control maturity assessment platform.

---

### Portal Modules

Navigate using the sidebar:

**1. Overview**
- Supervisory risk posture
- Priority review queue
- Key observations


**2. Entity Assessment**
- CSE-level risk assessment
- Capability maturity
- Supervisory recommendations


**3. Findings Register**
- Validated findings
- Evidence details
- Confidence assessment


**4. Monitoring Coverage**
- Asset visibility
- Control coverage gaps


**5. Reports**
- Generate supervisory assessment reports

"""
)


st.info(
"Select a module from the left navigation panel."
)