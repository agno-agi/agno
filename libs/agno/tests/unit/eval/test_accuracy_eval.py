"""Unit tests for AccuracyEval"""

from unittest.mock import AsyncMock, MagicMock

from agno.eval.accuracy import AccuracyAgentResponse, AccuracyEval
from agno.run.agent import RunOutput


def _mock_evaluator(eval_instance: AccuracyEval, score: int = 8):
    """Helper to mock the evaluator agent to return a numeric accuracy score."""
    evaluator = eval_instance.get_evaluator_agent()
    evaluator.model = MagicMock()
    mock_response = AccuracyAgentResponse(accuracy_score=score, accuracy_reason="Mocked evaluation response.")
    mock_output = RunOutput(content=mock_response)
    evaluator.run = MagicMock(return_value=mock_output)
    evaluator.arun = AsyncMock(return_value=mock_output)
    eval_instance.evaluator_agent = evaluator
    return evaluator


def _mock_evaluator_failure(eval_instance: AccuracyEval):
    """Helper to mock the evaluator agent so every evaluation fails (e.g. judge model unavailable)."""
    evaluator = eval_instance.get_evaluator_agent()
    evaluator.model = MagicMock()
    evaluator.run = MagicMock(side_effect=Exception("Evaluator model unavailable"))
    evaluator.arun = AsyncMock(side_effect=Exception("Evaluator model unavailable"))
    eval_instance.evaluator_agent = evaluator
    return evaluator


def test_basic_evaluation_computes_score():
    """A successful evaluation populates results and computes the score stats."""
    eval = AccuracyEval(
        input="What is 2 + 2?",
        expected_output="4",
    )
    _mock_evaluator(eval, score=8)

    result = eval.run_with_output(output="4", print_results=False, print_summary=False)

    assert result is not None
    assert len(result.results) == 1
    assert result.avg_score == 8
    assert result.min_score == 8
    assert result.max_score == 8


def test_all_iterations_fail_returns_none_stats():
    """Regression for #7672: when every iteration fails, the stat fields default to None
    instead of being left unset (which raised AttributeError)."""
    eval = AccuracyEval(
        input="What is 2 + 2?",
        expected_output="4",
        num_iterations=2,
    )
    _mock_evaluator_failure(eval)

    result = eval.run_with_output(output="4", print_results=False, print_summary=False)

    assert result is not None
    assert len(result.results) == 0
    assert result.avg_score is None
    assert result.mean_score is None
    assert result.min_score is None
    assert result.max_score is None
    assert result.std_dev_score is None


def test_print_summary_does_not_raise_when_all_iterations_fail():
    """print_summary() must not raise AttributeError on an empty result (the bug's crash site)."""
    eval = AccuracyEval(
        input="What is 2 + 2?",
        expected_output="4",
    )
    _mock_evaluator_failure(eval)

    result = eval.run_with_output(output="4", print_results=False, print_summary=False)
    # Should complete without raising AttributeError.
    result.print_summary()


async def test_async_all_iterations_fail_returns_none_stats():
    """Async regression for #7672 via arun_with_output."""
    eval = AccuracyEval(
        input="What is 2 + 2?",
        expected_output="4",
    )
    _mock_evaluator_failure(eval)

    result = await eval.arun_with_output(output="4", print_results=False, print_summary=False)

    assert result is not None
    assert len(result.results) == 0
    assert result.avg_score is None
