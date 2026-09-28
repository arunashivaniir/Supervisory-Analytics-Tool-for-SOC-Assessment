import json
import copy


class SchemaMapper:


    def __init__(
            self,
            mapping_file,
            schema_file
    ):


        with open(mapping_file) as f:

            self.mappings = json.load(f)



        with open(schema_file) as f:

            self.schema = json.load(f)



    def create_empty_schema(self):

        return copy.deepcopy(
            self.schema
        )



    def set_nested_value(
            self,
            data,
            path,
            value
    ):


        keys = path.split(".")


        current = data


        for key in keys[:-1]:

            current = current[key]


        current[keys[-1]] = value



    def is_valid_value(
            self,
            value
    ):


        if value is None:

            return False


        if str(value).lower() == "nan":

            return False


        if str(value).strip() == "":

            return False


        return True



    def validate_mapping(
            self,
            concept,
            source_column,
            value
    ):


        """
        Prevent incorrect semantic mappings
        """


        # closed_by should never become resolution time

        if (

            concept == "RESOLUTION_TIME"

            and

            "closed_by" in source_column.lower()

        ):

            return False



        # created_time should not become resolution time

        if (

            concept == "RESOLUTION_TIME"

            and

            (

                "created" in source_column.lower()

                or

                "opened" in source_column.lower()

            )

        ):

            return False



        return True



    def map_record(
            self,
            record,
            semantic_mapping
    ):


        canonical_data = self.create_empty_schema()



        for mapping in semantic_mapping:



            source_column = mapping[
                "source_column"
            ]


            concept = mapping[
                "canonical_concept"
            ]


            confidence = mapping.get(
                "confidence",
                0
            )



            # ignore low confidence mappings

            if confidence < 0.45:

                continue



            if concept not in self.mappings:

                continue



            if source_column not in record:

                continue



            value = record[
                source_column
            ]



            if not self.is_valid_value(value):

                continue



            if not self.validate_mapping(

                concept,

                source_column,

                value

            ):

                continue



            canonical_path = self.mappings[concept][
                "canonical_path"
            ]



            self.set_nested_value(

                canonical_data,

                canonical_path,

                value

            )



            # -----------------------------
            # Investigation Evidence Handling
            # -----------------------------


            if concept == "INVESTIGATION_EVIDENCE":


                canonical_data[

                    "investigation_context"

                ][

                    "available"

                ] = True



                canonical_data[

                    "investigation_context"

                ][

                    "evidence_available"

                ] = True



        return canonical_data