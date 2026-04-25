"""Unit tests for AccuracyResult dataclass."""

from agno.eval.accuracy import AccuracyEvaluation, AccuracyResult


def _make_evaluation(score: int = 8) -> AccuracyEvaluation:
    return AccuracyEvaluation(
        input="What is Python?",
        output="Python is a programming language.",
        expected_output="Python is a high-level programming language.",
        score=score,
        reason="Good answer.",
    )


class TestAccuracyResultEmptyResults:
    """Tests for AccuracyResult when no iterations succeed (results=[])."""

    def test_avg_score_defaults_to_none(self):
        """avg_score should be None when no results exist, not raise AttributeError."""
        result = AccuracyResult()
        assert result.avg_score is None

    def test_mean_score_defaults_to_none(self):
        result = AccuracyResult()
        assert result.mean_score is None

    def test_min_score_defaults_to_none(self):
        result = AccuracyResult()
        assert result.min_score is None

    def test_max_score_defaults_to_none(self):
        result = AccuracyResult()
        assert result.max_score is None

    def test_std_dev_score_defaults_to_none(self):
        result = AccuracyResult()
        assert result.std_dev_score is None

    def test_print_summary_does_not_raise(self):
        """print_summary() should not raise AttributeError when results is empty."""
        result = AccuracyResult()
        # Should complete without AttributeError
        result.print_summary()

    def test_compute_stats_noop_when_empty(self):
        """compute_stats() should be a no-op when results is empty."""
        result = AccuracyResult()
        result.compute_stats()
        assert result.avg_score is None
        assert result.mean_score is None


class TestAccuracyResultWithResults:
    """Tests for AccuracyResult when results are present."""

    def test_compute_stats_single_result(self):
        result = AccuracyResult()
        result.results.append(_make_evaluation(score=8))
        result.compute_stats()
        assert result.avg_score == 8.0
        assert result.mean_score == 8.0
        assert result.min_score == 8
        assert result.max_score == 8
        assert result.std_dev_score == 0  # stdev of single value

    def test_compute_stats_multiple_results(self):
        result = AccuracyResult()
        result.results.extend([_make_evaluation(score=6), _make_evaluation(score=10)])
        result.compute_stats()
        assert result.avg_score == 8.0
        assert result.mean_score == 8.0
        assert result.min_score == 6
        assert result.max_score == 10
        assert result.std_dev_score is not None
        assert result.std_dev_score > 0

    def test_print_summary_with_results(self):
        """print_summary() should work correctly when results are present."""
        result = AccuracyResult()
        result.results.append(_make_evaluation(score=7))
        result.compute_stats()
        # Should complete without any error
        result.print_summary()
