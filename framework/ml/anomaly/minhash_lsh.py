"""Optimized similarity search for high-threshold Jaccard.

Combines exact deduplication with MinHash LSH for near-duplicates.
Designed for thresholds >= 0.8 where data has many identical records.
"""

from __future__ import annotations

import random
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from framework.supervision.text_similarity import _tokenise, _jaccard


DEFAULT_NUM_PERM = 256
DEFAULT_THRESHOLD = 0.8
DEFAULT_L = 32


class MinHash:
    """MinHash signature for a token set."""

    __slots__ = ("hashvalues", "num_perm", "seed")

    def __init__(
        self,
        num_perm: int = DEFAULT_NUM_PERM,
        seed: int = 42,
        hashvalues: Optional[List[int]] = None,
    ) -> None:
        self.num_perm = num_perm
        self.seed = seed
        if hashvalues is not None:
            self.hashvalues = hashvalues
        else:
            self.hashvalues = [2**32 - 1] * num_perm

    @classmethod
    def from_tokens(
        cls, tokens: Sequence[str], num_perm: int = DEFAULT_NUM_PERM, seed: int = 42
    ) -> "MinHash":
        mh = cls(num_perm=num_perm, seed=seed)
        mh.update(tokens)
        return mh

    def update(self, tokens: Sequence[str]) -> None:
        rng = random.Random(self.seed)
        permutations = [(rng.randint(1, 2**32 - 1), rng.randint(0, 2**32 - 1)) for _ in range(self.num_perm)]

        for token in tokens:
            h = hash(token) & 0xFFFFFFFF
            for i, (a, b) in enumerate(permutations):
                permuted = (a * h + b) & 0xFFFFFFFF
                if permuted < self.hashvalues[i]:
                    self.hashvalues[i] = permuted

    def jaccard(self, other: "MinHash") -> float:
        if self.num_perm != other.num_perm:
            raise ValueError("MinHash objects must have the same num_perm")
        matches = sum(1 for a, b in zip(self.hashvalues, other.hashvalues) if a == b)
        return matches / self.num_perm

    def get_signature(self) -> List[int]:
        return self.hashvalues[:]


