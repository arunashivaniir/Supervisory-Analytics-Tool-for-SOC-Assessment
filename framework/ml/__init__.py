"""Machine-learning layers for SAT-SA.

One capability lives here: offline Isolation Forest anomaly discovery in
``framework.ml.anomaly``.

The package is optional in the sense that importing it does not require
scikit-learn. The estimator is imported lazily inside the detector, so SAT-SA
and its existing test suite run unchanged on a runtime where scikit-learn is
absent, and the anomaly layer reports itself unavailable with the reason
instead of fabricating a verdict.
"""

__all__ = ["anomaly"]
