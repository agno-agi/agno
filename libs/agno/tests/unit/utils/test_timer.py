"""Unit tests for the Timer utility."""

from unittest.mock import patch

from agno.utils.timer import Timer


def test_elapsed_returns_frozen_zero_after_stop_not_a_live_recompute():
    timer = Timer()

    with patch("agno.utils.timer.perf_counter", return_value=100.0):
        timer.start()
        timer.stop()

    assert timer.elapsed_time == 0.0

    with patch("agno.utils.timer.perf_counter", return_value=250.0):
        assert timer.elapsed == 0.0


def test_elapsed_recomputes_live_while_timer_is_still_running():
    timer = Timer()

    with patch("agno.utils.timer.perf_counter", return_value=100.0):
        timer.start()

    with patch("agno.utils.timer.perf_counter", return_value=103.5):
        assert timer.elapsed == 3.5


def test_elapsed_is_zero_before_start():
    timer = Timer()
    assert timer.elapsed == 0.0


def test_stop_records_the_elapsed_interval():
    timer = Timer()

    with patch("agno.utils.timer.perf_counter", side_effect=[100.0, 103.0]):
        timer.start()
        timer.stop()

    assert timer.elapsed == 3.0


def test_restart_measures_a_fresh_interval():
    timer = Timer()

    with patch("agno.utils.timer.perf_counter", side_effect=[0.0, 5.0, 100.0, 108.0]):
        timer.start()
        timer.stop()
        timer.start()
        timer.stop()

    assert timer.elapsed == 8.0


def test_stop_twice_extends_to_the_last_stop():
    """Duration is wall-clock lifetime: a timer stopped more than once (e.g. a run paused
    then continued) reports the time to the last stop, including the gap between them."""
    timer = Timer()

    with patch("agno.utils.timer.perf_counter", side_effect=[10.0, 11.0, 60.0]):
        timer.start()
        timer.stop()
        timer.stop()

    assert timer.elapsed == 50.0


def test_context_manager_measures_the_block():
    timer = Timer()

    with patch("agno.utils.timer.perf_counter", side_effect=[10.0, 12.0]):
        with timer:
            pass

    assert timer.elapsed == 2.0


def test_to_dict_reports_start_end_and_elapsed():
    timer = Timer()

    with patch("agno.utils.timer.perf_counter", side_effect=[10.0, 13.0]):
        timer.start()
        timer.stop()

    result = timer.to_dict()
    assert result["start_time"] == "10.0"
    assert result["end_time"] == "13.0"
    assert result["elapsed"] == 3.0
