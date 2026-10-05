# SAT-SA: Supervisory Analytics Tool for SOC Assessment

**Smart India Hackathon 2026** | Problem Statement 26157 | Team HexBytes

SAT-SA is an offline supervisory analytics tool that helps examiners assess Security Operations Centre (SOC) submissions systematically. It profiles submitted evidence, maps heterogeneous records to a common canonical schema, validates integrity, detects evidence-backed supervisory signals, and lets the examiner trace every finding back to its source records.

**Workflow:** Understand → Assure → Detect → Explain → Review

---

## Key Capabilities

| Area | Description |
|---|---|
| **Data understanding** | Schema profiling, dataset role detection (alerts, cases, workflow events, assets), and mapping to 30 canonical concepts. Each mapping carries a confidence state (`MAPPED`, `LOW_CONFIDENCE`, `AMBIGUOUS`, `UNMAPPED`, `INVALID`) with examiner override. |
| **Evidence assurance** | 10 validation checks, SHA-256 integrity verification and provenance manifests. Analysis is blocked if integrity fails. |
| **Signal detection** | Critical alert not escalated; missing escalation evidence; repeated asset activity; repeated investigation evidence; offline operational anomaly detection. |
| **Traceable findings** | Every finding follows *Signal → Reason → Evidence → Source record*. |
| **Peer benchmarking** | Compares a scope against a peer cohort using median, MAD, percentile, rank and modified Z-score. Reports limited or non-separable cohorts instead of forcing a ranking. |
| **Offline operation** | No cloud or external API dependency; evidence stays inside the deployment environment. |

## Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React, TypeScript, Vite, Tailwind CSS |
| Backend | Python, FastAPI, Pandas |
| Analytics and storage | DuckDB, NumPy, SciPy, scikit-learn |
| Input formats | CSV, JSON, NDJSON, SQLite |
| Integrity | SHA-256, provenance manifests |

---

## Setup

### Requirements

- Linux (recommended)
- Python 3.10 or later
- Node.js 18 or later, with npm
- Git

Verify the installed versions:

```bash
python3 --version && node --version && npm --version && git --version
```

### 1. Clone the repository

```bash
git clone <REPOSITORY_URL>
cd <REPOSITORY_NAME>
git checkout v6
```

### 2. Install backend dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Install frontend dependencies

```bash
npm install
```

### 4. Run the application

**Option A: single script** (if `dev.sh` is present)

```bash
chmod +x dev.sh
./dev.sh
```

**Option B: run services separately**

Terminal 1, backend:

```bash
source .venv/bin/activate
uvicorn <backend_module>:app --host 127.0.0.1
```

Terminal 2, frontend:

```bash
npm run dev
```

Open the local URL printed by Vite in your browser.

> Bind services to `127.0.0.1` only. Do not expose the development server to untrusted networks.

---

## Usage

1. **Create an assessment.** Select *New Assessment* and upload the SOC evidence dataset.
2. **Review data understanding.** Check source-to-canonical mappings and resolve `LOW_CONFIDENCE`, `AMBIGUOUS` or `UNMAPPED` fields with an override where needed.
3. **Run evidence assurance.** Validation and SHA-256 checks must pass before analysis is permitted.
4. **Run supervisory analysis.** Review the detected signals and their reasons.
5. **Review peer benchmarking.** Compare the scope against its cohort. Cohorts with no spread are shown as *Tied, no peer separation*.
6. **Investigate findings.** Open any finding to see why it was raised, its supporting evidence and the original source records.

---

## Testing

```bash
pytest              # backend and analytics tests
npm run check       # frontend type and lint checks
npm run build       # production build verification
```

The project includes 1000+ automated tests covering the analytical and application layers.

## Performance

Measured on large **synthetic** SOC datasets:

| Metric | Result |
|---|---|
| Records processed | 5,000,000 |
| Runtime | ~90 seconds |
| Peak memory (RSS) | ~1.57 GB |
| Offline bundle size | ~242 MB (Linux) |

These are measurements from the tested environment, not hardware-independent guarantees.

---

## Limitations

SAT-SA is a decision-support tool, not an autonomous decision-maker. A detected signal indicates an observable pattern in the submitted evidence. It does not by itself establish misconduct, control failure, malicious activity or root cause. Final interpretation rests with the examiner.

## Data Handling

- Process all evidence locally; do not commit real SOC datasets to version control.
- Keep credentials and configuration in environment variables or an untracked `.env` file.
- After changing backend framework or benchmark configuration files, restart the backend so the new configuration is loaded.

## License

<LICENSE: to be specified by the team>
