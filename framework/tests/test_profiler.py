from framework.profiling.dataset_profiler import DatasetProfiler


profiler = DatasetProfiler()


result = profiler.profile(
    "data.csv"
)


print(result)