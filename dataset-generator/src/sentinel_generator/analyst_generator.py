import random


ROLES = [
    "L1_ANALYST",
    "L2_ANALYST",
    "L3_ANALYST"
]


SKILLS = [
    "LOW",
    "MEDIUM",
    "HIGH",
    "EXPERT"
]


WORKLOADS = [
    "LOW",
    "NORMAL",
    "HIGH",
    "OVERLOADED"
]


AVAILABILITY = [
    "ACTIVE",
    "ACTIVE",
    "ACTIVE",
    "OFFLINE"
]


def generate_analysts(count=20):

    analysts = []

    for i in range(count):

        role = random.choice(ROLES)

        if role == "L1_ANALYST":
            experience = random.randint(0,2)

        elif role == "L2_ANALYST":
            experience = random.randint(2,5)

        else:
            experience = random.randint(5,10)


        analyst = {

            "analyst_id":
                f"ANL_{str(i+1).zfill(3)}",

            "analyst_name":
                f"Analyst_{i+1}",

            "role":
                role,

            "experience_years":
                experience,

            "skill_level":
                random.choice(SKILLS),

            "workload":
                random.choice(WORKLOADS),

            "availability":
                random.choice(AVAILABILITY)

        }


        analysts.append(analyst)


    return analysts