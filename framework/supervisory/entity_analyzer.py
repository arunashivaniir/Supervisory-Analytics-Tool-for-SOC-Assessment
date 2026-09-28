class EntityAnalyzer:


    def analyze(
            self,
            canonical_records,
            feature_results
    ):


        entity_summary = {

            "total_records":
                len(canonical_records),

            "execution_gaps":
                {},

            "risk_indicators":
                [],

            "attention_score":
                0

        }



        gap_count = 0



        for record_features in feature_results:


            for feature in record_features:


                if not feature["available"]:


                    feature_name = feature["feature"]


                    if feature_name not in entity_summary["execution_gaps"]:

                        entity_summary["execution_gaps"][feature_name] = 0


                    entity_summary["execution_gaps"][feature_name] += 1


                    gap_count += 1



        entity_summary["attention_score"] = self.calculate_score(

            gap_count,

            len(canonical_records)

        )


        entity_summary["risk_indicators"] = self.generate_indicators(

            entity_summary["execution_gaps"]

        )


        return entity_summary





    def calculate_score(
            self,
            gaps,
            records
    ):


        if records == 0:

            return 0


        score = (

            gaps / records

        ) * 100


        return round(

            min(score,100),

            2

        )





    def generate_indicators(
            self,
            gaps
    ):


        indicators = []


        for gap,count in gaps.items():


            indicators.append(

                {

                "indicator":
                    gap,

                "occurrences":
                    count

                }

            )


        return indicators