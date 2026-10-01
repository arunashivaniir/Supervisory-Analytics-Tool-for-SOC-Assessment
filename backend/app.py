"""Local HTTP adapter in front of the SAT-SA pipeline.

This service is transport. It discovers evidence files, starts a pipeline run,
and returns that run's result. It does not interpret the result: it holds no
threshold, no severity rule, no score comparison, no capability list and no
finding classification of its own. Every analytical value the React frontend
displays is produced by ``SATSAPipeline`` and passed through unchanged.

Deliberately absent from this file:

* any comparison of a score or a count against a limit
* any mapping from a status string to a severity, rank or priority
* any dataset chosen by name
* any aggregation that the pipeline has not already performed

If a value is needed in the UI and the pipeline does not produce it, it does
not belong here; it belongs in an intelligence layer, which is out of scope
for the frontend work.

Runs entirely on localhost against local files. No outbound network access.
"""

from __future__ import annotations

import os
import threading
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.datasets import (
    bundle_root,
    list_datasets,
    repository_root,
    resolve_dataset,
)
from backend.jobs import AnalysisStore

# The frontend dev server origin. Fixed, not a wildcard, so the adapter is
# reachable only from the local UI.
ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]

app = FastAPI(
    title="SAT-SA Local Adapter",
    description=(
        "Thin transport in front of the existing SAT-SA pipeline. "
        "The pipeline is the single source of truth for every analytical value."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

store = AnalysisStore()

# The React bundle, when it has been built. Served read-only so the whole
# application can run from one origin with no CDN. In a frozen executable
# this lives inside the bundle; in development it is frontend/dist.
FRONTEND_DIST = os.path.join(bundle_root(), "frontend", "dist")


class AnalysisRequest(BaseModel):
    """A request to analyse one repository dataset."""

    dataset: str = Field(
        ...,
        description="Repository-relative path to a dataset file.",
    )


class PreviewRequest(BaseModel):
    """A request to preview submitted datasets without analysing them."""

    datasets: List[str] = Field(
        ...,
        description="Repository-relative dataset paths, boundaries preserved.",
    )
    explicit_roles: Optional[Dict[str, str]] = Field(
        default=None,
        description="Reviewer role per dataset path; detection otherwise.",
    )
    mapping_overrides: Optional[Dict[str, Dict[str, Any]]] = Field(
        default=None,
        description="Reviewer concept per source field per dataset path.",
    )


@app.post("/api/previews")
def create_previews(request: PreviewRequest) -> Dict[str, Any]:
    """Preview each submitted dataset independently. No analytics run.

    Every dataset gets its own preview entry: either the bounded
    canonical preview or an error entry saying why it could not be
    previewed. One bad file never fails the rest of the package. The
    existing single-dataset analysis endpoint is untouched.
    """

    from backend.serialisation import serialisable_result
    from framework.canonical.preview import preview_dataset
    from framework.pipeline import SATSAPipeline

    pipeline = SATSAPipeline()
    previews: List[Dict[str, Any]] = []

    for dataset in request.datasets or []:
        try:
            absolute = resolve_dataset(dataset)
        except FileNotFoundError:
            previews.append({"dataset": dataset, "error": "Dataset not found"})
            continue
        except ValueError as error:
            previews.append({"dataset": dataset, "error": str(error)})
            continue

        relative = os.path.relpath(absolute, repository_root())

        try:
            from backend.evidence_store import gate_dataset

            gate_dataset(relative)
        except Exception as error:  # noqa: BLE001 - reported per dataset
            from backend.evidence_store import EvidenceAnalysisBlocked

            if isinstance(error, EvidenceAnalysisBlocked):
                previews.append({"dataset": dataset, "error": error.reason})
                continue

            raise

        try:
            preview = preview_dataset(
                dataset,
                pipeline,
                explicit_role=(request.explicit_roles or {}).get(dataset),
                mapping_overrides=(request.mapping_overrides or {}).get(dataset),
            )
        except FileNotFoundError:
            previews.append({"dataset": dataset, "error": "Dataset not found"})
            continue
        except Exception as error:  # noqa: BLE001 - reported per dataset
            previews.append(
                {"dataset": dataset, "error": f"{type(error).__name__}: {error}"}
            )
            continue

        previews.append(preview)

    return serialisable_result({"previews": previews})


@app.get("/api/health")
def health() -> Dict[str, Any]:
    """Liveness, and whether the intelligence stack imported cleanly."""

    pipeline_available = True
    pipeline_error: Optional[str] = None

    try:
        from framework.pipeline import SATSAPipeline  # noqa: F401
    except Exception as error:  # noqa: BLE001
        pipeline_available = False
        pipeline_error = f"{type(error).__name__}: {error}"

    return {
        "status": "ok" if pipeline_available else "degraded",
        "pipeline_available": pipeline_available,
        "pipeline_error": pipeline_error,
        "retained_analyses": len(store._order),  # noqa: SLF001 - diagnostic
    }


@app.get("/api/datasets")
def datasets() -> Dict[str, Any]:
    """Every dataset file available for analysis.

    A listing, not a recommendation. The frontend may present these; it must
    not treat the first, the largest or any particular one as the subject of
    the assessment.
    """

    return {"datasets": list_datasets()}


@app.post("/api/analyses")
def create_analysis(request: AnalysisRequest) -> Dict[str, Any]:
    """Start a pipeline run and return immediately."""

    try:
        absolute = resolve_dataset(request.dataset)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset not found")
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    relative = os.path.relpath(absolute, repository_root())

    # A dataset that is registered evidence is analysed only if the evidence
    # trust layer's own gate allows it. This is the same check
    # ``verify_analysis_target`` performs before an analysis layer reads a
    # working copy, applied here because the adapter is what starts a run; a
    # submission whose digest no longer matches its registration is refused
    # rather than analysed, and a preserved original is never a target.
    try:
        from backend.evidence_store import gate_dataset

        gated = gate_dataset(relative)
    except Exception as error:  # noqa: BLE001 - mapped below
        from backend.evidence_store import EvidenceAnalysisBlocked

        if isinstance(error, EvidenceAnalysisBlocked):
            detail: Dict[str, Any] = {"reason": error.reason}

            if error.comparison is not None:
                detail["comparison"] = {
                    "status": error.comparison.status.value,
                    "expected_sha256": error.comparison.expected_sha256,
                    "observed_sha256": error.comparison.observed_sha256,
                    "detail": error.comparison.detail,
                }

            raise HTTPException(status_code=409, detail=detail)

        raise

    job = store.create(request.dataset)

    worker = threading.Thread(
        target=store.run,
        args=(job,),
        name=f"satsa-analysis-{job.id[:8]}",
        daemon=True,
    )
    worker.start()

    state = job.public_state(include_result=False)
    state["resolved_path"] = relative

    if gated is not None:
        # Recorded so the run states which submission it read and that the
        # submission verified, rather than the interface inferring it.
        state["evidence"] = gated

    return state


@app.get("/api/analyses")
def list_analyses() -> Dict[str, Any]:
    """Job states without their results, oldest first."""

    return {"analyses": store.public_states(include_result=False)}


def _require_job(job_id: str) -> Any:
    job = store.get(job_id)

    if job is None:
        raise HTTPException(status_code=404, detail="Analysis not found")

    return job


@app.get("/api/analyses/{job_id}")
def get_analysis(job_id: str, include_result: bool = True) -> Dict[str, Any]:
    """Job state, with the pipeline result once the run has finished."""

    job = _require_job(job_id)
    state = job.public_state(include_result=include_result)

    if include_result and job.status == "processing":
        # The result is not ready yet. Said plainly rather than as an empty
        # result, so the frontend never renders "no findings" for a run that
        # has not happened.
        state["result"] = None

    return state


@app.get("/api/analyses/{job_id}/export.json")
def export_analysis(job_id: str) -> Any:
    """The analysis as the interface consumed it.

    This is the transport export for the examiner's records: the same
    intelligence-layer output the screen displayed, including every omitted
    key's explanation. It is not a report; the adapter does not author
    supervisory text.
    """

    from fastapi.responses import JSONResponse

    job = _require_job(job_id)

    if job.status == "processing":
        raise HTTPException(status_code=409, detail="Analysis still processing")

    if job.status == "error":
        raise HTTPException(status_code=409, detail="Analysis failed")

    filename = f"satsa-{os.path.basename(job.dataset)}-analysis.json"

    return JSONResponse(
        content={"result": job.result, "omitted_keys": job.omitted_keys},
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        media_type="application/json",
    )


@app.get("/api/analyses/{job_id}/export-full.json")
def export_full_analysis(job_id: str) -> Any:
    """The complete pipeline result, streamed from the on-disk export.

    Includes the per-record keys the interface does not carry. The file is
    written once when the run finishes and served as-is, so the bytes are the
    pipeline's own output rather than a reconstruction.
    """

    from fastapi.responses import FileResponse

    job = _require_job(job_id)

    if job.status == "processing":
        raise HTTPException(status_code=409, detail="Analysis still processing")

    if job.status == "error":
        raise HTTPException(status_code=409, detail="Analysis failed")

    if not job.export_path or not os.path.isfile(job.export_path):
        raise HTTPException(status_code=410, detail="Full export no longer retained")

    filename = f"satsa-{os.path.basename(job.dataset)}-full-result.json"

    return FileResponse(
        path=job.export_path,
        media_type="application/json",
        filename=filename,
    )


# ---------------------------------------------------------------------------
# Evidence integrity
#
# Transport only, over ``framework.evidence``. No digest is calculated or
# compared here, and no status is decided here: each response is the return
# value of the evidence trust layer's own verification. A submission whose
# digest does not match its registration is reported as INTEGRITY_FAILED with
# the registered and observed digests, and its analysis gate reported closed.
# That is a result, not a transport error, so it is returned with 200.
# ---------------------------------------------------------------------------


def _evidence_error(error: Exception) -> HTTPException:
    """Map the trust layer's own errors onto transport status codes."""

    from framework.evidence.integrity import (
        EvidenceNotFoundError,
        EvidenceValidationError,
    )

    if isinstance(error, EvidenceNotFoundError):
        return HTTPException(status_code=404, detail=str(error))

    if isinstance(error, EvidenceValidationError):
        return HTTPException(status_code=400, detail=str(error))

    return HTTPException(status_code=500, detail=f"{type(error).__name__}: {error}")


@app.get("/api/evidence")
def list_evidence() -> Dict[str, Any]:
    """Every registered evidence submission and its integrity, verified now.

    Each entry carries the digest the manifest registered, the digest observed
    for the preserved original and for the controlled working copy, the
    provenance that was supplied and the provenance that was not, and whether
    the evidence trust layer permits analysis to proceed.
    """

    from backend.evidence_store import inventory

    return {"evidence": inventory()}


@app.get("/api/evidence/{evidence_id}")
def get_evidence(evidence_id: str) -> Dict[str, Any]:
    """One registered submission, verified on read."""

    from backend.evidence_store import describe

    try:
        return describe(evidence_id)
    except Exception as error:  # noqa: BLE001 - mapped below
        raise _evidence_error(error)


@app.post("/api/evidence/{evidence_id}/verify")
def verify_evidence(evidence_id: str) -> Dict[str, Any]:
    """Re-verify one submission through the evidence trust layer.

    The action behind the interface's ``Verify Integrity`` control. The
    comparison is performed by the trust layer; this route only returns what it
    reported.
    """

    from backend.evidence_store import verify

    try:
        return verify(evidence_id)
    except Exception as error:  # noqa: BLE001 - mapped below
        raise _evidence_error(error)


if os.path.isdir(FRONTEND_DIST):
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # The interface is a single-page application, so a reload on a deep link
    # asks for a path that is not a file. Without this the browser gets a 404
    # for its own route, and reloading on /findings would appear to lose the
    # application. Only non-API paths fall through to the application shell.
    @app.get("/{spa_path:path}", include_in_schema=False)
    def serve_application(spa_path: str) -> Any:
        candidate = os.path.normpath(os.path.join(FRONTEND_DIST, spa_path))
        within_dist = candidate == FRONTEND_DIST or candidate.startswith(
            FRONTEND_DIST + os.sep
        )

        if within_dist and os.path.isfile(candidate):
            return FileResponse(path=candidate)

        return FileResponse(path=os.path.join(FRONTEND_DIST, "index.html"))

    # Mounted last so it cannot shadow an API route.
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
