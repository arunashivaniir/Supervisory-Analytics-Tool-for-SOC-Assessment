from framework.intelligence.context.capability_map import CapabilityMap



class DatasetContextAnalyzer:


    def analyze(
            self,
            profile,
            semantic_mapping
    ):


        result = CapabilityMap()



        concepts = [

            item["canonical_concept"]

            for item in semantic_mapping

        ]



        # Evidence based detection

        self.detect_alert_management(

            concepts,
            result

        )


        self.detect_network_data(

            concepts,
            result

        )


        self.detect_investigation_data(

            concepts,
            result

        )


        self.detect_asset_data(

            concepts,
            result

        )



        return result.to_dict()



    def detect_alert_management(
            self,
            concepts,
            result
    ):


        evidence = []


        required = [

            "SECURITY_SEVERITY",

            "RESOLUTION_TIME"

        ]


        for item in required:

            if item in concepts:

                evidence.append(item)



        confidence = len(evidence)/len(required)



        if confidence > 0:


            result.add(

                "ALERT_MANAGEMENT",

                confidence,

                evidence

            )



    def detect_network_data(
            self,
            concepts,
            result
    ):


        network_concepts = [

            "NETWORK_PROTOCOL",

            "TRAFFIC_BYTES",

            "PACKET_COUNT",

            "CONNECTION_DURATION"

        ]



        evidence = [

            c for c in network_concepts

            if c in concepts

        ]



        if evidence:


            result.add(

                "NETWORK_ANALYSIS",

                len(evidence)/len(network_concepts),

                evidence

            )



    def detect_investigation_data(
            self,
            concepts,
            result
    ):


        evidence = []


        if "INVESTIGATION_EVIDENCE" in concepts:

            evidence.append(
                "INVESTIGATION_EVIDENCE"
            )



        if evidence:


            result.add(

                "INVESTIGATION_WORKFLOW",

                1.0,

                evidence

            )



    def detect_asset_data(
            self,
            concepts,
            result
    ):


        if "ASSET_IDENTIFIER" in concepts:


            result.add(

                "ASSET_CONTEXT",

                1.0,

                [

                    "ASSET_IDENTIFIER"

                ]

            )