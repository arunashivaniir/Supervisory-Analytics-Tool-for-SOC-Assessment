import streamlit as st
import pandas as pd
import json
import plotly.express as px



# ==================================================
# CONFIGURATION
# ==================================================

st.set_page_config(

    page_title="SAT-SA Dashboard",

    page_icon="🛡️",

    layout="wide"

)



import os


BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


DATA_PATH = os.path.join(

    BASE_DIR,

    "..",

    "data",

    "generated"

) + "/"



# ==================================================
# LOAD DATA
# ==================================================

@st.cache_data
def load_data():


    with open(

        DATA_PATH + "cse_risk_profiles.json"

    ) as f:

        risk_profiles = json.load(f)



    with open(

        DATA_PATH + "finding_validation.json"

    ) as f:

        validation = json.load(f)



    with open(

        DATA_PATH + "peer_benchmarking_results.json"

    ) as f:

        peer = json.load(f)



    findings = pd.read_csv(

        DATA_PATH + "supervisory_findings.csv"

    )



    negative_space = pd.read_csv(

        DATA_PATH + "negative_space_findings.csv"

    )



    return (

        risk_profiles,

        validation,

        peer,

        findings,

        negative_space

    )





profiles, validation, peer, findings, negative_space = load_data()





# ==================================================
# TITLE
# ==================================================

st.title(

    "🛡️ SAT-SA Supervisory Analytics Dashboard"

)


st.caption(

    "Supervisory Analytics Tool for SOC Assessment"

)



# ==================================================
# EXECUTIVE METRICS
# ==================================================

total_cse = len(profiles)


high_risk = len(

    [

        x for x in profiles

        if x["overall_risk"]["level"]

        ==

        "HIGH"

    ]

)



medium_risk = len(

    [

        x for x in profiles

        if x["overall_risk"]["level"]

        ==

        "MEDIUM"

    ]

)



low_risk = len(

    [

        x for x in profiles

        if x["overall_risk"]["level"]

        ==

        "LOW"

    ]

)



total_findings = len(validation)



ml_supported = len(

    [

        x for x in validation

        if x["ml_supported"]

    ]

)



col1,col2,col3,col4,col5 = st.columns(5)



col1.metric(

    "Total CSEs",

    total_cse

)



col2.metric(

    "HIGH Risk Entities",

    high_risk

)



col3.metric(

    "MEDIUM Risk Entities",

    medium_risk

)



col4.metric(

    "Total Findings",

    total_findings

)



col5.metric(

    "ML Supported Findings",

    ml_supported

)



st.divider()



# ==================================================
# RISK DISTRIBUTION
# ==================================================


risk_df = pd.DataFrame(

    [

        {

            "CSE":x["cse_id"],

            "Risk":x["overall_risk"]["level"],

            "Score":x["overall_risk"]["score"]

        }

        for x in profiles

    ]

)



fig = px.pie(

    risk_df,

    names="Risk",

    title="CSE Risk Distribution"

)


st.plotly_chart(

    fig,

    use_container_width=True

)



# ==================================================
# TOP RISK ENTITIES
# ==================================================


st.subheader(

    "Top Risk Entities"

)



top_risk = risk_df.sort_values(

    "Score",

    ascending=False

).head(10)



st.dataframe(

    top_risk,

    use_container_width=True

)



# ==================================================
# ENTITY DRILL DOWN
# ==================================================


st.divider()


st.header(

    "Entity Assessment"

)



selected_cse = st.selectbox(

    "Select CSE",

    [

        x["cse_id"]

        for x in profiles

    ]

)



entity = next(

    x for x in profiles

    if x["cse_id"]

    ==

    selected_cse

)



st.subheader(

    selected_cse

)



c1,c2,c3 = st.columns(3)


c1.metric(

    "Risk Score",

    entity["overall_risk"]["score"]

)


c2.metric(

    "Risk Level",

    entity["overall_risk"]["level"]

)


c3.metric(

    "Review Priority",

    entity["review_priority"]

)



# Capability table


capability = pd.DataFrame(

    {

        "Capability":

        [

            "Detection",

            "Investigation",

            "Monitoring"

        ],

        "Risk":

        [

            entity["capability_assessment"]["detection"]["risk"],

            entity["capability_assessment"]["investigation"]["risk"],

            entity["capability_assessment"]["monitoring"]["risk"]

        ]

    }

)



st.table(

    capability

)



st.subheader(

    "Risk Drivers"

)


for driver in entity["risk_drivers"]:

    st.warning(driver)



# ==================================================
# FINDING INTELLIGENCE
# ==================================================


st.divider()


st.header(

    "Finding Intelligence"

)



finding_count = findings["finding"].value_counts()



fig = px.bar(

    finding_count,

    title="Finding Categories"

)



st.plotly_chart(

    fig,

    use_container_width=True

)



# Validation metrics


v1,v2,v3 = st.columns(3)



supported = len(

    [

        x for x in validation

        if x["validation_status"]

        ==

        "EVIDENCE_SUPPORTED"

    ]

)



review = len(

    [

        x for x in validation

        if x["validation_status"]

        ==

        "REQUIRES_REVIEW"

    ]

)



avg_conf = round(

    sum(

        x["confidence_score"]

        for x in validation

    )

    /

    len(validation),

    2

)



v1.metric(

    "Evidence Supported",

    supported

)


v2.metric(

    "Requires Review",

    review

)


v3.metric(

    "Average Confidence",

    f"{avg_conf}%"

)



# ==================================================
# ML EXPLAINABILITY
# ==================================================


st.divider()


st.header(

    "ML Explainability"

)



ml_df = pd.DataFrame(validation)



st.dataframe(

    ml_df[

        [

            "alert_id",

            "finding",

            "confidence_score",

            "ml_supported",

            "validation_status"

        ]

    ],

    use_container_width=True

)



# ==================================================
# NEGATIVE SPACE
# ==================================================


st.divider()


st.header(

    "Monitoring Coverage / Negative Space"

)



n1,n2 = st.columns(2)



n1.metric(

    "Coverage Gaps",

    len(negative_space)

)



n2.metric(

    "Affected Assets",

    negative_space["asset_id"].nunique()

)



st.dataframe(

    negative_space,

    use_container_width=True

)



st.success(

    "SAT-SA Dashboard Loaded Successfully"

)