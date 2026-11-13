"""Argument comparisons agree across both public tool-evaluation APIs."""

import pytest

from agno.eval.reliability import ReliabilityEval
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.scorer import ToolCallScorer


@pytest.mark.parametrize(
    "actual,expected,matches",
    [
        (True, 1, False),
        (1, True, False),
        (False, 0, False),
        (0, False, False),
        (True, 1.0, False),
        (0.0, False, False),
        ([True], [1], False),
        ({"items": [False]}, {"items": [0]}, False),
        ([{"value": 1}], [{"value": True}], False),
        (True, True, True),
        (False, False, True),
        (1, 1, True),
        (1, 1.0, True),
        (1.0, 1, True),
        ("1", 1, False),
        (None, None, True),
        ([1, 2], [2, 1], False),
        ([1], [1, 2], False),
        ({"a": 1, "b": 2}, {"a": 1}, False),
        ({"items": [True, None]}, {"items": [True, None]}, True),
    ],
)
@pytest.mark.parametrize("api", ["score", "ascore", "run", "arun"])
async def test_tool_argument_value_types(actual, expected, matches, api):
    run = RunOutput(tools=[ToolExecution(tool_name="check", tool_args={"value": actual, "extra": "allowed"})])
    arguments = {"check": {"value": expected}}
    if api in ("score", "ascore"):
        scorer = ToolCallScorer(["check"], arguments=arguments)
        result = scorer.score(run) if api == "score" else await scorer.ascore(run)
        assert result.passed is matches
    else:
        evaluation = ReliabilityEval(
            agent_response=run,
            expected_tool_calls=["check"],
            expected_tool_call_arguments=arguments,
            telemetry=False,
            show_spinner=False,
        )
        result = evaluation.run() if api == "run" else await evaluation.arun()
        assert (result.eval_status == "PASSED") is matches


@pytest.mark.parametrize("actual", [{}, {"other": None}])
def test_missing_argument_does_not_match_null(actual):
    run = RunOutput(tools=[ToolExecution(tool_name="check", tool_args=actual)])
    arguments = {"check": {"value": None}}
    assert ToolCallScorer(["check"], arguments=arguments).score(run).passed is False
    result = ReliabilityEval(
        agent_response=run,
        expected_tool_calls=["check"],
        expected_tool_call_arguments=arguments,
        telemetry=False,
        show_spinner=False,
    ).run()
    assert result.eval_status == "FAILED"
