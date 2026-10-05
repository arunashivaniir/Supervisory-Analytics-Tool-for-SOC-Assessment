# SAT-SA

## Supervisory Analytics Tool for SOC Assessment

SAT-SA is an offline, evidence-driven supervisory analytics platform
designed to help NCIIPC examiners assess how effectively Critical Sector
Entities operate their Security Operations Centres (SOCs) using periodic
operational submissions as evidence.

SOC submissions can contain millions of records and may arrive with
different schemas, field names and data structures. SAT-SA converts
these heterogeneous submissions into a common analytical representation,
validates their reliability, detects evidence-backed supervisory
signals, links findings to source evidence and provides peer-cohort
benchmarking for contextual assessment.

## Core Workflow

``` text
SOC Evidence Submission
        |
        v
Dataset Profiling
        |
        v
Role Detection
        |
        v
30-Concept Canonical Mapping
        |
        v
Validation + Integrity Verification
        |
        v
Supervisory Analytics Engine
        |
        v
Assessment Scopes
        |
        v
Evidence-Backed Findings
        |
        v
Peer-Cohort Benchmarking
        |
        v
Examiner Review
        |
        v
Reports
```

**Understand → Assure → Detect → Explain → Review**

## Key Capabilities

### Heterogeneous Dataset Handling

Each submitted dataset is independently profiled and assigned an
operational role where sufficient evidence exists:

-   ALERTS
-   CASES
-   WORKFLOW_EVENTS
-   ASSETS
-   UNKNOWN

Role detection is conservative and avoids forcing unsupported
classifications.

### 30-Concept Canonical Mapping

Source-specific fields are mapped into a common 30-concept canonical
representation.

Mapping confidence is explicitly represented using:

-   MAPPED
-   LOW_CONFIDENCE
-   AMBIGUOUS
-   UNMAPPED
-   INVALID

Uncertain mappings can be reviewed and overridden by the examiner.

### Validation and Integrity

Before analysis, SAT-SA performs 10 validation checks covering
identifiers, duplicates, relationships, timestamps, severity, mapping
consistency, structural constraints, evidence integrity, data quality
and analytical preconditions.

SHA-256 integrity manifests and provenance information maintain
traceability between submitted evidence and analytical results.

Blocking validation or integrity failures prevent unsafe analysis.

### Supervisory Analytics Engine

The current implementation detects five evidence-backed supervisory
signal categories:

1.  Critical alert not escalated
2.  Missing escalation evidence
3.  Repeated asset activity
4.  Repeated investigation evidence
5.  Offline operational anomaly using Isolation Forest

Signals are indicators for supervisory investigation, not automatic
final verdicts.

### Traceable Findings

Every finding can be followed through:

``` text
Signal
  ↓
Reason / Analytical Result
  ↓
Supporting Evidence
  ↓
Source Record
```

This allows the examiner to understand why a finding was raised and
inspect the evidence behind it.

### Assessment Scopes

Results are organised into assessment scopes representing an entity over
an assessment period.

Scopes provide context including:

-   Entity
-   Assessment period
-   Record count
-   Signal count
-   Primary signal
-   Attention indicators
-   Evidence coverage
-   Peer context

### Peer-Cohort Benchmarking

SAT-SA compares assessment results against a peer cohort using seven
operational metrics.

The benchmarking layer uses statistical measures including:

-   Peer median
-   Median Absolute Deviation (MAD)
-   Percentile
-   Rank
-   Modified Z-score

Where a cohort is too small, tied, zero-variance or otherwise unsuitable
for meaningful comparison, SAT-SA explicitly reports the limitation
rather than forcing a ranking.

## Offline Architecture

SAT-SA is designed for local and air-gapped deployment.

``` text
+-----------------------------+
|        Examiner UI          |
| Dataset | Assess | Findings |
| Evidence | Benchmark | Report|
+-------------+---------------+
              |
              v
+-----------------------------+
|       Application/API       |
+-------------+---------------+
              |
              v
+-----------------------------+
|     Analytical Pipeline     |
|                             |
| Profiling                   |
| Role Detection              |
| Canonical Mapping           |
| Validation                  |
| Integrity                   |
| Supervisory Analytics       |
| Peer Benchmarking           |
+-------------+---------------+
              |
              v
+-----------------------------+
| Local Evidence / Results    |
| Provenance / Findings       |
+-----------------------------+
```

