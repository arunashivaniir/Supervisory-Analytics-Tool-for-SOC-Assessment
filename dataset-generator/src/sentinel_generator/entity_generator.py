import random


SECTORS = [
    "ENERGY",
    "BANKING",
    "TELECOM",
    "HEALTHCARE",
    "TRANSPORT",
    "GOVERNMENT"
]


SOC_PROFILES = [
    "MATURE",
    "NORMAL",
    "KPI_OPTIMIZED",
    "OVERLOADED",
    "VENDOR_DEPENDENT"
]


def generate_entities(count=10):

    entities = []

    for i in range(count):

        sector = random.choice(SECTORS)

        # Decide SOC behaviour first
        profile = random.choice(SOC_PROFILES)


        # Generate maturity based on behaviour
        if profile in [
            "KPI_OPTIMIZED",
            "VENDOR_DEPENDENT",
            "OVERLOADED"
        ]:

            # Looks good externally, but weak internally
            actual_maturity = round(
                random.uniform(2.0, 3.8),
                1
            )

            reported_maturity = round(
                random.uniform(
                    actual_maturity + 0.5,
                    5.0
                ),
                1
            )


        else:

            # Healthy SOC: reported and actual are close
            actual_maturity = round(
                random.uniform(3.5, 5.0),
                1
            )

            reported_maturity = round(
                random.uniform(
                    max(0, actual_maturity - 0.3),
                    min(5, actual_maturity + 0.3)
                ),
                1
            )


        entity = {

            "cse_id":
                f"CSE_{str(i+1).zfill(3)}",

            "organisation_name":
                f"{sector}_ORG_{i+1}",

            "sector":
                sector,

            "criticality":
                random.choice(
                    [
                        "NATIONAL",
                        "HIGH",
                        "MEDIUM"
                    ]
                ),

            "reported_maturity":
                reported_maturity,

            "actual_maturity":
                actual_maturity,

            "soc_profile":
                profile
        }


        entities.append(entity)


    return entities