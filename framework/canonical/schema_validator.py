import json


class CanonicalSchemaValidator:


    def __init__(self, schema_file):

        with open(schema_file) as f:

            self.schema = json.load(f)



    def validate(self, data):

        missing = []


        for section in self.schema:

            if section not in data:

                missing.append(section)


        return {

            "valid":
            len(missing) == 0,

            "missing_sections":
            missing

        }