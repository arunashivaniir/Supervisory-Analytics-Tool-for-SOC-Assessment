from framework.entity.entity_resolver import EntityResolver



class EntityEvaluator:


    def __init__(self):

        self.entity_resolver = EntityResolver()




    def evaluate(
            self,
            records,
            findings
    ):


        entity_records = self.group_entities(
            records
        )


        entity_results = []



        for entity, entity_info in entity_records.items():


            entity_findings = [

                finding

                for finding in findings

                if finding.get("entity") == entity

            ]



            assessment = self.create_assessment(

                entity,

                entity_info,

                entity_findings

            )


            entity_results.append(

                assessment

            )



        return entity_results





    def group_entities(
            self,
            records
    ):


        entities = {}



        for record in records:


            entity_details = self.entity_resolver.resolve(

                record

            )


            entity = entity_details["entity"]



            if entity not in entities:


                entities[entity] = {


                    "records": [],


                    "confidence":

                        entity_details["confidence"],


                    "source":

                        entity_details["source"]

                }



            entities[entity]["records"].append(

                record

            )



        return entities





    def create_assessment(
            self,
            entity,
            entity_info,
            findings
    ):


        score = 0


        indicators = []



        for finding in findings:


            indicator = finding.get(

                "indicator"

            )


            if indicator:


                indicators.append(

                    indicator

                )



            severity = finding.get(

                "severity",

                "LOW"

            )



            if severity == "HIGH":


                score += 30



            elif severity == "MEDIUM":


                score += 15



            elif severity == "LOW":


                score += 5




        score = min(

            score,

            100

        )



        if score >= 70:


            risk_level = "HIGH"



        elif score >= 40:


            risk_level = "MEDIUM"



        else:


            risk_level = "LOW"




        return {


            "entity":

                entity,


            "entity_confidence":

                entity_info["confidence"],


            "entity_source":

                entity_info["source"],


            "records_analyzed":

                len(

                    entity_info["records"]

                ),


            "attention_score":

                score,


            "risk_level":

                risk_level,


            "risk_indicators":

                list(

                    set(indicators)

                )

        }