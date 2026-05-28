"""Unit tests for vectordb score normalization functions."""

import pytest

from agno.vectordb.distance import Distance
from agno.vectordb.score import (
    normalize_cosine,
    normalize_l2,
    normalize_max_inner_product,
    normalize_score,
    score_to_cosine_distance,
    score_to_distance_threshold,
    score_to_l2_distance,
    score_to_max_inner_product,
)


def test_normalize_cosine_identical_vectors():
    """Distance 0 should return similarity 1.0."""
    assert normalize_cosine(0.0) == 1.0


def test_normalize_cosine_orthogonal_vectors():
    """Distance 1 should return similarity 0.0."""
    assert normalize_cosine(1.0) == 0.0


def test_normalize_cosine_opposite_vectors():
    """Distance 2 should return similarity 0.0 (clamped)."""
    assert normalize_cosine(2.0) == 0.0


def test_normalize_cosine_typical_distance():
    """Distance 0.3 should return similarity 0.7."""
    assert normalize_cosine(0.3) == pytest.approx(0.7)


def test_normalize_cosine_nan_returns_zero():
    """NaN input should return 0.0."""
    assert normalize_cosine(float("nan")) == 0.0


def test_normalize_cosine_inf_returns_zero():
    """Infinite input should return 0.0."""
    assert normalize_cosine(float("inf")) == 0.0
    assert normalize_cosine(float("-inf")) == 0.0


def test_normalize_cosine_negative_distance_clamped():
    """Negative distance should be clamped to 1.0."""
    assert normalize_cosine(-0.5) == 1.0


def test_normalize_l2_identical_vectors():
    """Distance 0 should return similarity 1.0."""
    assert normalize_l2(0.0) == 1.0


def test_normalize_l2_distance_one():
    """Distance 1 should return similarity 0.5."""
    assert normalize_l2(1.0) == 0.5


def test_normalize_l2_large_distance():
    """Large distance should approach 0."""
    assert normalize_l2(100.0) == pytest.approx(1 / 101)


def test_normalize_l2_nan_returns_zero():
    """NaN input should return 0.0."""
    assert normalize_l2(float("nan")) == 0.0


def test_normalize_l2_inf_returns_zero():
    """Infinite input should return 0.0."""
    assert normalize_l2(float("inf")) == 0.0


def test_normalize_max_inner_product_identical_vectors():
    """Inner product 1 should return similarity 1.0."""
    assert normalize_max_inner_product(1.0) == 1.0


def test_normalize_max_inner_product_orthogonal_vectors():
    """Inner product 0 should return similarity 0.5."""
    assert normalize_max_inner_product(0.0) == 0.5


def test_normalize_max_inner_product_opposite_vectors():
    """Inner product -1 should return similarity 0.0."""
    assert normalize_max_inner_product(-1.0) == 0.0


def test_normalize_max_inner_product_typical():
    """Inner product 0.8 should return similarity 0.9."""
    assert normalize_max_inner_product(0.8) == pytest.approx(0.9)


def test_normalize_max_inner_product_nan_returns_zero():
    """NaN input should return 0.0."""
    assert normalize_max_inner_product(float("nan")) == 0.0


def test_normalize_max_inner_product_positive_inf_returns_one():
    """Positive infinity should return 1.0."""
    assert normalize_max_inner_product(float("inf")) == 1.0


def test_normalize_max_inner_product_negative_inf_returns_zero():
    """Negative infinity should return 0.0."""
    assert normalize_max_inner_product(float("-inf")) == 0.0


def test_normalize_score_cosine_dispatch():
    """Should dispatch to normalize_cosine."""
    assert normalize_score(0.3, Distance.cosine) == pytest.approx(0.7)


def test_normalize_score_l2_dispatch():
    """Should dispatch to normalize_l2."""
    assert normalize_score(1.0, Distance.l2) == 0.5


def test_normalize_score_max_inner_product_dispatch():
    """Should dispatch to normalize_max_inner_product."""
    assert normalize_score(0.8, Distance.max_inner_product) == pytest.approx(0.9)


