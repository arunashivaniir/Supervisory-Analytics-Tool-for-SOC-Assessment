# SAT-SA: Supervisory Analytics Tool for SOC Assessment

**Smart India Hackathon 2026** | Problem Statement 26157 | Team HexBytes | NCIIPC

An offline analytics tool that helps a supervisory examiner assess how well a Critical Sector Entity ran its Security Operations Centre, using the entity's own periodic SOC submission as the evidence.

Every finding is produced by an explicit signal, carries the records it came from, and traces back to the submitted rows. Submissions in different schemas are mapped to one canonical model, and any mapping the system is unsure about is shown to the examiner rather than hidden.

It supports supervisory judgement. It does not replace it.

> Setup takes about five minutes: see [Installation](#installation), then [Evaluator quick start](#evaluator-quick-start).

## Contents

| Section | What it covers |
|---|---|
| [The problem](#the-problem) | What PS 26157 asks for |
| [What SAT-SA does](#what-sat-sa-does) | The solution, end to end |
| [What SAT-SA is not](#what-sat-sa-is-not) | Scope boundaries |
| [Architecture](#architecture) | Pipeline and where authority sits |
| [Capabilities](#capabilities) | What is actually implemented |
| [Installation](#installation) | Requirements and setup |
| [Evaluator quick start](#evaluator-quick-start) | Walkthrough |
| [Detection and benchmarking](#detection-and-benchmarking) | Signals and peer comparison |
| [Offline operation](#offline-operation) | Air-gapped deployment |
| [Validation and performance](#validation-and-performance) | Measured, with limits stated |
| [Limitations](#limitations) | Read this one |

---

## The problem

Critical Sector Entities (CSEs) run Security Operations Centres, and NCIIPC examiners assess how effective those SOCs are. The evidence is the SOC's own operational records: alerts, cases and workflow events submitted periodically.

Three things make manual review hard:

- **Scale.** A single submission can hold hundreds of thousands to millions of records, and an examiner can read only a sample.
- **Heterogeneity.** Each entity exports different schemas, field names and formats, so the same concept appears under many names.
- **Reproducibility.** A finding that cannot be traced to specific records is hard to defend or repeat.

## What SAT-SA does

It reads a periodic submission and turns it into a traceable assessment:

**Understand → Assure → Detect → Explain → Review**

| Stage | What happens |
|---|---|
| **Understand** | Profiles the schema, detects the dataset role (`ALERTS`, `CASES`, `WORKFLOW_EVENTS`, `ASSETS`, `UNKNOWN`), and maps source fields to 30 canonical concepts. |
| **Assure** | Runs 10 validation checks and verifies SHA-256 manifests. If integrity fails, analysis is blocked. |
| **Detect** | Raises supervisory signals and compares each assessment scope against a peer cohort. |
| **Explain** | Gives every finding its reason, supporting evidence and source-record references. |
| **Review** | The examiner inspects findings, resolves uncertain mappings and forms the judgement. |

## What SAT-SA is not

| It is not | Because |
|---|---|
| a SIEM | it does not collect or correlate live logs |
| a SOC | it does not detect intrusions |
| real-time monitoring | it assesses periodic submissions, after the fact |
| autonomous | it takes no action; a signal is an indicator, not a determination |
| a cloud or SaaS service | it runs entirely offline, with no external API |
| a replacement for the examiner | it prioritises and evidences; a human decides |

## Architecture

```text
SOC submission (CSV / JSON / NDJSON / SQLite)
        │
        ▼
  Data understanding ──── profiling · role detection · canonical mapping
        │                 (MAPPED / LOW_CONFIDENCE / AMBIGUOUS / UNMAPPED / INVALID)
        ▼
  Evidence assurance ──── 10 validation checks · SHA-256 manifests
        │                 integrity failure blocks analysis
        ▼
  Signal engine ───────── 5 supervisory signals
        │
        ▼
  Peer benchmarking ───── median · MAD · percentile · rank · modified Z-score
        │
        ▼
  Traceable findings ──── Signal → Reason → Evidence → Source record
        │
        ▼
  HUMAN EXAMINER ──────── forms the supervisory judgement
```

Everything an examiner acts on is traceable to submitted rows. The only machine-learning component is an offline Isolation Forest anomaly detector with a fixed random seed, so results are reproducible. No external AI service is involved at any point.

## Capabilities

| Capability | Status |
|---|---|
| Ingestion: CSV, JSON, NDJSON, SQLite | implemented |
| Schema profiling and dataset role detection | implemented |
| Canonical mapping to 30 concepts, with confidence states | implemented |
| Examiner review and override of uncertain mappings | implemented |
| 10 validation checks | implemented |
| SHA-256 integrity verification and provenance manifests | implemented |
| Analysis gate on integrity failure | implemented |
| 5 supervisory signals | implemented |
| Peer benchmarking on 7 operational metrics | implemented |
| Traceable findings with source-record drill-down | implemented |
| Large-dataset path (DuckDB), measured to 5M records | implemented |
| Fully local operation, no cloud dependency | implemented |
| Linux offline bundle (~242 MB) | implemented |

---

## Installation

### Requirements

- Linux
- Python 3.10 or later
- Node.js 18 or later, with npm
- Git
- A web browser (the interface is served locally)
- No GPU required

```bash
python3 --version && node --version && npm --version && git --version
```

### From source

```bash
git clone <REPOSITORY_URL>
cd <REPOSITORY_NAME>
git checkout v6

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

npm install
```

### Run

**Option A: single script** (if `dev.sh` is present)

```bash
chmod +x dev.sh
./dev.sh
```

**Option B: services separately**

```bash
# Terminal 1: backend
source .venv/bin/activate
uvicorn <backend_module>:app --host 127.0.0.1

# Terminal 2: frontend
npm run dev
```

Open the local URL printed by Vite. Bind to `127.0.0.1` only; do not expose the development server to an untrusted network.

### Offline bundle

The Linux bundle (~242 MB) contains the backend, frontend, configuration and starter data. Copy it to the target machine, extract it, and run its start script. No installation or internet access is needed.

---

## Evaluator quick start

| # | Action | What to look for |
|---|---|---|
| 1 | Start SAT-SA (see [Run](#run)) and open the local URL | The interface loads with no external requests |
| 2 | **New Assessment**, upload a SOC evidence dataset | Schema profile and detected dataset role |
| 3 | Open **Data Understanding** | 30 canonical concepts, each with a confidence state |
| 4 | Override a `LOW_CONFIDENCE` or `AMBIGUOUS` mapping | The examiner stays in control of uncertain fields |
| 5 | Open **Evidence Assurance** | 10 checks and SHA-256 verification; analysis is permitted only if they pass |
| 6 | Run supervisory analysis | The detected signals, each with a reason |
| 7 | Open **Peer Benchmarking** | Observed value, peer median, percentile, rank, MAD, modified Z-score |
| 8 | Select a finding | Why it was raised, its evidence and its source records |

---

## Detection and benchmarking

### Signals (5)

| Signal | Meaning |
|---|---|
| Critical alert not escalated | A critical alert with no escalation |
| Missing escalation evidence | Escalation is expected, but no supporting record exists |
| Repeated asset activity | The same asset recurs in alerts beyond expectation |
| Repeated investigation evidence | Near-duplicate investigation records |
| Offline operational anomaly | Isolation Forest: 300 trees, 11 features, contamination 0.05, fixed seed |

### Every finding carries

```text
Signal → Reason → Evidence → Source record
```

The final step re-reads the submission itself, so what an examiner verifies is the entity's own data.

### Peer benchmarking

For each assessment scope SAT-SA selects a peer cohort and calculates the peer median, Median Absolute Deviation (MAD), percentile, rank and modified Z-score across 7 operational metrics.

It does not force a comparison. When the cohort has zero spread or is too small, the metric is reported as limited or non-separable (for example, *Tied, no peer separation*) instead of producing a misleading ranking.

---

## Offline operation

SAT-SA makes no external network connection: no cloud API, no CDN, no telemetry. Evidence stays inside the deployment environment.

| Component | Internet to prepare | Internet to run |
|---|---|---|
| Analysis pipeline | no | no |
| Python and Node dependencies | once, to download | no |
| Offline bundle | no | no |

---

## Validation and performance

### Performance

Measured on large **synthetic** SOC datasets, single machine:

| Records | Runtime |
|---|---|
| 100,000 | ~8 s |
| 1,000,000 | ~22–30 s |
| 5,000,000 | ~90 s, peak memory ~1.57 GB |

These are measurements from the tested environment, not hardware-independent capacity guarantees.

### Detection validation

`<PRECISION / RECALL against seeded ground truth: fill in, or state "not yet measured">`

Synthetic ground truth is not expert validation. A generator that injects the conditions the signals look for agrees with them partly by construction.

### Testing

```bash
pytest              # backend and analytics tests
npm run check       # frontend checks
npm run build       # production build verification
```

The project includes 1000+ automated tests covering the analytical and application layers.

---

## Limitations

- **Synthetic data.** All performance and accuracy figures come from synthetic datasets. `<State exactly what expert review, if any, was performed.>`
- **After the fact.** SAT-SA assesses periodic submissions. It has no live view of any entity and is not a monitoring tool.
- **Indicators, not verdicts.** A signal is an observable pattern. It does not by itself establish misconduct, control failure, malicious activity or root cause. The examiner decides.
- **Absent records produce no signal.** Signals that read a record cannot fire when the record was never written.
- **Anomaly detection is a prioritisation aid.** The fixed contamination of 0.05 means about 5% of records are flagged by construction; read the result as a ranking, not a rate estimate.
- **Scope-limited detection.** Five signals cover the conditions the problem statement names. They are not an exhaustive model of SOC quality.
- **Platform.** The offline bundle and setup instructions are Linux only. Windows has not been built or tested.
- **No live ingestion.** Database connections and API ingestion are not implemented.

## Configuration and development

- After changing backend framework or benchmark configuration files, **restart the backend** so the new configuration is loaded.
- Keep credentials in environment variables or an untracked `.env` file.
- Do not commit real SOC datasets to version control.

## License

`<LICENSE: to be specified by the team>`
