"""Unit tests for PerformanceResult statistics"""

from agno.eval.performance import PerformanceResult

# ---------------------------------------------------------------------------
# p95 percentile for small samples
# ---------------------------------------------------------------------------


def test_single_sample_p95_matches_sample():
    result = PerformanceResult(run_times=[1.0], memory_usages=[10.0])
    assert result.p95_run_time == 1.0
    assert result.p95_memory_usage == 10.0


def test_small_sample_p95_stays_within_observed_range():
    result = PerformanceResult(run_times=[1.0, 2.0], memory_usages=[10.0, 20.0])
    assert result.min_run_time <= result.p95_run_time <= result.max_run_time
    assert result.min_memory_usage <= result.p95_memory_usage <= result.max_memory_usage


def test_identical_samples_p95_equals_value():
    result = PerformanceResult(run_times=[5.0, 5.0, 5.0])
    assert result.p95_run_time == 5.0


def test_empty_run_times_p95_is_zero():
    result = PerformanceResult(run_times=[], memory_usages=[])
    assert result.p95_run_time == 0
    assert result.p95_memory_usage == 0
