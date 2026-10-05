from framework.supervisory.risk_scoring import RiskScoring



class EntityEvaluator:


    def __init__(self):

        self.scorer = RiskScoring()



    def evaluate(
            self,
            canonical_records,
            feature_results
    ):


        entity_data = {}



        for index, record in enumerate(canonical_records):


            entity = (
                record
                .get("entity_context", {})
                .get("entity_id")
            )


            if not entity:

                entity = "UNKNOWN_ENTITY"



            if entity not in entity_data:


                entity_data[entity] = {

                    "records": 0,

                    "findings": []

                }



            entity_data[entity]["records"] += 1



            features = feature_results[index]



            for feature in features:


                # Supervisory gaps are identified
                # when expected evidence is missing

                if feature["available"] is False:


                    entity_data[entity]["findings"].append(

                        feature["feature"]

                    )



        results = []



        for entity, data in entity_data.items():


            findings = list(

                set(
                    data["findings"]
                )

            )



            score = self.scorer.calculate_score(

                findings

            )



            results.append({

                "entity": entity,

                "records_analyzed":
                    data["records"],

                "risk_score":
                    score,

                "risk_level":
                    self.scorer.risk_level(score),

                "risk_indicators":
                    findings

            })



        return results