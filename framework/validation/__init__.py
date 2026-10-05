"""Observer-only validation framework for the existing SAT-SA signals.

This package compares human manual review against SAT-SA output. It adds no
analytics. It reads the existing pipeline result and the existing human review
template, and it writes comparison artefacts to disk. It never imports a
detector in order to change how detection works, and it never writes to any
existing result key.

The single most important rule in this package: an *expert* label is one a real
human reviewer entered after independently inspecting the submitted data. This
package can ship an empty template for that purpose, and it can ship controlled
expectations written from the raw data for software testing, but it must never
present either as expert ground truth.
"""

from framework.validation.corpus import (
    CORPUS_PATH,
    ValidationCase,
    load_corpus,
)
from framework.validation.schema import (
    HUMAN_FIELDS,
    REVIEW_TEMPLATE_PATH,
    build_review_template,
    load_review,
    validate_review,
)

__all__ = [
    "CORPUS_PATH",
    "REVIEW_TEMPLATE_PATH",
    "HUMAN_FIELDS",
    "ValidationCase",
    "build_review_template",
    "load_corpus",
    "load_review",
    "validate_review",
]