The core analytical workflow does not require external cloud APIs.
Sensitive SOC evidence remains within the controlled deployment
environment.

## Setup

### Prerequisites

Recommended environment:

-   Linux
-   Python 3
-   Node.js and npm
-   Git

### Clone

``` bash
git clone (https://github.com/arunashivaniir/Supervisory-Analytics-Tool-for-SOC-Assessment)
cd Supervisory-Analytics-Tool-for-SOC-Assessment
```

### Start Demo Mode

For the evaluator-facing demonstration:

``` bash
SATSA_DATASET_MODE=demo ./dev.sh
```

If an existing SAT-SA instance is already running, stop it first so that
the backend is restarted with the demo-mode environment variable.

Verify:

``` bash
./dev.sh status
```

The status should contain:

``` text
datasets  mode demo
```

Default local endpoints:

``` text
Frontend: http://127.0.0.1:5178
Backend:  http://127.0.0.1:8000
```

### Development / Full Mode

For development and testing:

``` bash
./dev.sh
```

or:

``` bash
SATSA_DATASET_MODE=full ./dev.sh
```

Full mode exposes the development dataset collection.

## Recommended Demo Flow

1.  Open the SAT-SA frontend.
2.  Select **Start Assessment**.
3.  Select a verified demonstration dataset.
4.  Review dataset profiling and detected role.
5.  Review canonical mapping and confidence states.
6.  Review validation status.
7.  Start the assessment.
8.  Open the Overview.
9.  Open an Assessment Scope.
10. Open a finding and follow **Signal → Reason → Evidence → Source
    Record**.
11. Inspect supporting evidence and provenance.
12. Review peer-cohort benchmarking.
13. Open the final report.

## Testing

Backend:

``` bash
python3 -m pytest -q
```

Frontend:

``` bash
cd frontend
npm run typecheck
npm run lint
npm run build
```

End-to-end workflow:

``` bash
npm run check
npm run check:switching
npm run check:roles
npm run check:demo
```

`check:demo` requires the backend to be running in demo mode.

`check:switching` and `check:roles` use development/test datasets and
should be run in full mode.

## Engineering Validation

Current engineering validation includes:

-   1,000+ automated tests
-   10 validation checks
-   30 canonical concepts
-   5 supervisory signal categories
-   7 peer-benchmark metrics
-   SHA-256 evidence integrity verification
-   Provenance tracking
-   Human-in-the-loop mapping review
-   Peer-cohort statistical benchmarking
-   Offline analytical execution

### Large-Scale Benchmark

A synthetic 5-million-record workload was measured at approximately:

``` text
Records:      5,000,000
Runtime:      ~90 seconds
Peak memory:  ~1.57 GB
```

These measurements are engineering results from synthetic data and
should not be interpreted as production SOC performance.

## Design Principles

### Evidence First

Supervisory observations are grounded in submitted operational evidence.

### Explicit Uncertainty

Uncertain mappings and insufficient peer baselines are exposed rather
than silently converted into certainty.

### Analytical Safety

Blocking validation and integrity failures prevent unsafe analysis.

### Traceability

Findings can be traced back to supporting evidence and source records.

### Human Judgement

SAT-SA identifies and prioritises areas for examination. The examiner
remains responsible for contextual interpretation and final supervisory
judgement.

## Limitations

The current performance measurements use synthetic datasets.

Supervisory signals and anomaly detection are indicators for
investigation, not automatic verdicts.

A missing event cannot be detected if the underlying record was never
included in the submitted evidence.

Peer benchmarking depends on the quality and size of the available peer
cohort. SAT-SA explicitly reports when meaningful statistical separation
cannot be established.

Broader expert and field validation remains an important next step
beyond the current engineering validation.

## Project Outcome

SAT-SA provides an end-to-end path from heterogeneous SOC evidence to
supervisory assessment:

``` text
Evidence
   ↓
Understand
   ↓
Assure
   ↓
Detect
   ↓
Explain
   ↓
Benchmark
   ↓
Investigate
   ↓
Examiner Judgement
```

The objective is to shift supervisory assessment from manually searching
large volumes of operational records toward targeted, evidence-backed
examination while preserving evidence integrity, analytical
transparency, statistical limitations and human judgement.
