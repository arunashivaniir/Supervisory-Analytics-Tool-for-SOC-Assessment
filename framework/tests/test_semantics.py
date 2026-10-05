from framework.profiling.dataset_profiler import DatasetProfiler
from framework.intelligence.semantic_inference import SemanticInference



profiler = DatasetProfiler()



profile = profiler.profile(
    "data.csv"
)



engine = SemanticInference(

    "framework/config/semantic_patterns.json"

)



results = engine.infer(
    profile
)



for result in results:

    print(result)