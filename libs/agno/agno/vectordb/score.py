"""Score normalization utilities for vector database distance metrics."""

import math

from agno.vectordb.distance import Distance


def normalize_cosine(distance: float) -> float:
    """Convert cosine distance to similarity score.

    Args:
        distance: Cosine distance value (0=identical, 1=orthogonal, 2=opposite)

    Returns:
        Similarity score in [0.0, 1.0]
    """
    if math.isnan(distance) or math.isinf(distance):
        return 0.0
    return max(0.0, min(1.0, 1.0 - distance))


def normalize_l2(distance: float) -> float:
    """Convert L2 distance to similarity score.

    Args:
        distance: L2 (Euclidean) distance value (0=identical)

    Returns:
        Similarity score in (0.0, 1.0]
    """
    if math.isnan(distance) or math.isinf(distance):
        return 0.0
    return 1.0 / (1.0 + distance)


def normalize_max_inner_product(inner_product: float) -> float:
    """Convert inner product to similarity score.

    Args:
        inner_product: Inner product value (1=identical, 0=orthogonal, -1=opposite)

    Returns:
        Similarity score in [0.0, 1.0]
    """
    if math.isnan(inner_product):
        return 0.0
    if math.isinf(inner_product):
        return 1.0 if inner_product > 0 else 0.0
    return max(0.0, min(1.0, (inner_product + 1.0) / 2.0))


def normalize_score(distance: float, metric: Distance) -> float:
    """Convert raw distance to similarity score based on metric type.

    Args:
        distance: Raw distance or score value
        metric: Distance metric type

    Returns:
        Similarity score in [0.0, 1.0]
    """
    if metric == Distance.cosine:
        return normalize_cosine(distance)
    elif metric == Distance.l2:
        return normalize_l2(distance)
    elif metric == Distance.max_inner_product:
        return normalize_max_inner_product(distance)
    else:
        raise ValueError(f"Unknown distance metric: {metric}")


def score_to_cosine_distance(similarity: float) -> float:
    """Convert similarity score to cosine distance threshold."""
    return 1.0 - similarity


def score_to_l2_distance(similarity: float) -> float:
    """Convert similarity score to L2 distance threshold."""
    if similarity <= 0:
        raise ValueError("similarity must be > 0 for L2 distance conversion")
    return (1.0 / similarity) - 1.0


def score_to_max_inner_product(similarity: float) -> float:
    """Convert similarity score to inner product threshold."""
    return 2.0 * similarity - 1.0


def score_to_distance_threshold(similarity: float, metric: Distance) -> float:
    """Convert similarity score to raw distance threshold.

    Args:
        similarity: Minimum similarity score (0.0-1.0)
        metric: Distance metric type

    Returns:
        Raw distance threshold for filtering
    """
    if metric == Distance.cosine:
        return score_to_cosine_distance(similarity)
    elif metric == Distance.l2:
        return score_to_l2_distance(similarity)
    elif metric == Distance.max_inner_product:
        return score_to_max_inner_product(similarity)
    else:
        raise ValueError(f"Unknown distance metric: {metric}")
