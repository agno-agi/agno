"""BUG-013: Workflow stream_events `or` pattern silently overrides explicit False.

stream_events = stream_events or self.stream_events
When stream_events=False (explicit), Python `or` evaluates to self.stream_events.
"""

import inspect
import re

import pytest


class TestBUG013StreamEventsOrPattern:
    def test_python_or_semantics_with_false(self):
        """Prove that `False or True` evaluates to True in Python."""
        stream_events = False
        self_stream_events = True
        result = stream_events or self_stream_events
        assert result is True, "False or True should be True — this is the bug mechanism"

    def test_workflow_uses_or_pattern(self):
        """Verify workflow.py uses the buggy `or` pattern for stream_events."""
        source = inspect.getsource(__import__("agno.workflow.workflow", fromlist=["workflow"]))
        matches = re.findall(r"stream_events\s*=\s*stream_events\s+or\s+self\.stream_events", source)
        assert len(matches) >= 2, f"Expected at least 2 `or` pattern instances (sync+async), found {len(matches)}"

    def test_stream_param_uses_correct_pattern(self):
        """Control: `stream` param correctly uses `if stream is None:` pattern."""
        source = inspect.getsource(__import__("agno.workflow.workflow", fromlist=["workflow"]))
        correct_pattern = re.findall(r"if stream is None:", source)
        assert len(correct_pattern) >= 2, "stream param should use None-check in both sync and async"
