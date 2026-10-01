# SAT-SA
## Supervisory Analytics Tool for SOC Assessment

**SAT-SA** is an offline supervisory analytics platform for examining periodic Security Operations Center (SOC) evidence at scale.

It is designed to help a supervisory examiner move from heterogeneous operational exports to **validated, explainable, source-traceable findings** without replacing human supervisory judgment.

> **Analytics identify. Evidence explains. The examiner decides.**

---

## Overview

SOC submissions commonly arrive as heterogeneous operational exports from SIEM, ITSM/SecOps, workflow, and asset-management systems. SAT-SA converts these submissions into a common analytical representation before applying supervisory checks.

The current pipeline is:

```text
Periodic SOC Submission
        │
        ▼
Dataset Profiling
        │
        ▼
Role Detection
        │
        ▼
Canonical Mapping
        │
        ▼
Validation & Integrity
        │
        ▼
Supervisory Analytics
        │
        ▼
Finding + Rationale
        │
        ▼
Source Evidence + Provenance
        │
        ▼
Examiner Review
```

The system is intentionally designed as an **assessment and supervisory triage instrument**, not as a SOC operating platform.

---

## Core Capabilities

### Submission Understanding
- Schema and dataset profiling
- Record, column, datatype, null, uniqueness, and distribution analysis
- Automatic dataset role detection:
  - `ALERTS`
  - `CASES`
  - `WORKFLOW_EVENTS`
  - `ASSETS`
  - `UNKNOWN`

### Canonical Representation
SAT-SA maps heterogeneous source fields into a common registry of **30 canonical concepts**.

Mappings retain explicit state and confidence:

```text
MAPPED
LOW_CONFIDENCE
AMBIGUOUS
UNMAPPED
INVALID
```

Examiners can review mappings, apply overrides, and rerun analysis using the corrected interpretation.

### Validation and Integrity
The pipeline validates structural and relational consistency before analysis, including:

- Required-field checks
- Duplicate identifiers
- Conflicting identifiers
- Orphaned cases and workflow events
- Missing relationships
- Severity and timestamp validity
- Chronology constraints
- Mapping collisions

Evidence handling also maintains provenance information and SHA-256 integrity manifests.

### Supervisory Analytics
The current live analytical layer contains five implemented signals:

| Signal | Analytical basis |
|---|---|
| Critical alert not escalated | Critical severity combined with recorded non-escalation |
| Missing escalation evidence | Expected escalation evidence absent or incomplete |
| Repeated asset activity | Statistical concentration / binomial tail test |
| Repeated investigation evidence | High-similarity investigation evidence clusters |
| Operational anomaly | Offline Isolation Forest over operational features |

The anomaly model operates locally and uses a deterministic configuration.

### Explainability and Traceability

Findings preserve a traceable evidence chain:

```text
Signal
  ↓
Rationale
  ↓
Derived Result
  ↓
Canonical Record
  ↓
Original Source Record
  ↓
Provenance / Integrity
```

The objective is to allow an examiner to inspect **why** a finding was raised and **which source evidence supports it**.

---

## Analytical Model

SAT-SA follows an evidence-first processing model:

1. **Understand the submission before analysis.**
2. **Preserve uncertainty instead of forcing ambiguous mappings.**
3. **Validate structural and relational assumptions before generating findings.**
4. **Keep analytical results linked to source evidence.**
5. **Present findings as supervisory signals for human review, not automated decisions.**

This separation reduces the risk of treating malformed, incomplete, or incorrectly mapped data as reliable supervisory evidence.

---

## Offline Architecture

SAT-SA is designed for restricted and air-gapped environments.

```text
┌─────────────────────────────────────────────┐
│                 Local Machine               │
│                                             │
│  Browser UI                                 │
│      │                                      │
│      ▼                                      │
│  FastAPI Adapter                            │
│      │                                      │
│      ▼                                      │
│  SAT-SA Analytical Pipeline                 │
│      ├── Profiling                          │
│      ├── Canonical Mapping                  │
│      ├── Validation                         │
│      ├── Evidence / Provenance              │
│      ├── Supervisory Analytics              │
│      └── Anomaly Detection                  │
│                                             │
│  Local filesystem / in-process data stores  │
└─────────────────────────────────────────────┘
```

