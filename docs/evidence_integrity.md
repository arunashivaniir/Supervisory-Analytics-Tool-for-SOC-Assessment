# SAT-SA Evidence Integrity

## Why this layer exists

An NCIIPC examiner or a security auditor can receive SOC evidence from a
Critical Sector Entity as a CSV, a JSON export, or a periodic evidence package
(ZIP). The first question is not "what does this data say?" -- it is:

> Can I demonstrate that the evidence I am analysing is the evidence that was
> submitted, and that it has not been altered since registration?

Without an answer to that question, every downstream finding inherits an
unproven assumption about its own source. A supervisory finding derived from
evidence that cannot be tied back to a specific, unmodified submission is not
defensible on challenge.

The SAT-SA Evidence Trust Layer establishes evidence identity, integrity and
provenance **before** any analytics run. It does not interpret SOC data, does
not contain a second analytics engine, and does not change any existing
analytical logic. The existing SAT-SA framework remains the single analytical
engine; this layer only makes the input to that engine verifiable and
traceable.

The question above is answered by *detection*, not by prevention. SAT-SA
registers a SHA-256 fingerprint of the submitted bytes and re-checks it before
analysis, so an altered file is reported instead of analysed. It cannot
physically prevent the alteration, and it cannot defend against someone who
edits the evidence and the local manifest together. Read
*What the integrity control actually is* before relying on this layer.

## Scope and non-scope

This is an evidence integrity and controlled handling layer for supervisory
assessment. It is **not**:

- a SOC or SIEM,
- a real-time monitoring or alerting system,
- a source of supervisory findings or risk decisions,
- a replacement for human auditor or examiner judgement.

It is **not** currently:

- cryptographically immutable storage,
- a digital signature or PKI scheme,
- tamper-proof storage, or an append-only ledger,
- authenticated, access-controlled or encrypted at rest.

Those are deliberately out of scope for this phase (see *Limitations*).

## What the integrity control actually is

> **SAT-SA does not claim to make locally stored evidence physically immutable.
> It establishes a registered cryptographic fingerprint and detects changes to
> registered evidence before analysis.**

The implementation contains four separate things. They are often conflated, and
only two of them are about detection. Keep them apart:

### 1. Application-level write protection

Immediately after registration, the owner write bit is cleared on each
preserved original (`originals_read_only` in the manifest). This is a
**handling control**: it stops a well-behaved process from overwriting
registered evidence by accident, and it makes an accidental edit obvious during
a manual review of the file's mode bits.

It is **not** a security boundary and **not** a cryptographic one. The owning
account can restore the bit with `chmod`, `unlock_preserved_original()` does
exactly that as a named maintenance operation, and a privileged filesystem user
is not affected by it at all. Nothing is *prevented* by this control. If the
flag cannot be set (an unsupported filesystem, a read-only mount), intake
continues and records `originals_read_only: false` rather than failing.

### 2. Integrity detection using SHA-256

This is the control that actually detects change. Intake computes the SHA-256
digest of the bytes written to disk and registers it in the manifest. Before
any analysis, `verify` recomputes the digest of the registered file and compares
it. Mismatch produces `INTEGRITY_FAILED`, both digests are reported, and the
exit code is non-zero so the run does not silently continue.

This is **detection, not prevention**. The tool reports that a file no longer
matches its registration; it does not stop the modification from happening, and
it cannot recover the original bytes once they are gone.

### 3. Preservation of the original evidence

The submitted bytes are copied once into `originals/<evidence_id>/` and are
never rewritten by SAT-SA. Every run analyses `working/<evidence_id>/dataset/`,
a separate analysis copy, so normalisation, type coercion or reformatting during
analysis cannot alter the preserved artefact. Re-registering the same
submission raises `EvidenceConflictError` rather than overwriting it.

Preservation is a **process guarantee about how this tool uses the data**, not a
guarantee about the filesystem. It holds for every operation SAT-SA performs;
it says nothing about what an administrator with shell access could do.

### 4. The limitation that a privileged user can change both sides

The manifest is a plain local JSON file holding the reference digests. It is
**not signed, not anchored, and not stored in append-only storage**. Therefore a
privileged filesystem user who can edit `originals/` can also edit the manifest
and replace the digest, and verification will then pass against the altered
bytes. The same applies to a user who can write to both the manifest and the
working copy.

