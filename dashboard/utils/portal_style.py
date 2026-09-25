import html

import streamlit as st


# =====================================================================
# SAT-SA Portal Styling
#
# Formal NCIIPC / critical-infrastructure supervisory assessment
# styling. Light enterprise theme with a government-blue accent palette.
# No neon, no SOC-style chrome, no gaming visuals.
# =====================================================================


PORTAL_CSS = """
<style>
/* Formal portal palette */

.satsa-portal {
  font-family: "Segoe UI", "Helvetica Neue", Arial, sans-serif;
  color: #1b2a41;
}

.satsa-banner {
  background: linear-gradient(90deg, #ffffff 0%, #f4f7fb 100%);
  border-left: 6px solid #1d4e89;
  padding: 14px 18px;
  margin-bottom: 10px;
  border-radius: 4px;
}

.satsa-banner .satsa-org {
  font-size: 12px;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: #5a7189;
  font-weight: 600;
}

.satsa-banner .satsa-title {
  font-size: 26px;
  font-weight: 600;
  color: #16283f;
  margin: 2px 0;
}

.satsa-banner .satsa-subtitle {
  font-size: 14px;
  color: #40586f;
}

.satsa-banner .satsa-cycle {
  font-size: 12px;
  color: #1d4e89;
  font-weight: 600;
  margin-top: 4px;
}

/* Status pills */

.pill {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.4px;
  border: 1px solid transparent;
  white-space: nowrap;
}

.pill-critical { background: #fdecee; color: #b02a37; border-color: #e9b3bb; }
.pill-high     { background: #fdf1e6; color: #b0541e; border-color: #eec9a8; }
.pill-medium   { background: #fbf5e8; color: #8a6d1a; border-color: #e6d29a; }
.pill-low      { background: #eaf4ee; color: #1c6b3f; border-color: #bad9c5; }
.pill-anomalous{ background: #fdecee; color: #b02a37; border-color: #e9b3bb; }
.pill-normal   { background: #eaf4ee; color: #1c6b3f; border-color: #bad9c5; }
.pill-ml       { background: #e8f0fb; color: #1d4e89; border-color: #b9cde6; }
.pill-rule     { background: #f1f3f5; color: #40586f; border-color: #ccd5de; }
.pill-pattern  { background: #eef3f9; color: #36587d; border-color: #c9d7e6; }

/* Section rules */

.satsa-section {
  border-bottom: 2px solid #dbe4ee;
  padding-bottom: 6px;
  margin-bottom: 12px;
}

.satsa-section span {
  font-size: 13px;
  letter-spacing: 1px;
  text-transform: uppercase;
  color: #40586f;
  font-weight: 600;
}

/* Data confidence footer */

.satsa-footnote {
  font-size: 12px;
  color: #6b7f94;
  font-style: italic;
}
</style>
"""



def inject_css():

    st.markdown(
        PORTAL_CSS,
        unsafe_allow_html=True,
    )



def banner():

    inject_css()

    st.markdown(
        """
        <div class="satsa-banner">
          <div class="satsa-org">National Critical Information Infrastructure Protection Centre (NCIIPC)</div>
          <div class="satsa-title">Supervisory Analytics Tool for SOC Assessment</div>
          <div class="satsa-subtitle">SAT-SA &mdash; SOC Capability and Control Maturity Assessment Platform</div>
          <div class="satsa-cycle">Assessment Cycle: September 2026</div>
        </div>
        """,
        unsafe_allow_html=True,
    )



def pill(
        label,
        kind="normal"
):

    return (
        f'<span class="pill pill-{html.escape(str(kind))}">'
        f"{html.escape(str(label))}"
        f"</span>"
    )



def risk_pill(level):

    return pill(
        level,
        str(
            level
        ).lower(),
    )



def anomaly_pill(status):

    return pill(
        status,
        "anomalous"
        if str(
            status
        ).upper()
        == "ANOMALOUS"
        else "normal",
    )



def source_pill(source):

    return pill(
        source,
        "ml"
        if "ML" in str(
            source
        )
        else "rule",
    )



def pattern_pill(pattern):

    return pill(
        pattern,
        "pattern",
    )



def section_label(text):

    st.markdown(
        f'<div class="satsa-section"><span>{html.escape(str(text))}</span></div>',
        unsafe_allow_html=True,
    )



def footnote(text):

    st.markdown(
        f'<div class="satsa-footnote">{html.escape(str(text))}</div>',
        unsafe_allow_html=True,
    )