"""Filesystem access for the local adapter.

The adapter is allowed to know which files exist. It is not allowed to know
what any of them mean. Dataset discovery is a directory listing, nothing
more: no filename is special-cased, ranked or preferred, because the moment
this module recognises a dataset it becomes a second source of analytical
truth.

One deliberate exception exists, and it is about presentation rather than
meaning: ``DEMO_ALLOWLIST`` plus ``SATSA_DATASET_MODE=demo`` narrows the
listing to a curated set for a demonstration. That switch changes which
files are *offered*; it does not rank them, does not reorder them, does not
describe them, and is not consulted by preview, analysis, mapping or
validation. A dataset the allowlist names is analysed by exactly the same
pipeline as one discovered by a directory walk, and a dataset it omits stays
in the repository and remains reachable through ``resolve_dataset``. Demo
mode is off unless it is switched on, so the default listing is unchanged.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, Iterable, List, Optional, Tuple

#: Extensions the ingestion layer can actually open. Used only to keep the
#: picker from offering the adapter its own output directories.
DATASET_SUFFIXES = (".csv",)

#: Directories that never contain submitted evidence. Skipping them is a
#: statement about the repository layout, not about any dataset.
#:
#: ``data/evidence`` and ``data/generated`` are deliberately absent. Both hold
#: real evidence files: the first is where evidence-mode submissions live, and
#: the interface must be able to open them the way it opens any other file. The
#: names here are compared one path segment at a time, so each entry is a
#: single directory name.
EXCLUDED_DIRECTORIES = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "artifacts",
    "build",
    "dist",
    "frontend",
    "node_modules",
    "venv",
}

#: The two listing modes. ``full`` is a directory walk; ``demo`` is this
#: allowlist. Named rather than implied so a configuration mistake can be
#: reported instead of silently falling back to a full walk.
MODE_FULL = "full"
MODE_DEMO = "demo"
DATASET_MODES = (MODE_FULL, MODE_DEMO)

#: Datasets curated for a demonstration, as repository-relative paths.
#:
#: Each entry was admitted by running the real preview against it and keeping
#: only datasets whose preview settles with a detected role (not UNKNOWN), zero
#: validation errors, and enough canonical concepts mapped to be worth
#: analysing. Nothing here is a statement about what the file contains beyond
#: that preview: the values below are the evidence for admission, recorded so a
#: later change can be re-checked rather than re-argued.
#:
#:   soc_asset_inventory_q3_2026.csv    ASSETS 0.60   E0 W1    4 of 16 concepts
#:   splunk_style_soc_alerts_q3_2026.csv ASSETS 0.60   E0 W2   10 of 26 concepts
#:
#: Deliberately not admitted, each because its own preview fails one of the
#: criteria above rather than because of what it is called:
#:
#:   SAT-SA_demo_Q3_2026.csv            UNKNOWN 0.00, E0 W0
#:       "No role anchor with supporting concepts was found." Offering it would
#:       put a dataset the interface cannot assess in front of the examiner.
#:   servicenow_style_secops_cases_q3_2026.csv
#:       ALERTS 0.38, E1 (DUPLICATE_ALERT_ID: 'alert_id' repeats 6,296 times).
#:       Offering it would put a dataset the interface refuses to run in front
#:       of the examiner.
#:   servicenow_style_workflow_events_q3_2026.csv
#:       CASES 0.30, E1.
#:   data/demo/incident_event_log.csv   46 MB.
#:   validation/unsw/*                  validation corpora, not submissions.
#:
#: Everything omitted above is still in the repository, still listed in full
#: mode, and still analysable: this is a curated picker, not a delete.
DEMO_ALLOWLIST = (
    "soc_asset_inventory_q3_2026.csv",
    "splunk_style_soc_alerts_q3_2026.csv",
)


def repository_root() -> str:
    """Absolute path to the repository root.

    Packaging override: when ``SATSA_DATA_ROOT`` is set, it names the
    runtime data directory instead (datasets, evidence, exports). A
    frozen executable sets it to the directory beside the executable
    unless the user already set it. Unset, this behaves exactly as
    before, so normal development is untouched.
    """

    override = os.environ.get("SATSA_DATA_ROOT")

    if override:
        return os.path.abspath(override)

    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))

    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def bundle_root() -> str:
    """Absolute path to the bundled read-only resources.

    In a frozen executable this is the bundle directory (``sys._MEIPASS``)
    holding the frontend build and framework configs; in development it is
    the repository root. Used only to locate files shipped with the
    application, never user data.
    """

    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)

        if meipass:
            return os.path.abspath(meipass)

        return os.path.dirname(os.path.abspath(sys.executable))

    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _relative(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def is_excluded(relative_path: str) -> bool:
    """True when a repository-relative path is not offered as evidence."""

    parts = relative_path.split("/")

    if any(part in EXCLUDED_DIRECTORIES for part in parts[:-1]):
        return True

    for part in parts:
        if part in EXCLUDED_DIRECTORIES:
            return True

    return False


def dataset_mode() -> str:
    """The listing mode this process is configured for.

    ``SATSA_DATASET_MODE`` selects it: ``demo`` narrows the listing to the
    curated allowlist, ``full`` (the default, and what an unset or empty
    variable means) walks the repository as before. Anything else is a
    configuration error and is reported as one, because quietly falling back
    to a full walk would put every test and validation dataset back in front
    of a demonstration.
    """

    raw = os.environ.get("SATSA_DATASET_MODE")

    if raw is None or not raw.strip():
        return MODE_FULL

    mode = raw.strip().lower()

    if mode not in DATASET_MODES:
        raise ValueError(
            "SATSA_DATASET_MODE must be one of %s, not %r"
            % (", ".join(DATASET_MODES), raw)
        )

    return mode


def demo_allowlist() -> Tuple[str, ...]:
    """The curated dataset paths demo mode offers.

    ``SATSA_DEMO_DATASETS`` replaces :data:`DEMO_ALLOWLIST` with its own
    comma-separated repository-relative paths, so a demonstration can be
    pointed at a different set without editing this module. The variable is
    read here and nowhere else, and it only ever decides what is listed: an
    allowlisted dataset is previewed and analysed exactly as a discovered one.
    """

    override = os.environ.get("SATSA_DEMO_DATASETS")

    if override is None:
        return DEMO_ALLOWLIST

    paths = tuple(
        part.strip().replace("\\", "/")
        for part in override.split(",")
        if part.strip()
    )

    return paths


def _describe(root: str, relative: str) -> Dict[str, Any]:
    """One listing entry, described the same way in both modes."""

    absolute = os.path.join(root, relative.replace("/", os.sep))

    return {
        "path": relative,
        "filename": relative.split("/")[-1],
        "directory": _relative(root, os.path.dirname(absolute)) or ".",
        "size_bytes": os.path.getsize(absolute),
        "modified": os.path.getmtime(absolute),
    }


def curated_datasets(
    allowlist: Optional[Iterable[str]] = None,
    root: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The allowlisted datasets that exist, and the ones that do not.

    ``found`` is lexicographic like every other listing this module produces,
    so the allowlist's order is not a ranking: a curated dataset never appears
    above another because of where it sits in the configuration.

    ``missing`` is reported rather than silently dropped, so a demonstration
    whose curated set is incomplete says so instead of quietly offering a
    smaller picker.
    """

    base = os.path.abspath(root or repository_root())
    wanted = list(allowlist if allowlist is not None else demo_allowlist())

    found: List[Dict[str, Any]] = []
    missing: List[str] = []

    for relative in wanted:
        absolute = os.path.join(base, relative.replace("/", os.sep))

        if is_excluded(relative) or not os.path.isfile(absolute):
            missing.append(relative)
            continue

        found.append(_describe(base, relative))

    found.sort(key=lambda item: item["path"])

    return found, missing