In a single-operator local directory, therefore, the practical guarantee is:

> registered evidence cannot be changed **undetectably by accident or by an
> ordinary, non-privileged process** that does not also edit the manifest.

Anything stronger requires a trust anchor outside this directory: a signature, a
transparency log, a timestamped receipt, or a digest published to a system the
local user cannot rewrite. That is the first item in *Next steps*.

**Terminology.** This document and the tool use *preserved*, *write-protected*,
*fingerprint*, *registered digest* and *change detected*. It does not describe
evidence as immutable, tamper-proof, cryptographically immutable or
administrator-proof, because none of those are implemented.

## Architecture

```
CSE / Company
    |
    v
Evidence Submission (CSV | JSON | ZIP)
    |
    v
SAT-SA Evidence Intake          <- framework/evidence/intake.py
    |  validate, classify, SHA-256
    v
Integrity Verification          <- framework/evidence/integrity.py
    |
    v
Evidence Registration
    |  manifest + provenance     <- framework/evidence/{manifest,provenance}.py
    v
Preserve Original Evidence      <- originals/<evidence_id>/  (write-protected)
    |
    +--> Working Copy            <- working/<evidence_id>/dataset/
            |
            v
        Existing SAT-SA Framework (unchanged)
            |
            v
        Supervisory Findings -> Entity Assessment
            |
            v
        Human Auditor / Examiner Review
```

The evidence layer is dataset-agnostic. It does not know or care whether the
submission contains alerts, investigations, assets, escalations, case
management or network data. Interpreting that data remains entirely the job of
the existing semantic inference and mapping framework.

## Running the analysis on registered evidence

The SAT-SA pipeline accepts an optional evidence-aware mode:

```bash
python -m framework.pipeline <dataset.csv>                        # unchanged
python -m framework.pipeline --from-evidence <EVIDENCE_ID>        # evidence mode
```

Local development mode needs no evidence registration and behaves exactly as
before. Evidence mode resolves the identifier through the registered evidence
workspace and refuses to run unless the evidence verifies.

```
[+] Resolving evidence
[+] Evidence ID: SATSA-EV-20260927T074707Z-a25d94190953
[+] Verifying evidence integrity
[+] Integrity status: VERIFIED
[+] Loading controlled working copy
[+] Working copy: .../working/SATSA-EV-.../dataset/alerts.csv
[+] Running SAT-SA analysis
```

The order of operations in evidence mode is deliberate:

1. **Resolve** the identifier. It is validated as an opaque token
   (`[A-Za-z0-9][A-Za-z0-9._-]*`, no `..`, no separators, no absolute paths)
   before it is ever joined to a directory, and the manifest must exist. A
   user-supplied value is never treated as a path, so traversal, absolute-path
   injection and arbitrary working-copy selection are all impossible.
2. **Verify the preserved original** against its registered SHA-256.
3. **Verify the controlled working copy** against the same registered digest.
   The working copy is the artefact that is about to be analysed, so analysing
   an unverified substitute is refused. A missing working copy is refused
   rather than silently regenerated.
4. **Analyse the working copy** -- never the preserved original. The preserved
   path is not even printed.

The result gains a single optional field:

```python
result["evidence_id"]   # present only in evidence mode
```

Everything else in the result is produced by the unmodified analytical
framework. `print_summary` renders the evidence ID only when the field is
present, so direct-mode output is unchanged.

If anything fails, the command reports why and stops before the analytical
engine is constructed:

```
[!] Evidence integrity verification failed
[!] Status: INTEGRITY_FAILED
[!] Subject: preserved original
[!] Path: .../originals/SATSA-EV-.../alerts.csv
[!] Expected SHA-256: a25d94190953eafe731cc96a72cbeaa9c5ed9a97cf252f418b5aeae992d4e106
[!] Observed SHA-256: 3d3b413a00c8593d010386cbd42b75b5f732ae7496178b8a358fdc33ee954619
[!] Detail: Evidence digest differs from the registered value; the file changed after registration
[!] Analysis aborted
```

There is no fallback to a user-supplied file, no analysis of the preserved
original, and no way to skip verification.

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Analysis completed. |
| 1 | No arguments; usage printed. |
| 2 | Usage error, or both a dataset and `--from-evidence` were supplied. |
| 3 | Evidence could not be resolved, or verification did not succeed. Analysis did not run. |

