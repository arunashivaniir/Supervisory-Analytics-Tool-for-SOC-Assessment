from framework.mapping.schema_mapper import SchemaMapper


mapper = SchemaMapper(

    "framework/config/mappings.json",

    "framework/canonical/canonical_schema.json"

)


semantic_mapping = [

    {
        "source_column":"priority",

        "canonical_concept":
        "SECURITY_SEVERITY"

    },

    {
        "source_column":"hostname",

        "canonical_concept":
        "ASSET_IDENTIFIER"

    },

    {
        "source_column":"close_time",

        "canonical_concept":
        "RESOLUTION_TIME"

    }

]


record = {

    "priority":"HIGH",

    "hostname":"WEB_SERVER_01",

    "close_time":120

}


result = mapper.map_record(

    record,

    semantic_mapping

)


print(result)