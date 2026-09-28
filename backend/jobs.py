"""Analysis job tracking for the local adapter.

A SAT-SA run over a large evidence file takes minutes, so the adapter runs it
on a worker thread and reports progress. This is scheduling only. The analysis
itself is whatever ``SATSAPipeline.run`` returns, stored unmodified.
"""

from __future__ import annotations

import datetime
import json
import os
import tempfile
import threading
import traceback
import uuid
from typing import Any, Dict, List, Optional

from backend.datasets import repository_root, resolve_dataset
from backend.serialisation import serialisable_result

#: Retained analyses. The tool is a single-examiner local application, so this
#: is a small ring rather than a database. Dropping the oldest entry is
#: announced through the store's length, not hidden.
MAX_RETAINED = 8

#: Pipeline result keys the user interface consumes.
#:
#: This is a transport list, not a preference. Every intelligence layer writes
#: to a key that appears here, so the interface can show a value only where the
#: pipeline produced one. The two keys below are absent because they are
#: per-record materialisations of a file of arbitrary size, not because their
#: contents are in any way less valid.
TRANSPORTED_KEYS: tuple = (
    "dataset",
    "profile",
    "ingestion",
    "semantic_mapping",
    "mapping_report",
    "canonical_package",
    "dataset_context",
    "assessment",
    "capability_assessment",
    "execution_gap_findings",
    "negative_space_findings",
    "operational_pattern_findings",
    "anomaly_findings",
    "entity_assessment",
    "supervisory_findings",
)

#: Keys present in a pipeline result but not sent to the browser, with the
#: reason. Declared so the interface can state what it is not showing instead
#: of appearing to have nothing to show.
VOLUMETRIC_KEYS: tuple = ("canonical_records", "feature_analysis")

OMITTED_KEY_REASON = (
    "Per-record material carried for every submitted record. Present in the "
    "pipeline result and in the full export; not sent to the browser because "
    "its size is a function of the evidence file, not of the analysis."
)

EXPORT_DIRECTORY = os.path.join(repository_root(), "artifacts", "analyses")


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class AnalysisJob:
    """One pipeline run and its lifecycle."""

    def __init__(self, dataset: str) -> None:
        self.id = uuid.uuid4().hex
        self.dataset = dataset
        self.status = "processing"
        self.created_at = _now()
        self.started_at: Optional[str] = None
        self.finished_at: Optional[str] = None
        self.result: Optional[Dict[str, Any]] = None
        self.omitted_keys: List[Dict[str, str]] = []
        self.export_path: Optional[str] = None
        self.error: Optional[str] = None
        self.error_detail: Optional[str] = None
        self.log: List[str] = []

    def public_state(self, include_result: bool = True) -> Dict[str, Any]:
        """The job as the frontend sees it.

        ``status`` is one of processing, complete or error. It describes the
        run, never the contents of the analysis.
        """

        state: Dict[str, Any] = {
            "job_id": self.id,
            "dataset": self.dataset,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "log": list(self.log),
        }

        if self.status == "error":
            state["error"] = self.error
            state["error_detail"] = self.error_detail

        if include_result and self.result is not None:
            state["result"] = self.result
            state["omitted_keys"] = list(self.omitted_keys)
            state["full_export_available"] = self.export_path is not None

        return state

    def discard_export(self) -> None:
        """Remove the on-disk full export belonging to this job."""

        if self.export_path and os.path.isfile(self.export_path):
            try:
                os.unlink(self.export_path)
            except OSError:
                pass

        self.export_path = None


class AnalysisStore:
    """In-memory job registry, guarded by a lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: Dict[str, AnalysisJob] = {}
        self._order: List[str] = []

    def create(self, dataset: str) -> AnalysisJob:
        job = AnalysisJob(dataset)

        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._evict()

        return job

    def get(self, job_id: str) -> Optional[AnalysisJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def public_states(self, include_result: bool = False) -> List[Dict[str, Any]]:
        """Every retained job's state, in the order the runs were started.

        Collected under a single acquisition. The lock is not reentrant, so a
        caller that iterated ``_order`` while holding it and then called
        :meth:`get` for each id would deadlock the whole service.
        """

        with self._lock:
            return [
                job.public_state(include_result=include_result)
                for job_id in self._order
                if (job := self._jobs.get(job_id)) is not None
            ]

    def _evict(self) -> None:
        while len(self._order) > MAX_RETAINED:
            dropped = self._order.pop(0)
            evicted = self._jobs.pop(dropped, None)

            if evicted is not None:
                evicted.discard_export()

    def run(self, job: AnalysisJob) -> None:
        """Execute the pipeline for a job. Never raises."""

        job.started_at = _now()

        try:
            from framework.pipeline import SATSAPipeline

            # Validate the request against the repository, then hand the
            # pipeline the repository-relative path rather than the absolute
            # one. The pipeline echoes the path it was given into
            # result["dataset"], result["ingestion"] and
            # result["assessment"]["source"], so passing an absolute path would
            # make the displayed subject depend on where the service happens to
            # be started from, and would put the local directory layout on
            # screen. The same dataset must produce the same result however it
            # is invoked.
            resolve_dataset(job.dataset)
            raw = SATSAPipeline().run(job.dataset)

            serialised = serialisable_result(raw)

            # The full result goes to disk first. It is written before the
            # interface payload is assembled so that a failure to store the
            # complete result cannot leave a partial export behind that looks
            # authoritative.
            os.makedirs(EXPORT_DIRECTORY, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w",
                suffix=".json",
                prefix=f"{job.id}-",
                dir=EXPORT_DIRECTORY,
                delete=False,
                encoding="utf-8",
            )

            try:
                with handle:
                    json.dump(serialised, handle, default=str)

                job.export_path = handle.name
            except BaseException:
                handle.close()
                os.unlink(handle.name)
                raise

            job.result = {
                key: serialised[key] for key in TRANSPORTED_KEYS if key in serialised
            }
            job.omitted_keys = [
                {"key": key, "reason": OMITTED_KEY_REASON}
                for key in VOLUMETRIC_KEYS
                if key in serialised
            ]

            unexpected = [
                key
                for key in serialised
                if key not in TRANSPORTED_KEYS and key not in VOLUMETRIC_KEYS
            ]

            if unexpected:
                # A new pipeline key must not be dropped without saying so.
                job.omitted_keys.extend(
                    {"key": key, "reason": "Not declared for transport."}
                    for key in sorted(unexpected)
                )

            job.status = "complete"
        except Exception as error:  # noqa: BLE001 - reported to the frontend
            job.status = "error"
            job.error = f"{type(error).__name__}: {error}"
            job.error_detail = traceback.format_exc()
        finally:
            job.finished_at = _now()
