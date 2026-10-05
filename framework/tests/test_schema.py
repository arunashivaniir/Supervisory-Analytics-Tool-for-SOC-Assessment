from framework.canonical.schema_validator import (
    CanonicalSchemaValidator
)


validator = CanonicalSchemaValidator(
    "framework/canonical/canonical_schema.json"
)


sample = {

    "entity_context": {},

    "alert_context": {},

    "investigation_context": {},

    "response_context": {},

    "asset_context": {},

    "monitoring_context": {},

    "metadata": {}

}


print(
    validator.validate(sample)
)