`--evidence-root <dir>` selects the evidence workspace (default
`data/evidence`). It is only read in evidence mode; direct mode ignores it.

### Packages

Evidence mode resolves exactly one analysis target: the working copy of the
registered original. For a ZIP submission that is the package itself, which the
single-file analytical pipeline cannot read. Extracted members remain available
under `working/<evidence_id>/package/` and can be analysed individually in
direct mode. There is deliberately no `--member` option: selecting a member
from the command line would reintroduce user-controlled working-copy selection.


## SHA-256 integrity

`framework/evidence/integrity.py` provides the cryptographic primitive.

```python
from framework.evidence import calculate_sha256, verify_sha256

digest = calculate_sha256("received/alerts.csv")   # 64 hex characters
result = verify_sha256("received/alerts.csv", digest)
result.status          # IntegrityStatus.VERIFIED
result.verified        # True
```

Properties:

- **Standard library only** (`hashlib`). No cloud hashing service, no upload,
  no network call, no external API, no external AI.
- **Chunked.** The file is read in 1 MiB binary windows, so a multi-gigabyte
  evidence package never has to fit in memory.
- **Format-agnostic.** CSV, JSON, ZIP and arbitrary binary evidence are all
  read as bytes. Nothing assumes text or an encoding.
- **Explicit.** Verification always returns a structured `IntegrityResult`
  with a status, the expected digest and the observed digest. There is no
  silent success path and no boolean-only "is it fine?" answer.

### Verification statuses

| Status | Meaning |
| --- | --- |
| `VERIFIED` | Observed digest equals the registered digest. |
| `INTEGRITY_FAILED` | Observed digest differs from the registered digest. The evidence changed after registration. |
| `MISSING` | The registered file is no longer present. |
| `UNAVAILABLE` | Verification could not be performed meaningfully (no registered digest, malformed digest, unreadable file, or a path that is not a regular file). |

`UNAVAILABLE` never reports success. Verification fails closed.

## Evidence intake flow

`framework/evidence/intake.py` performs, in order:

1. **Path validation** -- the path must exist, must be a regular file, and must
   not be a symbolic link (unless explicitly allowed). Preserved originals
   cannot be re-registered as a new submission.
2. **Metadata inspection** -- filename, size, modification time and a
   content-type label (by extension, then by content sniffing). Purely
   descriptive; no parsing of the submission.
3. **SHA-256 calculation** of the submitted file.
4. **Evidence ID allocation** -- `SATSA-EV-<UTC timestamp>-<first 12 hex of
   SHA-256>`. The identifier is derived only from the content digest and the
   registration moment. It contains no entity name, sector, dataset type,
   filename or assessment period, so it is meaningful for any submission.
5. **Duplicate refusal** -- if the same SHA-256 is already registered in the
   workspace, intake fails with `EvidenceConflictError` naming the existing
   evidence ID. Because the identifier contains a timestamp, duplicate
   detection compares *digests* rather than identifiers, so it does not depend
   on clock resolution. An examiner is pointed at the existing registration to
   verify instead. A second copy can be registered deliberately with
   `allow_duplicate=True`.
6. **Preservation of the original** into `originals/`, hashed *as it is
   written*, then compared against the digest observed in step 3. A source
   that changes mid-intake is rejected and nothing is preserved.
7. **Working copy creation** as a physically separate file.
8. **Package handling** if the submission is a ZIP: members are validated, then
   extracted one at a time into the working area.
9. **Manifest and provenance records** written as JSON.
10. **Immediate re-verification** of the preserved original against the
    recorded digest. If that fails, the whole registration is rolled back.

If any step fails, the partially written submission is removed, so the
workspace never contains a half-registered evidence item.

## Original versus working copy

This is the central separation.

```
Original Evidence   data/evidence/originals/<evidence_id>/<file>
    |  registered SHA-256, write-protected, never touched by analysis
    |
    +--> Working Copy   data/evidence/working/<evidence_id>/dataset/<file>
             |
             +--> the existing SAT-SA pipeline reads this
```

- The working copy is a **separate file**, not a link. Analysis can modify,
  reformat or normalise it without any possibility of affecting the preserved
  original.
- The pipeline is expected to receive the working copy path, for example
  `python -m framework.pipeline data/evidence/working/<evidence_id>/dataset/alerts.csv`.