class MinHashLSH:
    """LSH index for MinHash signatures using banding."""

    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        num_perm: int = DEFAULT_NUM_PERM,
        l: int = DEFAULT_L,
    ) -> None:
        self.threshold = threshold
        self.num_perm = num_perm
        self.l = l
        self.k = max(1, num_perm // l)
        self._tables: List[Dict[Tuple[int, ...], List[int]]] = [{} for _ in range(l)]

    def _get_band_hash(self, hashvalues: List[int], band: int) -> Tuple[int, ...]:
        start = band * self.k
        end = min(start + self.k, self.num_perm)
        return tuple(hashvalues[start:end])

    def insert(self, index: int, minhash: MinHash) -> None:
        for band in range(self.l):
            band_hash = self._get_band_hash(minhash.hashvalues, band)
            if band_hash not in self._tables[band]:
                self._tables[band][band_hash] = []
            self._tables[band][band_hash].append(index)

    def query(self, minhash: MinHash) -> Set[int]:
        candidates: Set[int] = set()
        for band in range(self.l):
            band_hash = self._get_band_hash(minhash.hashvalues, band)
            if band_hash in self._tables[band]:
                candidates.update(self._tables[band][band_hash])
        return candidates


def _deduplicate_exact(
    token_sets: Sequence[Optional[Set[str]]],
) -> Tuple[List[Optional[Set[str]]], Dict[int, List[int]]]:
    """Group identical token sets. Returns (unique_token_sets, index_map)."""
    seen: Dict[frozenset, int] = {}
    unique: List[Optional[Set[str]]] = []
    index_map: Dict[int, List[int]] = defaultdict(list)

    for i, tokens in enumerate(token_sets):
        if tokens is None:
            unique.append(None)
            index_map[len(unique) - 1].append(i)
            continue

        key = frozenset(tokens)
        if key in seen:
            idx = seen[key]
            index_map[idx].append(i)
        else:
            idx = len(unique)
            seen[key] = idx
            unique.append(tokens)
            index_map[idx].append(i)

    return unique, dict(index_map)


def find_connected_components_minhash(
    token_sets: Sequence[Optional[Set[str]]],
    threshold: float = DEFAULT_THRESHOLD,
    num_perm: int = DEFAULT_NUM_PERM,
    exact_jaccard_fn=None,
) -> List[List[int]]:
    """Find connected components of mutual similarity using exact deduplication + MinHash LSH.

    Returns list of components, each a list of original indices.
    """
    if exact_jaccard_fn is None:
        exact_jaccard_fn = _jaccard

    n = len(token_sets)

    # Step 1: Exact deduplication - identical token sets form initial components
    unique_token_sets, index_map = _deduplicate_exact(token_sets)

    if len(unique_token_sets) <= 1:
        # All None or all identical
        result = []
        for idx, orig_indices in index_map.items():
            if orig_indices:
                result.append(orig_indices)
        return result

    # Step 2: Build union-find on unique token sets
    num_unique = len(unique_token_sets)
    parent = list(range(num_unique))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[max(root_left, root_right)] = min(root_left, root_right)

    # Each unique token set starts as its own component
    # Exact duplicates already grouped in index_map

    # Step 3: MinHash LSH on unique token sets to find cross-group connections
    minhashes: List[Optional[MinHash]] = []
    for tokens in unique_token_sets:
        if tokens is None or len(tokens) == 0:
            minhashes.append(None)
        else:
            minhashes.append(MinHash.from_tokens(tokens, num_perm=num_perm))

    # Use k=1 for high-threshold search
    l = min(num_perm, 64)
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm, l=l)

    for i, mh in enumerate(minhashes):
        if mh is not None:
            lsh.insert(i, mh)

    # Query and union
    seen_pairs: Set[Tuple[int, int]] = set()

    for i, mh in enumerate(minhashes):
        if mh is None:
            continue
        candidates = lsh.query(mh)
        for j in candidates:
            if j <= i:
                continue
            key = (i, j)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            if minhashes[j] is None:
                continue

            if unique_token_sets[i] is None or unique_token_sets[j] is None:
                continue
            sim = exact_jaccard_fn(unique_token_sets[i], unique_token_sets[j])
            if sim >= threshold:
                union(i, j)

    # Step 4: Build components from union-find on unique indices
    unique_components: Dict[int, List[int]] = defaultdict(list)
    for i in range(num_unique):
        if unique_token_sets[i] is not None:
            unique_components[find(i)].append(i)

    # Step 5: Expand to original indices
    result: List[List[int]] = []
    for comp_unique_indices in unique_components.values():
        component: List[int] = []
        for u_idx in comp_unique_indices:
            component.extend(index_map[u_idx])
        if component:
            result.append(component)

    return result


