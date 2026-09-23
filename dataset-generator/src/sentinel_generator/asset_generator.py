import random


ASSET_TYPES = [
    "SERVER",
    "DATABASE",
    "FIREWALL",
    "ENDPOINT",
    "SCADA_SYSTEM",
    "PLC_CONTROLLER",
    "APPLICATION",
    "CLOUD_SERVICE"
]


BUSINESS_FUNCTIONS = {

    "ENERGY": [
        "Power Generation",
        "Grid Distribution",
        "SCADA Monitoring"
    ],

    "BANKING": [
        "Transaction Processing",
        "Core Banking",
        "Payment Gateway"
    ],

    "TELECOM": [
        "Network Management",
        "Customer Services",
        "Communication Infrastructure"
    ],

    "HEALTHCARE": [
        "Patient Records",
        "Medical Systems",
        "Hospital Operations"
    ],

    "TRANSPORT": [
        "Traffic Management",
        "Fleet Operations",
        "Ticketing System"
    ],

    "GOVERNMENT": [
        "Citizen Services",
        "Data Management",
        "Government Applications"
    ]
}


def generate_assets(entities, min_assets=5, max_assets=15):

    assets = []

    asset_count = 1


    for entity in entities:

        cse_id = entity["cse_id"]
        sector = entity["sector"]


        number_of_assets = random.randint(
            min_assets,
            max_assets
        )


        for _ in range(number_of_assets):

            criticality = random.choices(

                [
                    "TIER-0",
                    "TIER-1",
                    "TIER-2",
                    "TIER-3"
                ],

                weights=[
                    10,
                    30,
                    40,
                    20
                ]

            )[0]


            asset = {

                "asset_id":
                    f"ASSET_{str(asset_count).zfill(4)}",

                "cse_id":
                    cse_id,

                "asset_name":
                    f"{sector}_ASSET_{asset_count}",

                "asset_type":
                    random.choice(ASSET_TYPES),

                "criticality":
                    criticality,

                "business_function":
                    random.choice(
                        BUSINESS_FUNCTIONS[sector]
                    ),

                "internet_exposed":
                    random.choice(
                        [
                            True,
                            False
                        ]
                    )
            }


            assets.append(asset)

            asset_count += 1


    return assets