def list_datasets(
    root: Optional[str] = None,
    mode: Optional[str] = None,
    allowlist: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Every readable dataset file offered for analysis, unsorted by meaning.

    Returned with a stable lexicographic order purely so the list does not
    shuffle between requests. Ordering carries no significance and no file
    is listed first for any reason other than its name.

    ``mode`` and ``allowlist`` exist so a caller (and a test) can state which
    listing it wants; both default to this process's configuration, which
    defaults to a full directory walk.
    """

    base = root or repository_root()
    effective = dataset_mode() if mode is None else mode

    if effective not in DATASET_MODES:
        raise ValueError(
            "dataset mode must be one of %s, not %r"
            % (", ".join(DATASET_MODES), effective)
        )

    if effective == MODE_DEMO:
        found, _missing = curated_datasets(allowlist=allowlist, root=base)

        return found

    found_all: List[Dict[str, Any]] = []

    for directory, subdirectories, filenames in os.walk(base):
        subdirectories[:] = [
            name for name in subdirectories if name not in EXCLUDED_DIRECTORIES
        ]

        for filename in filenames:
            if not filename.lower().endswith(DATASET_SUFFIXES):
                continue

            absolute = os.path.join(directory, filename)
            relative = _relative(base, absolute)

            if is_excluded(relative):
                continue

            found_all.append(_describe(base, relative))

    found_all.sort(key=lambda item: item["path"])

    return found_all


def resolve_dataset(path: str, root: Optional[str] = None) -> str:
    """Turn a repository-relative path into an absolute one.

    The containment check keeps the adapter from being used as a general file
    reader. It is a path safety check, not a dataset policy.
    """

    base = os.path.abspath(root or repository_root())
    absolute = os.path.abspath(os.path.join(base, path))

    if absolute != base and not absolute.startswith(base + os.sep):
        raise ValueError("path resolves outside the repository")

    if not os.path.isfile(absolute):
        raise FileNotFoundError(path)

    return absolute