def test_normalize_score_unknown_metric_raises():
    """Unknown metric should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown distance metric"):
        normalize_score(0.5, "invalid")  # type: ignore


def test_score_to_cosine_distance_similarity_one():
    """Similarity 1.0 should return distance 0."""
    assert score_to_cosine_distance(1.0) == 0.0


def test_score_to_cosine_distance_similarity_zero():
    """Similarity 0.0 should return distance 1."""
    assert score_to_cosine_distance(0.0) == 1.0


def test_score_to_cosine_distance_typical():
    """Similarity 0.7 should return distance 0.3."""
    assert score_to_cosine_distance(0.7) == pytest.approx(0.3)


def test_score_to_cosine_distance_roundtrip():
    """Converting back and forth should give original value."""
    original = 0.65
    distance = score_to_cosine_distance(original)
    restored = normalize_cosine(distance)
    assert restored == pytest.approx(original)


def test_score_to_l2_distance_similarity_one():
    """Similarity 1.0 should return distance 0."""
    assert score_to_l2_distance(1.0) == 0.0


def test_score_to_l2_distance_similarity_half():
    """Similarity 0.5 should return distance 1."""
    assert score_to_l2_distance(0.5) == 1.0


def test_score_to_l2_distance_zero_raises():
    """Similarity 0 should raise ValueError."""
    with pytest.raises(ValueError, match="must be > 0"):
        score_to_l2_distance(0.0)


def test_score_to_l2_distance_negative_raises():
    """Negative similarity should raise ValueError."""
    with pytest.raises(ValueError, match="must be > 0"):
        score_to_l2_distance(-0.5)


def test_score_to_l2_distance_roundtrip():
    """Converting back and forth should give original value."""
    original = 0.8
    distance = score_to_l2_distance(original)
    restored = normalize_l2(distance)
    assert restored == pytest.approx(original)


def test_score_to_max_inner_product_similarity_one():
    """Similarity 1.0 should return inner product 1."""
    assert score_to_max_inner_product(1.0) == 1.0


def test_score_to_max_inner_product_similarity_half():
    """Similarity 0.5 should return inner product 0."""
    assert score_to_max_inner_product(0.5) == 0.0


def test_score_to_max_inner_product_similarity_zero():
    """Similarity 0.0 should return inner product -1."""
    assert score_to_max_inner_product(0.0) == -1.0


def test_score_to_max_inner_product_typical():
    """Similarity 0.9 should return inner product 0.8."""
    assert score_to_max_inner_product(0.9) == pytest.approx(0.8)


def test_score_to_max_inner_product_roundtrip():
    """Converting back and forth should give original value."""
    original = 0.75
    inner_product = score_to_max_inner_product(original)
    restored = normalize_max_inner_product(inner_product)
    assert restored == pytest.approx(original)


def test_score_to_distance_threshold_cosine():
    """Should dispatch to score_to_cosine_distance."""
    assert score_to_distance_threshold(0.7, Distance.cosine) == pytest.approx(0.3)


def test_score_to_distance_threshold_l2():
    """Should dispatch to score_to_l2_distance."""
    assert score_to_distance_threshold(0.5, Distance.l2) == 1.0


def test_score_to_distance_threshold_max_inner_product():
    """Should dispatch to score_to_max_inner_product."""
    assert score_to_distance_threshold(0.9, Distance.max_inner_product) == pytest.approx(0.8)


def test_score_to_distance_threshold_unknown_raises():
    """Unknown metric should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown distance metric"):
        score_to_distance_threshold(0.5, "invalid")  # type: ignore


@pytest.mark.parametrize("similarity", [0.1, 0.25, 0.5, 0.75, 0.9, 0.99])
def test_cosine_roundtrip(similarity):
    """Roundtrip conversion should return original value."""
    distance = score_to_distance_threshold(similarity, Distance.cosine)
    restored = normalize_score(distance, Distance.cosine)
    assert restored == pytest.approx(similarity)


@pytest.mark.parametrize("similarity", [0.1, 0.25, 0.5, 0.75, 0.9, 0.99])
def test_l2_roundtrip(similarity):
    """Roundtrip conversion should return original value."""
    distance = score_to_distance_threshold(similarity, Distance.l2)
    restored = normalize_score(distance, Distance.l2)
    assert restored == pytest.approx(similarity)


@pytest.mark.parametrize("similarity", [0.1, 0.25, 0.5, 0.75, 0.9, 0.99])
def test_max_inner_product_roundtrip(similarity):
    """Roundtrip conversion should return original value."""
    threshold = score_to_distance_threshold(similarity, Distance.max_inner_product)
    restored = normalize_score(threshold, Distance.max_inner_product)
    assert restored == pytest.approx(similarity)
