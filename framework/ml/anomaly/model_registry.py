"""Artifact and metadata storage for the offline anomaly model.

Two files, deliberately
-----------------------
The pickled estimator and its JSON metadata are stored separately. The metadata
is therefore readable, diffable and auditable with ``cat`` and no code
execution, and a reviewer can confirm what a model claims to be without
unpickling anything.

Integrity
---------
``artifact_sha256`` is computed with ``framework.evidence.integrity``'s
``calculate_sha256`` -- the same utility the evidence layer already uses for
evidence files. There is no second SHA-256 implementation in this module.
Loading verifies the digest and refuses a mismatched artifact, so a model file
that has been swapped or truncated cannot be served silently.

Unpickling notice
-----------------
Loading an artifact executes the pickle. That is inherent to a persisted
scikit-learn estimator. The metadata records the digest precisely so the
provenance of any file can be checked before it is loaded.
"""

from __future__ import annotations

import json
import os
import pickle
from typing import Any, Dict, Optional

from framework.evidence import calculate_sha256


class ModelRegistryError(Exception):
    """The model artifact or its metadata is missing or inconsistent."""


class AnomalyModelRegistry:
    """Stores and retrieves the model artifact alongside its metadata."""

    def __init__(
        self,
        artifact_path: str,
        metadata_path: str,
    ) -> None:

        self.artifact_path = artifact_path
        self.metadata_path = metadata_path

    @classmethod
    def from_config(cls, config) -> "AnomalyModelRegistry":

        settings = config.registry

        if "artifact_path" not in settings or "metadata_path" not in settings:
            raise ModelRegistryError(
                "anomaly_model.json must declare registry.artifact_path and "
                "registry.metadata_path"
            )

        return cls(settings["artifact_path"], settings["metadata_path"])

    # -- public API ---------------------------------------------------------

    def exists(self) -> bool:
        return os.path.isfile(self._absolute(self.artifact_path)) and (
            os.path.isfile(self._absolute(self.metadata_path))
        )

    def save(self, model: Any, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """Write the artifact, then stamp and write its metadata."""

        artifact = self._absolute(self.artifact_path)

        os.makedirs(os.path.dirname(artifact) or ".", exist_ok=True)

        with open(artifact, "wb") as handle:
            pickle.dump(model, handle, protocol=pickle.HIGHEST_PROTOCOL)

        digest = calculate_sha256(artifact)

        # The digest is computed from the bytes on disk, not from the in-memory
        # object, so the metadata always describes the stored artifact.
        recorded = dict(metadata)
        recorded["artifact_sha256"] = digest
        recorded["artifact_path"] = self.artifact_path

        metadata_file = self._absolute(self.metadata_path)

        os.makedirs(os.path.dirname(metadata_file) or ".", exist_ok=True)

        with open(metadata_file, "w") as handle:
            json.dump(recorded, handle, indent=4, sort_keys=True)
            handle.write("\n")

        return recorded

    def load_metadata(self) -> Dict[str, Any]:
        path = self._absolute(self.metadata_path)

        if not os.path.isfile(path):
            raise ModelRegistryError(
                f"anomaly model metadata not found: {self.metadata_path}. "
                f"Train the model before running inference."
            )

        with open(path, "r") as handle:
            return json.load(handle)

    def load(self, verify_digest: bool = True) -> Any:
        """Load the estimator, verifying the recorded digest first."""

        metadata = self.load_metadata()

        artifact = self._absolute(self.artifact_path)

        if not os.path.isfile(artifact):
            raise ModelRegistryError(
                f"anomaly model artifact not found: {self.artifact_path}"
            )

        if verify_digest:

            expected = metadata.get("artifact_sha256")

            if not expected:
                raise ModelRegistryError(
                    "anomaly model metadata carries no artifact_sha256, so "
                    "the artifact cannot be verified"
                )

            observed = calculate_sha256(artifact)

            if observed != expected:
                raise ModelRegistryError(
                    "anomaly model artifact digest does not match its metadata: "
                    f"expected {expected}, observed {observed}"
                )

        with open(artifact, "rb") as handle:
            return pickle.load(handle)

    def artifact_digest(self) -> str:
        return calculate_sha256(self._absolute(self.artifact_path))

    @staticmethod
    def _absolute(path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
