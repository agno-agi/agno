from unittest.mock import MagicMock, patch

from agno.agent.agent import Agent
from agno.eval.accuracy import AccuracyEval
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.eval.performance import PerformanceEval
from agno.eval.reliability import ReliabilityEval


def test_accuracy_evals_telemetry():
    """Test that telemetry logging is called during sync accuracy eval run."""
    agent = Agent()
    accuracy_eval = AccuracyEval(agent=agent, input="What is the capital of France?", expected_output="Paris")

    # Assert telemetry is active by default
    assert accuracy_eval.telemetry

    # Mock the API call that gets made when telemetry is enabled
    with patch("agno.api.evals.create_eval_run_telemetry") as mock_create:
        agent.model = MagicMock()
        accuracy_eval.run(print_summary=False, print_results=False)

        # Verify API was called with correct parameters
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]["eval_run"]
        assert call_args.run_id == accuracy_eval.eval_id
        assert call_args.eval_type.value == "accuracy"


def test_performance_evals_telemetry():
    """Test that telemetry works for performance evaluations."""

    def sample_func():
        return "test result"

    performance_eval = PerformanceEval(func=sample_func)

    # Assert telemetry is active by default
    assert performance_eval.telemetry

    # Mock the API call that gets made when telemetry is enabled
    with patch("agno.api.evals.create_eval_run_telemetry") as mock_create:
        performance_eval.run()

        # Verify API was called with correct parameters
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]["eval_run"]
        assert call_args.run_id == performance_eval.eval_id
        assert call_args.eval_type.value == "performance"


def test_reliability_evals_telemetry():
    """Test that telemetry works for reliability evaluations."""
    from agno.models.message import Message
    from agno.run.agent import RunOutput

    # Create a mock RunOutput with proper messages and tool calls
    mock_message = Message(
        role="assistant",
        content="Test response",
        tool_calls=[{"id": "call_1", "type": "function", "function": {"name": "test_tool", "arguments": "{}"}}],
    )
    mock_response = RunOutput(content="Test response", messages=[mock_message])
    reliability_eval = ReliabilityEval(agent_response=mock_response, expected_tool_calls=["test_tool"])

    # Assert telemetry is active by default
    assert reliability_eval.telemetry

    # Mock the API call that gets made when telemetry is enabled
    with patch("agno.api.evals.create_eval_run_telemetry") as mock_create:
        reliability_eval.run(print_results=False)

        # Verify API was called with correct parameters
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]["eval_run"]
        assert call_args.run_id == reliability_eval.eval_id
        assert call_args.eval_type.value == "reliability"


def test_agent_as_judge_numeric_telemetry():
    """Test that telemetry works for agent-as-judge evaluations (numeric mode)."""
    eval = AgentAsJudgeEval(
        criteria="Response must be helpful",
        scoring_strategy="numeric",
        threshold=7,
    )

    # Assert telemetry is active by default
    assert eval.telemetry

    evaluator = eval.get_evaluator_agent()
    evaluator.model = MagicMock()

    # Mock the API call that gets made when telemetry is enabled
    with patch("agno.api.evals.create_eval_run_telemetry") as mock_create:
        eval.run(input="What is Python?", output="Python is a programming language.", print_results=False)

        # Verify API was called with correct parameters
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]["eval_run"]
        assert call_args.eval_type.value == "agent_as_judge"


def test_agent_as_judge_binary_telemetry():
    """Test that telemetry works for agent-as-judge evaluations (binary mode)."""
    eval = AgentAsJudgeEval(
        criteria="Response must not contain personal info",
        scoring_strategy="binary",
    )

    # Assert telemetry is active by default
    assert eval.telemetry

    evaluator = eval.get_evaluator_agent()
    evaluator.model = MagicMock()

    # Mock the API call that gets made when telemetry is enabled
    with patch("agno.api.evals.create_eval_run_telemetry") as mock_create:
        eval.run(input="Tell me about privacy", output="Privacy is important.", print_results=False)

        # Verify API was called with correct parameters
        mock_create.assert_called_once()
        call_args = mock_create.call_args[1]["eval_run"]
        assert call_args.eval_type.value == "agent_as_judge"