Design characteristics:

- Localhost execution
- No cloud or SaaS dependency
- No external AI/API dependency
- No telemetry dependency
- No CDN dependency
- CPU-based analytical execution
- GPU not required

---

## Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| API | FastAPI, Uvicorn |
| Data / Analytics | Python, Pandas, DuckDB, NumPy, SciPy |
| ML | scikit-learn / Isolation Forest |
| Input | CSV, JSON, NDJSON/JSONL, SQLite |
| Integrity | SHA-256 manifests and provenance tracking |
| Deployment | Linux offline bundle / localhost |

---

## Performance Profile

Measured local execution on the current pipeline:

| Dataset Size | Approx. Input Size | Runtime | Peak RSS |
|---:|---:|---:|---:|
| 100K records | 10.8 MB | ~8 s | ~313 MB |
| 1M records | 108 MB | ~22–30 s | ~1 GB |
| 5M records | 541 MB | ~90 s | ~1.57 GB |

A Linux application bundle is also produced for offline distribution.

Performance figures are environment-dependent and are provided as engineering measurements rather than deployment guarantees.

---

## Validation and Verification

SAT-SA separates **software verification** from **supervisory correctness validation**.

### Software verification
Automated tests cover implementation behaviour across ingestion, profiling, mapping, validation, evidence handling, analytics, anomaly detection, and related framework components.

### Supervisory validation
Analytical correctness requires comparison against expert-reviewed or otherwise ground-truthed records.

The repository contains the validation framework needed to support this process; numerical precision/recall claims should only be reported after a labelled expert-review study has been completed.

---

## Synthetic Enterprise SOC Data

The repository contains synthetic datasets modeled on common enterprise security-system export structures.

They are intended for development, demonstration, profiling, mapping, validation, and scale testing.

**These files are synthetic and must not be represented as real NCIIPC or organizational SOC records.**

| Dataset | Approx. Records | Intended Role |
|---|---:|---|
| `splunk_style_soc_alerts_q3_2026.csv` | 60,000 | `ALERTS` |
| `servicenow_style_secops_cases_q3_2026.csv` | 30,000 | `CASES` |
| `servicenow_style_workflow_events_q3_2026.csv` | 50,000 | `WORKFLOW_EVENTS` |
| `soc_asset_inventory_q3_2026.csv` | ~3,500 | `ASSETS` |
| `SAT-SA_demo_Q3_2026.csv` | Demo dataset | End-to-end demonstration |

---

## Local Development

The repository provides a local launcher:

```bash
./dev.sh
```

Supported commands:

```bash
./dev.sh start
./dev.sh stop
./dev.sh restart
./dev.sh status
./dev.sh doctor
./dev.sh logs
```

Services are bound to `127.0.0.1`.

### Run the test suite

```bash
pytest -q
```

---

## Packaging

Offline packaging and verification utilities are available under:

```text
packaging/
```

They include the Linux build configuration, starter data, package verification, and browser verification components.

---

## Repository Structure

```text
SAT-SA/
├── backend/          FastAPI application layer
├── framework/        Core analytical pipeline
├── frontend/         React + TypeScript application
├── packaging/        Offline packaging and verification
├── docs/             Scope, workflow, and implementation documentation
├── dev.sh            Local development launcher
└── *.csv             Synthetic enterprise SOC datasets
```

---

## Scope

SAT-SA is intended for **periodic supervisory assessment of SOC evidence**.

It is not:

- a SIEM
- a SOC replacement
- a real-time monitoring platform
- a continuous telemetry collector
- a centralized national monitoring platform
- an automated supervisory decision-maker

The examiner remains responsible for interpreting findings and making supervisory decisions.

---

## Current Release Scope

The current implementation is centered on **single-dataset assessment and evidence-backed supervisory triage**.

Capabilities such as broader peer benchmarking, cross-period trend analysis, multi-file assessment packages, expanded supervisory rule coverage, and expert-labelled validation are areas for continued development and validation rather than claims of completed functionality in this release.

---

## Project

**SAT-SA — Supervisory Analytics Tool for SOC Assessment**

**Codename:** CIPHER  
**Cyber Intelligence Platform for Holistic Evaluation & Review**

Built for offline, evidence-preserving analysis of periodic SOC operational submissions.
