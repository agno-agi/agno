"""Vector math for ranking, without numpy, which is not a core dependency."""

from math import sqrt
from typing import List, Sequence


def dot(left: Sequence[float], right: Sequence[float]) -> float:
    """Dot product, which is cosine similarity when both vectors are unit length."""
    total = 0.0
    for a, b in zip(left, right):
        total += a * b
    return total


def unit(vector: Sequence[float]) -> List[float]:
    """Scale to unit length, so repeated similarity checks reduce to a dot product."""
    norm = sqrt(sum(value * value for value in vector))
    if norm <= 0.0:
        return [0.0] * len(vector)
    return [value / norm for value in vector]


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Cosine similarity of two vectors, 0.0 when either has no magnitude."""
    product = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        product += a * b
        left_norm += a * a
        right_norm += b * b
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return product / (sqrt(left_norm) * sqrt(right_norm))