- The preserved original has application-level write protection (owner write bit
  cleared) after registration. This is a **handling control against accidental
  modification by a well-behaved process**, not a security boundary: the same
  operating system account can restore the write bit, and root or an
  administrator can modify the file regardless. See
  *What the integrity control actually is*.
- `unlock_preserved_original()` exists as an explicit, named maintenance
  action for an examiner who needs write access in order to *demonstrate* that
  change detection works. It is never called automatically.

### Workspace layout

```
data/evidence/
    originals/<evidence_id>/<file>            preserved original, write-protected
    manifests/<evidence_id>.manifest.json     what arrived, and its digest
    provenance/<evidence_id>.provenance.json  who/what sent it, and when
    working/<evidence_id>/dataset/<file>      controlled analysis copy
    working/<evidence_id>/package/...         validated extracted ZIP members
```

The store is a plain directory tree. An examiner can inspect it with ordinary
tools, archive it, and re-verify it without any SAT-SA component running.

## Manifest

`framework/evidence/manifest.py` records *what arrived*.

```json
{
  "schema_version": "1.0",
  "evidence_id": "SATSA-EV-20260927T073107Z-9284ed4fd7fe",
  "created_at": "2026-09-27T07:31:07Z",
  "hash_algorithm": "sha256",
  "originals_read_only": true,
  "file_count": 1,
  "total_size": 12,
  "files": [
    {
      "name": "alerts.csv",
      "stored_name": "alerts.csv",
      "relative_path": "alerts.csv",
      "size": 12,
      "sha256": "9284ed4fd7fe1346904656f329db6cc49c0e7ae5b8279bff37f96bc6eb59baad",
      "modified_at": "2026-09-27T07:31:07Z",
      "content_type": "csv",
      "role": "original",
      "location": "originals"
    }
  ],
  "notes": {"intake": "sat-sa-evidence-intake/1.0"}
}
```

Notes:

- Timestamps are UTC and ISO-8601 with a `Z` suffix, for machine readability.
- `location` says whether a file lives under `originals/` or `working/`, so a
  manifest entry can always be resolved back to a real path.
- `sha256` is the registered integrity fingerprint: the reference value that
  every later verification compares against.
- `originals_read_only` records only that the owner write bit was cleared on
  the preserved originals at registration. It is a handling control, not a
  security claim, and it is not consulted during verification.
- For a ZIP package, the package itself is hashed as the `original`, and each
  extracted member is recorded separately with its own size and digest.
- `relative_path` values are always resolved through a containment check, so a
  tampered manifest cannot redirect a verification read outside the workspace.
- The manifest is unsigned local JSON. An edit to `sha256` is therefore a
  successful attack against a single-operator local store, not a failure mode
  that verification can catch. See point 4 above.

## Provenance

`framework/evidence/provenance.py` records *who/what sent it, and when*.

| Field | Source | Behaviour when absent |
| --- | --- | --- |
| `evidence_id` | generated | always present |
| `received_at` | intake clock (UTC) | always present |
| `original_filename` | filesystem | always present |
| `file_size` | filesystem | always present |
| `sha256` | computed | always present |
| `package_type` | classified | may be `unknown` |
| `source_identifier` | submitter | `null`, listed in `unavailable_fields` |
| `assessment_period` | submitter | `null`, listed in `unavailable_fields` |
| `submitted_by` | submitter | `null`, listed in `unavailable_fields` |
| `received_channel` | submitter | `null`, listed in `unavailable_fields` |

The layer never invents a company name, a CSE identifier, a submitter name or
an assessment period. Missing information is represented explicitly as `null`
and enumerated in `unavailable_fields`, so an auditor can see the gap instead
of reading a plausible fabrication. The record also carries a small chain of
custody (`EVIDENCE_RECEIVED`, `ORIGINAL_PRESERVED`, `ANALYSIS_COPY_CREATED`),
metadata only.

The record is generic enough to serve both an NCIIPC supervisory assessment and
an independent security audit: it carries no sector-specific fields.

## Change detection

The judge's concern, demonstrated explicitly.

