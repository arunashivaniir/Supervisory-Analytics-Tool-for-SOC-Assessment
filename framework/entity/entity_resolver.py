class EntityResolver:


    ENTITY_FIELDS = [

        "entity_id",
        "entity",
        "organization",
        "organisation",
        "company",
        "cse_id",
        "tenant",
        "customer"

    ]


    ORG_FIELDS = [

        "department",
        "division",
        "business_unit",
        "region"

    ]



    ASSET_FIELDS = [

        "asset_identifier",
        "host",
        "hostname",
        "device"

    ]



    def resolve(self, record):


        normalized = {

            str(k).lower():

            v

            for k,v in record.items()

        }



        # 1. Explicit entity


        for field in self.ENTITY_FIELDS:


            if field in normalized:

                value = normalized[field]


                if value:

                    return {

                        "entity": str(value),

                        "confidence": 1.0,

                        "source": field

                    }



        # 2. Organizational context


        for field in self.ORG_FIELDS:


            if field in normalized:


                value = normalized[field]


                if value:

                    return {

                        "entity": str(value),

                        "confidence": 0.7,

                        "source": field

                    }



        # 3. Asset fallback


        for field in self.ASSET_FIELDS:


            if field in normalized:


                value = normalized[field]


                if value:

                    return {

                        "entity": "UNKNOWN_ENTITY",

                        "confidence": 0.3,

                        "source": field

                    }



        # 4. Unknown


        return {

            "entity":

            "UNKNOWN_ENTITY",

            "confidence":

            0,

            "source":

            "none"

        }