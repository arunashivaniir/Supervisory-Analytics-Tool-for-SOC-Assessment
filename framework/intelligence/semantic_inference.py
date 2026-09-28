import json



class SemanticInference:


    def __init__(self, config_file):

        with open(config_file, "r") as file:

            self.patterns = json.load(file)




    def infer(self, profiler_output):

        results = []


        for column in profiler_output.get(
            "columns",
            []
        ):


            column_name = column.get(
                "column_name",
                ""
            ).lower()



            category = column.get(
                "category",
                ""
            )



            sample_values = [

                str(value).upper()

                for value in column.get(
                    "sample_values",
                    []
                )

            ]



            best_match = None

            best_confidence = 0



            for concept, rules in self.patterns.items():


                confidence = self.calculate_score(

                    column_name,

                    category,

                    sample_values,

                    rules

                )



                if confidence > best_confidence:


                    best_confidence = confidence


                    best_match = concept




            # Keep meaningful mappings only

            if best_match and best_confidence >= 0.45:


                results.append({

                    "source_column":

                        column_name,


                    "canonical_concept":

                        best_match,


                    "confidence":

                        round(
                            best_confidence,
                            2
                        )

                })



        return results




    def infer_with_candidates(
            self,
            profiler_output
    ):

        """
        Score every concept for every column, once per schema.

        Returns ``{lowercased column name: [{concept, confidence}]}``
        with all candidates at or above the 0.45 apply threshold, best
        first. ``infer()`` is the winner of this table under the same
        strict-greater comparison, so both agree on every column.
        """


        table = {}


        for column in profiler_output.get(
            "columns",
            []
        ):


            lowered = column.get(
                "column_name",
                ""
            ).lower() if isinstance(
                column.get(
                    "column_name",
                    ""
                ),
                str
            ) else ""



            category = column.get(
                "category",
                ""
            )



            sample_values = [

                str(value).upper()

                for value in column.get(
                    "sample_values",
                    []
                )

            ]



            scored = []


            for concept, rules in self.patterns.items():


                confidence = self.calculate_score(

                    lowered,

                    category,

                    sample_values,

                    rules

                )


                if confidence >= 0.45:


                    scored.append({

                        "concept":

                            concept,


                        "confidence":

                            round(
                                confidence,
                                2
                            )

                    })



            scored.sort(
                key=lambda item: item["confidence"],
                reverse=True
            )


            table[lowered] = scored



        return table





    def calculate_score(

            self,

            column_name,

            category,

            sample_values,

            rules

    ):


        score = 0



        #
        # Keyword matching
        #

        keyword_matches = 0



        for keyword in rules.get(

            "keywords",

            []

        ):


            if keyword.lower() in column_name:


                keyword_matches += 1



        if keyword_matches:


            score += min(

                0.5 + ((keyword_matches - 1) * 0.1),

                0.7

            )



        #
        # Negative keyword penalty
        #

        negative_matches = 0



        for keyword in rules.get(

            "negative_keywords",

            []

        ):


            if keyword.lower() in column_name:


                negative_matches += 1



        if negative_matches:


            score -= min(

                negative_matches * 0.25,

                0.5

            )



        #
        # Category validation
        #

        if category in rules.get(

            "expected_categories",

            []

        ):


            score += 0.25



        #
        # Sample value validation
        #

        for pattern in rules.get(

            "value_patterns",

            []

        ):


            pattern = str(pattern).upper()



            for value in sample_values:


                if pattern in value:


                    score += 0.25

                    break



        #
        # Normalize score
        #

        score = max(

            0,

            min(

                score,

                1

            )

        )



        return score