def find_similar_pairs_minhash(
    token_sets: Sequence[Optional[Set[str]]],
    threshold: float = DEFAULT_THRESHOLD,
    num_perm: int = DEFAULT_NUM_PERM,
    exact_jaccard_fn=None,
) -> List[Tuple[int, int, float]]:
    """Find all pairs with Jaccard similarity >= threshold.

    Uses exact deduplication + MinHash LSH for sub-quadratic search.
    Returns list of (i, j, similarity) where i < j.
    """
    if exact_jaccard_fn is None:
        exact_jaccard_fn = _jaccard

    n = len(token_sets)

    # Step 1: Exact deduplication - identical token sets get similarity 1.0
    unique_token_sets, index_map = _deduplicate_exact(token_sets)

    pairs: List[Tuple[int, int, float]] = []

    # Add pairs from exact duplicates (similarity = 1.0)
    for idx, original_indices in index_map.items():
        if len(original_indices) > 1:
            for i in range(len(original_indices)):
                for j in range(i + 1, len(original_indices)):
                    pairs.append((original_indices[i], original_indices[j], 1.0))

    # Step 2: MinHash LSH on unique token sets
    if len(unique_token_sets) <= 1:
        return pairs

    # Build MinHash for unique sets
    minhashes: List[Optional[MinHash]] = []
    for tokens in unique_token_sets:
        if tokens is None or len(tokens) == 0:
            minhashes.append(None)
        else:
            minhashes.append(MinHash.from_tokens(tokens, num_perm=num_perm))

    # LSH with k=1 for high-threshold search (each hash is a band)
    # This gives P = 1 - (1 - s)^l, which is selective for high s
    l = min(num_perm, 64)  # Use up to 64 bands
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm, l=l)

    for i, mh in enumerate(minhashes):
        if mh is not None:
            lsh.insert(i, mh)

    # Query and verify
    seen_pairs: Set[Tuple[int, int]] = set()

    for i, mh in enumerate(minhashes):
        if mh is None:
            continue
        candidates = lsh.query(mh)
        for j in candidates:
            if j <= i:
                continue
            key = (i, j)
            if key in seen_pairs:
                continue
            seen_pairs.add(key)

            if minhashes[j] is None:
                continue

            # Verify with exact Jaccard
            if unique_token_sets[i] is None or unique_token_sets[j] is None:
                continue
            sim = exact_jaccard_fn(unique_token_sets[i], unique_token_sets[j])
            if sim >= threshold:
                # Expand to original indices
                for orig_i in index_map[i]:
                    for orig_j in index_map[j]:
                        if orig_i < orig_j:
                            pairs.append((orig_i, orig_j, sim))

    return pairs


def find_max_similarities_minhash(
    token_sets: Sequence[Optional[Set[str]]],
    num_perm: int = DEFAULT_NUM_PERM,
    exact_jaccard_fn=None,
) -> List[float]:
    """Find max Jaccard similarity for each token set against all others.

    Returns list of max similarities (0.0 for records with no tokens or no
    other records to compare against).
    """
    if exact_jaccard_fn is None:
        exact_jaccard_fn = _jaccard

    n = len(token_sets)

    # Step 1: Exact deduplication
    unique_token_sets, index_map = _deduplicate_exact(token_sets)

    if len(unique_token_sets) <= 1:
        return [0.0] * n

    # Build MinHash for unique sets
    minhashes: List[Optional[MinHash]] = []
    for tokens in unique_token_sets:
        if tokens is None or len(tokens) == 0:
            minhashes.append(None)
        else:
            minhashes.append(MinHash.from_tokens(tokens, num_perm=num_perm))

    # LSH with k=1 for high-threshold
    l = min(num_perm, 64)
    lsh = MinHashLSH(threshold=0.0, num_perm=num_perm, l=l)

    for i, mh in enumerate(minhashes):
        if mh is not None:
            lsh.insert(i, mh)

    max_sims: List[float] = [0.0] * n

    for i, mh in enumerate(minhashes):
        if mh is None:
            continue

        best = 0.0
        # Check exact duplicates first (similarity = 1.0)
        if len(index_map[i]) > 1:
            best = 1.0

        candidates = lsh.query(mh)
        for j in candidates:
            if j == i:
                continue
            if minhashes[j] is None:
                continue
            if unique_token_sets[i] is None or unique_token_sets[j] is None:
                continue
            sim = exact_jaccard_fn(unique_token_sets[i], unique_token_sets[j])
            if sim > best:
                best = sim

        # Propagate to all original indices
        for orig_i in index_map[i]:
            max_sims[orig_i] = best

    return max_sims


def build_minhash_index(
    token_sets: Sequence[Optional[Set[str]]],
    threshold: float = DEFAULT_THRESHOLD,
    num_perm: int = DEFAULT_NUM_PERM,
) -> Tuple[List[Optional[MinHash]], MinHashLSH]:
    """Build MinHash signatures and LSH index for a sequence of token sets."""
    minhashes: List[Optional[MinHash]] = []
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm, l=min(num_perm, 64))

    for i, tokens in enumerate(token_sets):
        if tokens is None or len(tokens) == 0:
            minhashes.append(None)
            continue
        mh = MinHash.from_tokens(tokens, num_perm=num_perm)
        minhashes.append(mh)
        lsh.insert(i, mh)

    return minhashes, lsh