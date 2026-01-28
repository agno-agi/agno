"""Score normalization utilities for vector database distance metrics.

Converts raw distance/similarity values from vector databases (e.g., pgvector)
into normalized 0-1 similarity floats. Each function handles a specific distance
metric and guards against NaN/infinity edge cases.

These utilities are used by vector_search() and hybrid_search() to attach
comparable similarity scores to returned Documents.
"""

import math

from agno.vectordb.distance import Distance


def normalize_cosine(distance: float) -> float:
    """Normalize a cosine distance value to a 0-1 similarity score.

    Args:
        distance: Raw cosine distance from pgvector's ``<=>`` operator.
            Range [0, 2] where 0 = identical vectors, 1 = orthogonal,
            2 = opposite vectors.

    Returns:
        Similarity score clamped to [0.0, 1.0] where 1.0 = identical.
    """
    if math.isnan(distance):
        return 0.0
    if math.isinf(distance):
        return 0.0
    result = 1.0 - distance
    return max(0.0, min(1.0, result))


def normalize_l2(distance: float) -> float:
    """Normalize an L2 (Euclidean) distance value to a 0-1 similarity score.

    Args:
        distance: Raw L2 distance from pgvector's ``<->`` operator.
            Range [0, +inf) where 0 = identical vectors.

    Returns:
        Similarity score in (0.0, 1.0] where 1.0 = identical.
        The formula ``1 / (1 + distance)`` is naturally bounded.
    """
    if math.isnan(distance):
        return 0.0
    if math.isinf(distance):
        return 0.0
    return 1.0 / (1.0 + distance)


def normalize_max_inner_product(raw_score: float) -> float:
    """Normalize a max inner product value to a 0-1 similarity score.

    Args:
        raw_score: Raw value from pgvector's ``<#>`` operator (negative
            inner product). pgvector returns the negative inner product
            for ascending index scan compatibility.

    Returns:
        Similarity score clamped to [0.0, 1.0].
    """
    if math.isnan(raw_score):
        return 0.0
    if math.isinf(raw_score):
        if raw_score > 0:
            return 1.0
        return 0.0
    result = (raw_score + 1.0) / 2.0
    return max(0.0, min(1.0, result))


def normalize_score(distance: float, metric: Distance) -> float:
    """Dispatch to the appropriate normalization function for a given metric.

    Args:
        distance: Raw distance or score value from the vector database.
        metric: The distance metric used by the vector database index.

    Returns:
        Normalized similarity score in [0.0, 1.0].

    Raises:
        ValueError: If ``metric`` is not a recognized Distance enum value.
    """
    if metric == Distance.cosine:
        return normalize_cosine(distance)
    elif metric == Distance.l2:
        return normalize_l2(distance)
    elif metric == Distance.max_inner_product:
        return normalize_max_inner_product(distance)
    else:
        raise ValueError(f"Unknown distance metric: {metric}")


def score_to_cosine_distance(similarity_threshold: float) -> float:
    """Inverse of normalize_cosine"""
    return 1.0 - similarity_threshold


def score_to_l2_distance(similarity_threshold: float) -> float:
    """Inverse of normalize_l2"""
    if similarity_threshold <= 0:
        raise ValueError("similarity_threshold must be > 0 for L2 distance conversion")
    return (1.0 / similarity_threshold) - 1.0


def score_to_max_inner_product(similarity_threshold: float) -> float:
    """Inverse of normalize_max_inner_product"""
    return 2.0 * similarity_threshold - 1.0


def score_to_distance_threshold(similarity_threshold: float, metric: Distance) -> float:
    """Dispatch to metric-specific inverse function."""
    if metric == Distance.cosine:
        return score_to_cosine_distance(similarity_threshold)
    elif metric == Distance.l2:
        return score_to_l2_distance(similarity_threshold)
    elif metric == Distance.max_inner_product:
        return score_to_max_inner_product(similarity_threshold)
    else:
        raise ValueError(f"Unknown distance metric: {metric}")
