class MappingReport:


    def generate(
            self,
            profile,
            semantic_mapping
    ):


        total_columns = len(
            profile.get(
                "columns",
                []
            )
        )


        mapped_columns = len(
            semantic_mapping
        )


        unmapped = []


        mapped_names = [

            item["source_column"]

            for item in semantic_mapping

        ]



        for column in profile.get(
            "columns",
            []
        ):


            name = column[
                "column_name"
            ]


            if name not in mapped_names:

                unmapped.append(
                    name
                )



        high = []

        medium = []

        low = []



        for item in semantic_mapping:


            confidence = item[
                "confidence"
            ]


            if confidence >= 0.85:

                high.append(item)



            elif confidence >= 0.5:

                medium.append(item)



            else:

                low.append(item)



        confidence_score = 0


        if mapped_columns > 0:

            confidence_score = round(

                (

                    mapped_columns /

                    total_columns

                )

                *

                100,

                2

            )



        return {


            "dataset_columns":

                total_columns,


            "mapped_columns":

                mapped_columns,


            "unmapped_columns":

                unmapped,


            "high_confidence":

                high,


            "medium_confidence":

                medium,


            "low_confidence":

                low,


            "overall_mapping_confidence":

                confidence_score

        }