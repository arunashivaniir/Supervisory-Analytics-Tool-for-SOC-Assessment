# SAT-SA Validation Framework

An **observer** of the existing SAT-SA system. It compares human manual review
against SAT-SA output for the three existing supervisory signal families:

- execution gap
- negative space
- operational pattern

It adds **no analytics**. It introduces no rule, no threshold, no score, no ML,
no network dependency, and no new pipeline result key. It reads the existing
pipeline result and the existing human review template, and writes its own
artefacts to disk.

---

## The one rule that matters

**Expert labels must come from a real human reviewer.**

This package ships two things that are *not* expert labels, and never presents
them as such:

| Artefact | What it is | What it is not |
|---|---|---|
| `human_review_template.json` | An **empty** form. Every human field is blank. | Not a review. Nothing has been judged. |
| `corpus.json` `controlled_expectation` | Design intent written by the framework author from the raw source rows. Exists so the comparison machinery can be exercised in software tests. | **Not expert ground truth.** Must never be described as such. |

Until a human reviewer completes the template and it is locked, the report says
**"Expert validation pending."** and classifies the run as *controlled
validation* rather than *expert validation*.

---

## Blind workflow

The order matters. A reviewer must not see SAT-SA output before forming their
own conclusion, or the comparison measures anchoring rather than agreement.

> **The reviewer should complete this file BEFORE seeing SAT-SA results.**
> `human_review_template.json` is the file referred to. If a reviewer has
> already seen a `sat_sa_reference_output.json`, a `validation_report.txt`, or
> any pipeline console output for these same 20 cases, the review is no longer
> blind and the resulting agreement figures must be reported as unblinded.

```bash
# STEP 1 — give the reviewer the cases.
#         They inspect the raw submitted data named in each record's
#         `dataset` column and complete the template.
python -m framework.validation template

# STEP 2 — the reviewer completes the template. Nothing else is run until
#         they are finished, because running it early is what breaks the
#         blind comparison.

# STEP 3 — only now, produce SAT-SA output.
python -m framework.validation reference

# STEP 4 — compare the locked review against the reference output.
python -m framework.validation compare

# STEP 5 — the report is written by `compare`.
cat framework/validation/output/validation_report.txt
```

Generate the empty template first:

```bash
python -m framework.validation template
```

> `python -m framework.validation all` runs every step in one command. It exists
> for convenience and for tests. It is **not** the recommended workflow,
> because it produces reference output immediately.

`compare` refuses to run if the template is missing or malformed, and prints a
notice when the template contains no human labels, so a controlled run can never
be mistaken for a validated one.

---

## Artefacts

All written to `framework/validation/output/`:

| File | Produced by | Contents |
|---|---|---|
| `human_review_template.json` | `template` | Empty form, one record per case. |
| `sat_sa_reference_output.json` | `reference` | Verbatim slice of existing result payloads, per case. |
| `validation_comparison.json` | `compare` | Per-indicator outcomes with evidence reports. |
| `validation_metrics.json` | `compare` | Per-family metrics. |
| `validation_report.txt` | `compare` / `report` | The report. |

---

## What the reviewer fills in

`case_id`, `assessment_id`, `entity` and `period` are pre-filled because they
are facts about the corpus, not opinions. Everything else starts empty:

```
human_execution_gap             indicators observed, per family
human_negative_space
human_operational_pattern
human_indicators                every indicator observed, all families
human_evidence_reference        which submitted records support it
human_reason                    their reasoning, in their own words
human_confidence                HIGH | MEDIUM | LOW | UNSURE
supervisory_dashboard_difficulty   YES | NO | UNCERTAIN
supervisory_review_rationale    why would a supervisor review this?
reviewer_id
review_timestamp
```

An empty field means *not assessed*. It is **not** a negative finding. A
reviewer who looked and found nothing records an empty list plus a confidence
value, which is why "no labels yet" is a checkable fact rather than an
assumption.

---

## Comparison methodology

Comparison is per **indicator**, per **family**, per **assessment scope**.

Scope is part of a signal's identity. An indicator reported for the right reason
against the wrong entity or the wrong period is a **scope mismatch**, never a
match. This is checked across the whole corpus, not case by case, so a signal
that moved between scopes is caught even when each case looks correct in
isolation.

