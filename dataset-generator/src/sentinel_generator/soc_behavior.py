import random


def get_soc_behavior(profile):

    if profile == "MATURE":

        return {

            "fast_closure_probability": 0.05,

            "evidence_probability": 0.90,

            "escalation_probability": 0.90,

            "remediation_probability": 0.90

        }


    elif profile == "KPI_OPTIMIZED":

        return {

            "fast_closure_probability": 0.80,

            "evidence_probability": 0.20,

            "escalation_probability": 0.30,

            "remediation_probability": 0.20

        }


    elif profile == "OVERLOADED":

        return {

            "fast_closure_probability": 0.10,

            "evidence_probability": 0.50,

            "escalation_probability": 0.50,

            "remediation_probability": 0.40

        }


    elif profile == "VENDOR_DEPENDENT":

        return {

            "fast_closure_probability": 0.30,

            "evidence_probability": 0.40,

            "escalation_probability": 0.70,

            "remediation_probability": 0.30

        }


    else:

        return {

            "fast_closure_probability":0.20,

            "evidence_probability":0.60,

            "escalation_probability":0.60,

            "remediation_probability":0.60

        }