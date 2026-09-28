class SupervisoryReport:



    def generate(self, entity_results):


        print(
            "\n========== ENTITY SUPERVISORY ASSESSMENT ==========\n"
        )


        for entity in entity_results:


            print(
                "Entity:",
                entity["entity"]
            )


            print(
                "Records Analysed:",
                entity["records_analyzed"]
            )


            print(
                "Attention Score:",
                entity["risk_score"]
            )


            print(
                "Risk Level:",
                entity["risk_level"]
            )


            print(
                "Risk Indicators:"
            )


            for item in entity["risk_indicators"]:

                print(
                    "-",
                    item
                )


            print(
                "\n------------------------------------"
            )