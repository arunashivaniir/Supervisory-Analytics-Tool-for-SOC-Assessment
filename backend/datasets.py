"""Filesystem access for the local adapter.

The adapter is allowed to know which files exist. It is not allowed to know
what any of them mean. Dataset discovery is a directory listing, nothing
more: no filename is special-cased, ranked or preferred, because the moment
this module recognises a dataset it becomes a second source of analytical
truth.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

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


def list_datasets(root: Optional[str] = None) -> List[Dict[str, Any]]:
    """Every readable dataset file in the repository, unsorted by meaning.

    Returned with a stable lexicographic order purely so the list does not
    shuffle between requests. Ordering carries no significance and no file
    is listed first for any reason other than its name.
    """

    base = root or repository_root()
    found: List[Dict[str, Any]] = []

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

            found.append(
                {
                    "path": relative,
                    "filename": filename,
                    "directory": _relative(base, directory),
                    "size_bytes": os.path.getsize(absolute),
                    "modified": os.path.getmtime(absolute),
                }
            )

    found.sort(key=lambda item: item["path"])

    return found


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
