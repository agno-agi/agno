"""Unit tests for AgentAsJudgeEval batch handling (#10879)."""

import pytest

from agno.eval.agent_as_judge import AgentAsJudgeEval


class TestEmptyCasesBatch:
    """run(cases=[]) must return an empty result, not crash (#10879)."""

    def test_run_with_empty_cases_returns_empty_result(self):
        evaluator = AgentAsJudgeEval(criteria="is relevant", show_spinner=False)
        result = evaluator.run(cases=[])
        assert result is not None
        assert result.results == []

    def test_run_with_empty_cases_does_not_raise(self):
        evaluator = AgentAsJudgeEval(criteria="is relevant", show_spinner=False)
        evaluator.run(cases=[])  # must not raise UnboundLocalError
