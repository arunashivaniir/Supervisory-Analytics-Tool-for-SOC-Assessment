"""Command line for the validation framework.

Subcommands, in the order the blind workflow requires:

  template   write an empty human review template
  reference  run SAT-SA and write the reference output
  compare    compare the locked review against the reference output
  report     render the validation report

The ordering is enforced in one place only, ``require_locked_review``, so a
reviewer cannot accidentally see tool output first.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from typing import Any, Dict, List, Mapping, Optional

from framework.validation.compare import compare
from framework.validation.corpus import (
    dataset_path,
    load_corpus,
)
from framework.validation.metrics import compute_metrics
from framework.validation.reference import (
    build_reference,
    write_reference,
)
from framework.validation.report import build_report, write_report
from framework.validation.schema import (
    REVIEW_TEMPLATE_PATH,
    has_any_expert_label,
    load_review,
    validate_review,
    write_review_template,
)

DEFAULT_OUTPUT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "output"
)


def _paths(args) -> Dict[str, str]:
    directory = args.output_dir

    return {
        "template": os.path.join(directory, "human_review_template.json"),
        "reference": os.path.join(directory, "sat_sa_reference_output.json"),
        "comparison": os.path.join(directory, "validation_comparison.json"),
        "metrics": os.path.join(directory, "validation_metrics.json"),
        "report": os.path.join(directory, "validation_report.txt"),
    }


def _write_json(payload: Any, path: str) -> None:
    directory = os.path.dirname(os.path.abspath(path))

    if directory:
        os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _load_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _pipelines_for(cases) -> Dict[str, Mapping[str, Any]]:
    """Run each distinct dataset once, keeping the raw results for evidence checks."""

    from framework.pipeline import SATSAPipeline

    pipelines: Dict[str, Mapping[str, Any]] = {}

    for dataset in sorted({case.dataset for case in cases}):
        with contextlib.redirect_stdout(io.StringIO()):
            pipelines[dataset] = SATSAPipeline().run(dataset_path(dataset))

    return pipelines


def command_template(args) -> int:
    cases = load_corpus()
    paths = _paths(args)

    write_review_template(paths["template"], cases)

    print(f"[+] empty human review template written: {paths['template']}")
    print(f"    {len(cases)} cases, every human field blank")
    print("    complete this BEFORE running the reference step")

    return 0


def command_reference(args) -> int:
    cases = load_corpus()
    paths = _paths(args)

    reference = build_reference(cases)

    write_reference(reference, paths["reference"])

    print(f"[+] SAT-SA reference output written: {paths['reference']}")
    print(f"    {reference['case_count']} cases across "
          f"{len(reference['datasets'])} datasets")

    collisions = reference.get("concept_collisions") or []

    for observation in collisions:
        for concept, columns in sorted(observation["collisions"].items()):
            print(
                f"    note: {observation['dataset']} maps "
                f"{', '.join(columns)} onto {concept}"
            )

    return 0


def require_locked_review(path: str) -> Mapping[str, Any]:
    """Load a review and refuse to continue if it looks mid-edit.

    This is the blind-comparison guard. It does not check that a review is
    correct, only that it is in a state a reviewer could have finished.
    """

    if not os.path.isfile(path):
        raise SystemExit(
            f"no human review found at {path}\n"
            "run the template step and complete the review first"
        )

    review = load_review(path)

    problems = validate_review(review)

    if problems:
        for problem in problems:
            print(f"[!] {problem}", file=sys.stderr)

        raise SystemExit("human review template failed validation")

    if not has_any_expert_label(review):
        print(
            "[i] the review contains no human labels, so this run is a"
            " controlled self-consistency check, not expert validation"
        )

    return review


def command_compare(args) -> int:
    cases = load_corpus()
    paths = _paths(args)

    review = require_locked_review(paths["template"])

    if not os.path.isfile(paths["reference"]):
        raise SystemExit(
            f"no reference output found at {paths['reference']}\n"
            "run the reference step after the review is locked"
        )

    reference = _load_json(paths["reference"])
    pipelines = _pipelines_for(cases)

    comparison = compare(cases, review, reference, pipelines)

    # The supervisory-value answers belong to the reviewer, so they travel from
    # the review into the metrics rather than being recomputed.
    comparison["supervisory_responses"] = _supervisory_responses(review)

    metrics = compute_metrics(comparison)

    _write_json(comparison, paths["comparison"])
    _write_json(metrics, paths["metrics"])

    report = build_report(cases, comparison, metrics, reference)

    write_report(report, paths["report"])

    print(f"[+] comparison written: {paths['comparison']}")
    print(f"[+] metrics written:    {paths['metrics']}")
    print(f"[+] report written:     {paths['report']}")

    if not metrics.get("expert_labelled"):
        print("[i] Expert validation pending.")

    return 0


def _supervisory_responses(review: Mapping[str, Any]) -> Dict[str, int]:
    counts: Dict[str, int] = {}

    for record in review.get("records", ()):
        answer = record.get("supervisory_dashboard_difficulty")

        if answer:
            counts[answer] = counts.get(answer, 0) + 1

    return counts


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m framework.validation",
        description="Observer-only validation framework for existing "
        "SAT-SA signals. Adds no analytics.",
    )
    parser.add_argument(
        "--output-dir", default=DEFAULT_OUTPUT_DIR,
        help="directory for generated artefacts",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("template", help="write an empty human review template")
    sub.add_parser("reference", help="run SAT-SA and write reference output")
    sub.add_parser("compare", help="compare a locked review against SAT-SA")
    sub.add_parser("report", help="render the report from existing artefacts")
    sub.add_parser(
        "all",
        help="template, reference, compare and report in one run. Provided "
        "for convenience only; it is not the recommended blind workflow, "
        "because it generates reference output immediately.",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "template":
        return command_template(args)

    if args.command == "reference":
        return command_reference(args)

    if args.command == "compare":
        return command_compare(args)

    if args.command == "all":
        command_template(args)
        command_reference(args)
        return command_compare(args)

    if args.command == "report":
        cases = load_corpus()
        paths = _paths(args)

        comparison = _load_json(paths["comparison"])
        metrics = _load_json(paths["metrics"])

        reference = (
            _load_json(paths["reference"])
            if os.path.isfile(paths["reference"])
            else None
        )

        report = build_report(cases, comparison, metrics, reference)

        write_report(report, paths["report"])

        print(f"[+] report written: {paths['report']}")

        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
