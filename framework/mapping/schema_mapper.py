import json
import copy


# Timestamp concepts the actor-column guard applies to. RESOLUTION_TIME
# keeps its original dedicated rules below; the Phase 1 timestamp
# concepts share the generalized *_by rejection.
TIMESTAMP_CONCEPTS = frozenset({
    "RESOLUTION_TIME",
    "EVENT_TIMESTAMP",
    "TRIGGERED_AT",
    "ACKNOWLEDGED_AT",
    "CLOSED_AT",
    "WORKFLOW_EVENT_AT",
})


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



        # Actor columns (closed_by, resolved_by, opened_by, ...) name a
        # person, never an instant. They must not become any timestamp
        # concept, however time-shaped the rest of the name looks. This
        # extends the closed_by rule above to the Phase 1 timestamp
        # concepts; the RESOLUTION_TIME rules are unchanged.

        if (

            concept in TIMESTAMP_CONCEPTS

            and

            source_column.lower().endswith("_by")

        ):

            return False



        return True



    def map_record(
            self,
            record,
            semantic_mapping,
            decisions=None
    ):

        """
        Project one record onto the canonical schema.

        ``semantic_mapping`` is the legacy winner list
        ``[{source_column, canonical_concept, confidence}]`` and behaves
        exactly as before when ``decisions`` is None. When schema-level
        ``decisions`` (see ``framework.canonical.decisions``) are supplied,
        entries decided AMBIGUOUS or INVALID are not applied: a field the
        schema pass could not decide is left unmapped rather than guessed.
        """


        canonical_data = self.create_empty_schema()



        if decisions is not None:

            usable = [
                item for item in semantic_mapping
                if self._decision_allows(item, decisions)
            ]

        else:

            usable = semantic_mapping



        for mapping in usable:



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



            value, found = self._read_record(record, source_column)


            if not found:

                continue



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


    def _decision_allows(
            self,
            mapping,
            decisions
    ):

        """
        Whether a schema-level decision permits applying a mapping entry.

        Entries without a recorded decision are allowed (legacy callers
        pass none at all); recorded AMBIGUOUS and INVALID entries are
        blocked. Matching is on the lowercased source column, the same
        key the inference pass reports.
        """

        wanted = mapping.get("source_column")

        for decision in decisions:

            if decision.get("source_column") != wanted:
                continue

            if decision.get("canonical_concept") != mapping.get(
                "canonical_concept"
            ):
                continue

            return bool(decision.get("applied", True))

        return True


    def _read_record(
            self,
            record,
            source_column
    ):

        """
        Read a source column from a record, tolerating header case.

        ``SemanticInference`` reports lowercased column names while
        records keep the submission's original spelling, so an exact
        lookup is tried first and a case-insensitive one second.
        Ambiguous duplicates (two keys differing only by case) resolve
        to the exact spelling when present, else the first in record
        order — and the collision is the ingestion layer's to report,
        not this mapper's to guess further on.
        """

        if source_column in record:

            return record[source_column], True


        lowered = source_column.lower()


        for key in record:

            if isinstance(key, str) and key.lower() == lowered:

                return record[key], True


        return None, False