```
$ python -m framework.evidence.intake alerts.csv
[+] Evidence intake started
[+] Evidence ID: SATSA-EV-20260927T073107Z-9284ed4fd7fe
[+] File: alerts.csv
[+] Size: 12 bytes
[+] SHA-256 integrity fingerprint registered: 9284ed4fd7fe1346904656f329db6cc49c0e7ae5b8279bff37f96bc6eb59baad
[+] Original evidence preserved: .../originals/SATSA-EV-.../alerts.csv
[+] Application-level write protection enabled: True
[+] Working copy created: .../working/SATSA-EV-.../dataset/alerts.csv
[+] Manifest generated: .../manifests/SATSA-EV-....manifest.json
[+] Provenance recorded: .../provenance/SATSA-EV-....provenance.json
[!] Unavailable provenance fields: source_identifier, submitted_by, assessment_period, received_channel
[+] Integrity status: VERIFIED
[i] Locally stored evidence is not made physically immutable by this step: it is a registered SHA-256 fingerprint, and the original is preserved with application-level write protection only. A privileged filesystem user can still modify both the evidence and its manifest.
```

Later, the preserved original is modified. Re-verification against the recorded
manifest reports the change rather than accepting it:

```
$ python -m framework.evidence.intake verify SATSA-EV-20260927T073107Z-9284ed4fd7fe
[+] Verifying SATSA-EV-20260927T073107Z-9284ed4fd7fe
  alerts.csv: INTEGRITY_FAILED
    Expected SHA-256: 9284ed4fd7fe1346904656f329db6cc49c0e7ae5b8279bff37f96bc6eb59baad
    Observed SHA-256: 3f7b2e0cd8427f75d14932149fba2f71c86adfa240a89b3c722fea1d0433ac7a
```

The verification exit code is non-zero when any file fails, so the check can be
scripted into an examiner's workflow. This is **detection**: the modification
was not prevented, it was found. See point 2 of *What the integrity control
actually is*.

Note that modifying the *working copy* is normal and expected -- that is what
analysis is for -- and does not affect the integrity status of the evidence.
Only the preserved original and the extracted package members are verified.

## Controls

Implemented in this phase:

- **Local processing only.** No internet dependency, no cloud service, no SaaS,
  no external API, no external AI. The evidence modules import nothing beyond
  the Python standard library; a test asserts this.
- **No execution of submitted content.** Files are only ever read as bytes.
  Nothing is imported, evaluated, `exec`'d, or run as a command. Filenames are
  never interpreted as anything other than filenames.
- **Safe ZIP handling.** `extractall` is never used. Every member name is
  validated and re-resolved against the extraction root before any write, and
  each destination file is opened in exclusive-create mode.
- **Path traversal prevention.** Rejected member names include `../`, nested
  traversal such as `a/../../x`, absolute POSIX paths, Windows drive-letter
  paths, backslash-separated traversal, null bytes, control characters,
  over-long names and over-deep nesting. Symbolic-link members and encrypted
  members are rejected.
- **Decompression-bomb bounds.** A package is refused if it declares more than
  10,000 members, a single member larger than 1 GiB, or more than 4 GiB of
  total uncompressed content. Archive CRCs are checked before extraction.
- **No silent replacement.** Copies are created with exclusive-create mode, so
  existing evidence is never overwritten. A byte-identical re-submission is
  refused by digest, and duplicate identifiers are suffixed rather than
  reused.
- **No content logging.** Only metadata (names, sizes, digests, timestamps) is
  recorded. File contents are never logged, echoed, or duplicated into the
  records.
- **Application-level write protection** on preserved originals, as a handling
  control against accidental overwrites. Not a security boundary (see point 1).
- **SHA-256 change detection** against the registered fingerprint, enforced
  before analysis in evidence mode. Not prevention, and not a defence against an
  attacker who also edits the manifest (see points 2 and 4).

Suitable for an air-gapped, NCIIPC-controlled environment.

## Limitations

Stated plainly, because an evidence layer that overstates itself is worse than
one that does not exist.

1. **Locally stored evidence is not physically immutable.** SHA-256
   verification proves that a file matches a digest that was *recorded at some
   point*. It does not make the stored bytes impossible to alter. The owner
   write bit cleared on originals is a handling control against accidental
   overwrites, not a security control, and the same account can restore it.
2. **A privileged filesystem user can change both the evidence and the
   manifest.** `verify()` compares files against the digests in the manifest.
   The manifest is a plain local JSON file: if an attacker can edit *both* the
   evidence and the manifest -- and the manifest is not signed, anchored or
   written to append-only storage -- verification passes against the altered
   bytes. There are no digital signatures, no append-only log, and no external
   anchoring. See point 4 of *What the integrity control actually is*.
