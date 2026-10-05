from framework.features.feature_registry import (
    get_feature_registry
)



class AdaptiveFeatureEngine:


    def __init__(self):

        self.registry = get_feature_registry()



    def get_value(
        self,
        data,
        path
    ):


        keys = path.split(".")


        current = data


        for key in keys:


            if key not in current:

                return None


            current = current[key]


        return current



    def evaluate_available_features(
        self,
        canonical_data
    ):


        results = []


        for feature, metadata in self.registry.items():


            available = True

            missing = []



            for field in metadata["required_fields"]:


                value = self.get_value(

                    canonical_data,

                    field

                )


                if value is None:

                    available = False

                    missing.append(field)



            results.append({

                "feature":

                feature,


                "category":

                metadata["category"],


                "available":

                available,


                "missing_fields":

                missing,


                "description":

                metadata["description"]

            })


        return results