"""An empty Parallel (built dynamically with no steps) must not crash.

The async path already returns a "No parallel steps executed" StepOutput, but the
sync execute()/execute_stream() paths built a ThreadPoolExecutor with
max_workers=len(self.steps) == 0, raising ValueError.
"""

import asyncio

from agno.workflow.parallel import Parallel
from agno.workflow.types import StepInput


def _step_input():
    return StepInput(input="hi")


def test_empty_parallel_sync_matches_async():
    result = Parallel(name="empty").execute(_step_input())
    assert result.content == "No parallel steps executed"

    async_result = asyncio.run(Parallel(name="empty").aexecute(_step_input()))
    assert async_result.content == result.content


def test_empty_parallel_stream_does_not_crash():
    events = list(Parallel(name="empty").execute_stream(_step_input()))
    assert events  # produces its aggregated output without raising