3. **No authentication or authorisation.** Anyone with filesystem access can
   read, re-hash, or delete the evidence store. There is no RBAC, no identity,
   and no audit of who accessed the store.
4. **No encryption at rest or in transit.** Evidence is stored as plaintext
   bytes under the local filesystem, using inherited permissions.
5. **Timestamps are host-supplied.** `received_at` and file modification times
   come from the local system clock and are not backed by a trusted timestamp
   authority.
6. **Evidence ID is not globally unique.** It is derived from a one-second
   timestamp and a 12-hex-digit digest prefix. It is unique in practice within
   one workspace; across independent systems it is not a globally unique
   identifier, and it is not a claim about ordering.
7. **ZIP support is a convenience, not a package format.** A submitted ZIP is
   validated and expanded member by member. Nested archives are registered as
   bytes, not recursively expanded.
8. **Content is not validated.** Integrity and provenance do not imply
   completeness, accuracy, or that the evidence is a faithful export of the
   submitter's systems. Only the existing SAT-SA framework, and ultimately the
   human examiner, can assess that.
9. **The evidence layer does not yet reach the dashboard.** The pipeline can
   consume a verified working copy from the command line, but no dashboard or
   report component reads `IntegrityResult` records yet.
10. **Single-file analysis only.** Evidence mode hands exactly one file to the
    analytical pipeline. A ZIP package is registered and verified, but its
    members are not analysed as a set.
11. **Integrity is not bound to a person.** The evidence ID, manifest and
    provenance are not signed, so an evidence record cannot be attributed to a
    named examiner or submitter beyond what the submitter itself supplied.

## How to run the tests

The evidence tests build their own throwaway evidence in pytest temporary
directories. They do not read or write any project dataset, and they do not
touch the real `data/evidence` workspace.

```bash
python -m pytest framework/tests/test_evidence.py -v          # evidence layer
python -m pytest framework/tests/test_evidence_pipeline_integration.py -v
```

To run the full suite, including the existing framework checks:

```bash
python -m pytest framework/tests
```

Demonstrate the layer by hand, without touching the repository datasets:

```bash
python -m framework.evidence.intake /path/to/submission.csv
python -m framework.evidence.intake verify
python -m framework.pipeline --from-evidence SATSA-EV-...
```

Add `--root <dir>` to use a different workspace, `--source-identifier`,
`--assessment-period`, `--submitted-by` to record provenance when the submitter
supplied that information, `--no-extract` to register a ZIP without expanding
it, `--allow-duplicate` to register byte-identical evidence that is already in
the store, and `--json` for a machine-readable record.

## How this supports NCIIPC and audit workflows

- **A defensible starting point.** Every finding produced downstream can be
  traced to a specific evidence ID, a specific digest and a specific
  registration time. That is what makes the finding survivable on challenge.
- **A clear chain of custody.** The provenance record, the preserved original
  and the separated working copy document the path from submission to analysis
  without storing a second copy of sensitive content.
- **Explicit gaps.** Unknown submitters, unknown entity identifiers and unknown
  assessment periods are recorded as unavailable rather than guessed, so the
  record cannot be accused of fabricating provenance.
- **Repeatable verification.** An examiner can re-run verification at any later
  point, including on an archived copy of the evidence store, and get the same
  answer. Verification is a pure function of files plus recorded digests.
- **A controlled, auditable handoff.** The analysis copy is a distinct object
  with a known parent, so "what was analysed" and "what was submitted" are
  separately answerable questions.
- **Air-gapped by design.** No dependency leaves the machine.

## Next steps

Deliberately deferred, in the order that adds the most defensibility per unit
of complexity:

1. Anchor the manifest: sign it, or write it to append-only storage, so that
   limitation 2 above is closed.
2. Add an examiner-facing integrity report and dashboard panel that consumes
   `IntegrityResult` records directly.
3. Record an explicit analysis event in the provenance chain-of-custody when a
   pipeline run consumes a working copy.

Explicitly not planned without a separate requirement: authentication, RBAC,
key management, PKI, blockchain, distributed storage, SIEM integration,
real-time monitoring, ML changes, new supervisory rules, or report redesign.