| Outcome | Meaning |
|---|---|
| `MATCH` | Both sides reported the indicator for the same scope, and the evidence check supported it. |
| `MATCH_UNSUPPORTED` | Both sides reported it, but the evidence did not check out. **Not** counted as a validated match. |
| `SCOPE_MISMATCH` | Both sides reported it, for different scopes. |
| `FALSE_POSITIVE` | SAT-SA reported it; the reviewer did not. |
| `FALSE_NEGATIVE` | The reviewer reported it; SAT-SA did not. |

**Free text is never compared by string equality.** A human and a tool will
never phrase a reason identically, and pretending otherwise would measure
wording rather than agreement. Explanations are carried through separately so
both remain reviewable, and the report records only whether an explanation was
present.

### Scope identity is `dataset` + `assessment_id`

An assessment id is only unique inside its own dataset. Two datasets in this
repository both contain a `CSE-A01::Period-2` scope, so scope keys carry the
dataset too.

---

## Evidence agreement

For every matched indicator, SAT-SA's evidence is checked against the submitted
source rows and the system's own semantic mapping:

1. **Traceability** — does the finding name records that exist inside its scope?
2. **Record-level support** — do the cited rows carry the values the finding
   claims as evidence?
3. **Arithmetic consistency** — do the finding's own numbers agree with each
   other and with the rows?

Outcomes are `SUPPORTED`, `PARTIALLY_SUPPORTED`, `UNSUPPORTED` and
`NOT_VERIFIABLE`. Only `SUPPORTED` counts as a validated match. A finding that
cites nothing checkable is `NOT_VERIFIABLE`, not supported: **silence is not
agreement.**

This does **not** re-run detection logic. Re-deriving a verdict would be new
analytics, and a re-derivation that agreed with itself would prove nothing.

### Concept collisions

The evidence checker reports any concept fed by more than one source column.
Where that happens, a finding's evidence value for the concept is ambiguous
unless the columns agree. This is currently true for
`dataset_capability_rich.csv`, where both `priority` and `asset_criticality`
map onto `SECURITY_SEVERITY`. Such findings need human reading rather than
automatic acceptance.

---

## Metrics

Reported **per family**, never as a single accuracy score:

- true positives, false positives, false negatives
- matches with unsupported evidence
- scope mismatches
- precision, recall

Plus: total cases, cases where SAT-SA declined to judge, and evidence
traceability status.

`NOT_EVALUABLE` is counted separately from "judged and found nothing", because
conflating them would let a layer that says nothing on small scopes score as
agreeing with a reviewer who also saw nothing.

With no human labels, precision and recall are reported as **not computable**
rather than as `0.0`. Reporting `0.0` from an empty review would be a false
statement about SAT-SA rather than a statement about the missing labels.

The supervisory-value question (`YES` / `NO` / `UNCERTAIN`) is counted but never
scored numerically. It is supporting evidence for a novelty argument, not an
accuracy metric.

---

## Corpus

`corpus.json` defines 20 assessment cases drawn from **4 datasets that already
exist in the repository**. No new dataset is created, and no existing dataset is
modified.

All 14 required case types are covered: clear execution gap, valid execution,
missing evidence, clear negative space, complete evidence, partial evidence,
clear operational concentration, normal distribution, repetitive investigation
evidence, normal investigation evidence, insufficient observations, mixed-signal
case, multi-CSE isolation and multi-period isolation.

No case depends on a hidden threshold. Every controlled expectation names the raw
rows it was read from, so a reviewer can check it against the same data.

---

## Tests

```bash
python -m pytest framework/tests/test_validation.py -v
```

Covers the schema, normalisation, exact match, false positive, false negative,
scope mismatch, evidence mismatch, `NOT_EVALUABLE` handling, all three family
comparisons, multi-CSE and multi-period isolation, the empty template, the
absence of fabricated labels, and pipeline regression.

---

## Adding an expert review

1. `python -m framework.validation template`
2. Fill in the human fields in
   `framework/validation/output/human_review_template.json`.
3. `python -m framework.validation reference`
4. `python -m framework.validation compare`

The report will then classify the run as expert validation instead of controlled
validation. `write_review_template` refuses to overwrite a template that already
contains reviewer input.
