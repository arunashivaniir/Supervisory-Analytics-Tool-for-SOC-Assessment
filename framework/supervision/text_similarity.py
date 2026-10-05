"""Text similarity utilities for operational pattern and anomaly detection.

Shared tokenisation and Jaccard similarity functions to avoid circular
imports between operational_pattern_detector, feature_builder and minhash_lsh.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence, Set

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _tokenise(value: Any) -> Optional[Set[str]]:
    """Reduce submitted text to a comparable set of lowercase tokens.

    Token *sets* are used rather than counts so that reordering or repeating
    words does not by itself break similarity, and so no submitted text is
    retained beyond the set of words used for the comparison.
    """

    if not isinstance(value, str):
        return None

    tokens = _TOKEN_PATTERN.findall(value.lower())

    if not tokens:
        return None

    return frozenset(tokens)


def _jaccard(left: Set[str], right: Set[str]) -> float:
    union = left | right

    if not union:
        return 0.0

    return len(left & right) / len(union)