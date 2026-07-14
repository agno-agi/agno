"""Regression tests for Timer.elapsed.

`elapsed` previously returned `self.elapsed_time or (perf_counter() -
self.start_time) if self.start_time else 0.0`, which Python parses as
`(self.elapsed_time or (perf_counter() - self.start_time)) if self.start_time
else 0.0`. Since 0.0 is falsy, a timer stopped with an elapsed_time of
exactly 0.0 (a fast but real measurement) would silently recompute using the
*current* time instead of returning the frozen, already-measured value.
"""

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
