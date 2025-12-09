"""Unit tests for AgentAsJudgeEval"""

from unittest.mock import AsyncMock, MagicMock

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.eval.agent_as_judge import AgentAsJudgeEval, BinaryJudgeResponse, NumericJudgeResponse
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput


def _mock_evaluator_numeric(eval_instance: AgentAsJudgeEval, score: int = 8):
    """Helper to mock evaluator agent for numeric mode."""
    evaluator = eval_instance.get_evaluator_agent()
    evaluator.model = MagicMock()
    mock_response = NumericJudgeResponse(score=score, reason="Mocked evaluation response.")
    mock_output = RunOutput(content=mock_response)
    evaluator.run = MagicMock(return_value=mock_output)
    eval_instance.evaluator_agent = evaluator
    return evaluator


def _mock_evaluator_binary(eval_instance: AgentAsJudgeEval, passed: bool = True):
    """Helper to mock evaluator agent for binary mode."""
    evaluator = eval_instance.get_evaluator_agent()
    evaluator.model = MagicMock()
    mock_response = BinaryJudgeResponse(passed=passed, reason="Mocked evaluation response.")
    mock_output = RunOutput(content=mock_response)
    evaluator.run = MagicMock(return_value=mock_output)
    eval_instance.evaluator_agent = evaluator
    return evaluator


def test_numeric_mode_basic():
    """Test basic numeric mode evaluation."""
    eval = AgentAsJudgeEval(
        criteria="Response must be helpful",
        scoring_strategy="numeric",
        threshold=7,
    )

    _mock_evaluator_numeric(eval, score=8)

    result = eval.run(
        input="What is Python?",
        output="Python is a programming language.",
        print_results=False,
    )

    assert result is not None
    assert len(result.results) == 1
    assert result.results[0].score is not None
    assert 1 <= result.results[0].score <= 10
    assert isinstance(result.results[0].passed, bool)


def test_binary_mode_basic():
    """Test basic binary mode evaluation."""
    eval = AgentAsJudgeEval(
        criteria="Response must not contain personal info",
        scoring_strategy="binary",
    )

    _mock_evaluator_binary(eval, passed=True)

    result = eval.run(
        input="Tell me about privacy",
        output="Privacy is important.",
        print_results=False,
    )

    assert result is not None
    assert len(result.results) == 1
    assert result.results[0].score is None  # Binary mode doesn't have scores
    assert isinstance(result.results[0].passed, bool)


def test_default_values():
    """Test that default values are correct."""
    eval = AgentAsJudgeEval(criteria="Be helpful")

    assert eval.scoring_strategy == "binary"
    assert eval.threshold == 7
    assert eval.telemetry is True


def test_batch_mode():
    """Test batch evaluation with multiple cases."""
    eval = AgentAsJudgeEval(
        criteria="Response must be helpful",
        scoring_strategy="numeric",
        threshold=7,
    )

    # Mock the evaluator
    _mock_evaluator_numeric(eval, score=8)

    result = eval.run(
        cases=[
            {"input": "Test 1", "output": "Response 1"},
            {"input": "Test 2", "output": "Response 2"},
            {"input": "Test 3", "output": "Response 3"},
        ],
        print_results=False,
    )

    assert result is not None
    assert len(result.results) == 3
    for eval_result in result.results:
        assert eval_result.score is not None
        assert isinstance(eval_result.passed, bool)


def test_additional_guidelines():
    """Test evaluation with additional guidelines."""
    eval = AgentAsJudgeEval(
        criteria="Response must be educational",
        scoring_strategy="numeric",
        threshold=6,
        additional_guidelines="Focus on beginner-friendly explanations",
    )

    # Mock the evaluator
    _mock_evaluator_numeric(eval, score=7)

    result = eval.run(
        input="What is ML?",
        output="Machine learning is when computers learn from data.",
        print_results=False,
    )

    assert result is not None
    assert len(result.results) == 1


def test_additional_guidelines_list():
    """Test evaluation with additional guidelines as a list."""
    eval = AgentAsJudgeEval(
        criteria="Response must be clear",
        scoring_strategy="numeric",
        threshold=7,
        additional_guidelines=["Be concise", "Use simple language"],
    )

    # Mock the evaluator
    _mock_evaluator_numeric(eval, score=8)

    result = eval.run(
        input="What is AI?",
        output="AI is artificial intelligence.",
        print_results=False,
    )

    assert result is not None
    assert len(result.results) == 1


def test_custom_evaluator():
    """Test evaluation with a custom evaluator agent."""
    custom_evaluator = Agent(
        id="strict-evaluator",
        name="Strict Evaluator",
        model=OpenAIChat(id="gpt-4o-mini"),
        instructions="You are VERY strict. Only give high scores for exceptional quality.",
    )

    eval = AgentAsJudgeEval(
        criteria="Response must be excellent",
        scoring_strategy="numeric",
        threshold=8,
        evaluator_agent=custom_evaluator,
    )

    # Mock the custom evaluator
    _mock_evaluator_numeric(eval, score=9)

    result = eval.run(
        input="What is Python?",
        output="Python is a programming language.",
        print_results=False,
    )

    assert result is not None
    assert len(result.results) == 1


def test_threshold_ranges():
    """Test evaluation with different threshold values."""
    for threshold in [1, 5, 8, 10]:
        eval = AgentAsJudgeEval(
            criteria="Response must be helpful",
            scoring_strategy="numeric",
            threshold=threshold,
        )

        # Mock the evaluator
        _mock_evaluator_numeric(eval, score=7)

        result = eval.run(
            input="Test",
            output="Response",
            print_results=False,
        )

        assert result is not None
        assert len(result.results) == 1


def test_name_assignment():
    """Test that evaluation name is stored."""
    eval = AgentAsJudgeEval(
        name="My Custom Eval",
        criteria="Be helpful",
    )

    assert eval.name == "My Custom Eval"


def test_telemetry_disabled():
    """Test that telemetry can be disabled."""
    eval = AgentAsJudgeEval(
        criteria="Be helpful",
        telemetry=False,
    )

    assert eval.telemetry is False


def test_db_logging_numeric():
    """Test that numeric eval results are logged to database."""
    db = InMemoryDb()

    eval = AgentAsJudgeEval(
        criteria="Response must be accurate",
        scoring_strategy="numeric",
        threshold=7,
        db=db,
        telemetry=False,  # Disable telemetry for unit test
    )

    # Mock the evaluator
    _mock_evaluator_numeric(eval, score=8)

    result = eval.run(
        input="What is 2+2?",
        output="4",
        print_results=False,
    )

    # Verify result
    assert result is not None

    # Check database
    eval_runs = db.get_eval_runs()
    assert len(eval_runs) == 1

    eval_run = eval_runs[0]
    assert eval_run.eval_type.value == "agent_as_judge"
    assert eval_run.eval_input["criteria"] == "Response must be accurate"
    assert eval_run.eval_input["scoring_strategy"] == "numeric"
    assert eval_run.eval_input["threshold"] == 7


def test_db_logging_binary():
    """Test that binary eval results are logged to database with threshold=None."""
    db = InMemoryDb()

    eval = AgentAsJudgeEval(
        criteria="Response must not contain offensive content",
        scoring_strategy="binary",
        db=db,
        telemetry=False,
    )

    # Mock the evaluator
    _mock_evaluator_binary(eval, passed=True)

    result = eval.run(
        input="Tell me a fact",
        output="The sky is blue.",
        print_results=False,
    )

    # Verify result
    assert result is not None
    assert result.results[0].score is None  # Binary mode has no score

    # Check database
    eval_runs = db.get_eval_runs()
    assert len(eval_runs) == 1

    eval_run = eval_runs[0]
    assert eval_run.eval_type.value == "agent_as_judge"
    assert eval_run.eval_input["criteria"] == "Response must not contain offensive content"
    assert eval_run.eval_input["scoring_strategy"] == "binary"
    assert eval_run.eval_input["threshold"] is None  # Binary mode sets threshold to None


async def test_async_run():
    """Test async evaluation."""
    eval = AgentAsJudgeEval(
        criteria="Response must be concise",
        scoring_strategy="numeric",
        threshold=6,
    )

    # Mock the evaluator for async
    evaluator = eval.get_evaluator_agent()
    evaluator.model = MagicMock()  # Mock the model to avoid real API calls
    mock_response = NumericJudgeResponse(score=7, reason="Mocked async evaluation.")
    mock_output = RunOutput(content=mock_response)
    evaluator.arun = AsyncMock(return_value=mock_output)
    eval.evaluator_agent = evaluator

    result = await eval.arun(
        input="What is AI?",
        output="Artificial intelligence.",
        print_results=False,
    )

    assert result is not None
    assert len(result.results) == 1
    assert result.results[0].score is not None


def test_invalid_threshold():
    """Test that invalid threshold values raise ValueError."""
    import pytest

    # Threshold below 1 should raise ValueError
    with pytest.raises(ValueError, match="threshold must be between 1 and 10"):
        AgentAsJudgeEval(
            criteria="Test criteria",
            scoring_strategy="numeric",
            threshold=0,
        )

    # Threshold above 10 should raise ValueError
    with pytest.raises(ValueError, match="threshold must be between 1 and 10"):
        AgentAsJudgeEval(
            criteria="Test criteria",
            scoring_strategy="numeric",
            threshold=11,
        )


def test_on_fail_callback():
    """Test that on_fail callback is called when evaluation fails."""
    failed_evaluation = None

    def on_fail_handler(evaluation):
        nonlocal failed_evaluation
        failed_evaluation = evaluation

    eval = AgentAsJudgeEval(
        criteria="Response must score above 8",
        scoring_strategy="numeric",
        threshold=8,
        on_fail=on_fail_handler,
    )

    # Mock the evaluator to return a failing score
    _mock_evaluator_numeric(eval, score=5)

    result = eval.run(
        input="Test input",
        output="Test output",
        print_results=False,
    )

    # Verify the evaluation failed
    assert result is not None
    assert result.results[0].passed is False
    assert result.results[0].score == 5

    # Verify on_fail was called with the failed evaluation
    assert failed_evaluation is not None
    assert failed_evaluation.passed is False
    assert failed_evaluation.score == 5


def test_on_fail_callback_batch_mode():
    """Test that on_fail is called for each failing case in batch mode."""
    failed_evaluations = []

    def on_fail_handler(evaluation):
        failed_evaluations.append(evaluation)

    eval = AgentAsJudgeEval(
        criteria="Response must be excellent",
        scoring_strategy="numeric",
        threshold=8,
        on_fail=on_fail_handler,
    )

    # Mock the evaluator to return varying scores (some pass, some fail)
    evaluator = eval.get_evaluator_agent()
    evaluator.model = MagicMock()

    # Return different scores for each case
    mock_responses = [
        NumericJudgeResponse(score=9, reason="Excellent response."),  # Pass
        NumericJudgeResponse(score=5, reason="Poor response."),  # Fail
        NumericJudgeResponse(score=7, reason="Below threshold."),  # Fail
        NumericJudgeResponse(score=10, reason="Perfect response."),  # Pass
    ]

    # Mock run to return different responses for each call
    evaluator.run = MagicMock(side_effect=[RunOutput(content=resp) for resp in mock_responses])
    eval.evaluator_agent = evaluator

    result = eval.run(
        cases=[
            {"input": "Test 1", "output": "Response 1"},
            {"input": "Test 2", "output": "Response 2"},
            {"input": "Test 3", "output": "Response 3"},
            {"input": "Test 4", "output": "Response 4"},
        ],
        print_results=False,
    )

    # Verify results
    assert result is not None
    assert len(result.results) == 4

    # Verify pass/fail status
    assert result.results[0].passed is True  # Score 9
    assert result.results[1].passed is False  # Score 5
    assert result.results[2].passed is False  # Score 7
    assert result.results[3].passed is True  # Score 10

    # Verify on_fail was called exactly twice (for the two failing cases)
    assert len(failed_evaluations) == 2
    assert failed_evaluations[0].score == 5
    assert failed_evaluations[0].passed is False
    assert failed_evaluations[1].score == 7
    assert failed_evaluations[1].passed is False

    # Verify pass rate is 50% (2 out of 4)
    assert result.pass_rate == 50.0


async def test_on_fail_callback_batch_mode_async():
    """Test that on_fail is called for each failing case in async batch mode."""
    failed_evaluations = []

    def on_fail_handler(evaluation):
        failed_evaluations.append(evaluation)

    eval = AgentAsJudgeEval(
        criteria="Response must be excellent",
        scoring_strategy="numeric",
        threshold=8,
        on_fail=on_fail_handler,
    )

    # Mock the evaluator to return varying scores
    evaluator = eval.get_evaluator_agent()
    evaluator.model = MagicMock()

    # Return different scores for each case
    mock_responses = [
        NumericJudgeResponse(score=6, reason="Below threshold."),  # Fail
        NumericJudgeResponse(score=9, reason="Excellent response."),  # Pass
        NumericJudgeResponse(score=4, reason="Poor response."),  # Fail
    ]

    # Mock arun to return different responses for each call
    evaluator.arun = AsyncMock(side_effect=[RunOutput(content=resp) for resp in mock_responses])
    eval.evaluator_agent = evaluator

    result = await eval.arun(
        cases=[
            {"input": "Test 1", "output": "Response 1"},
            {"input": "Test 2", "output": "Response 2"},
            {"input": "Test 3", "output": "Response 3"},
        ],
        print_results=False,
    )

    # Verify results
    assert result is not None
    assert len(result.results) == 3

    # Verify pass/fail status
    assert result.results[0].passed is False  # Score 6
    assert result.results[1].passed is True  # Score 9
    assert result.results[2].passed is False  # Score 4

    # Verify on_fail was called exactly twice (for the two failing cases)
    assert len(failed_evaluations) == 2
    assert failed_evaluations[0].score == 6
    assert failed_evaluations[0].passed is False
    assert failed_evaluations[1].score == 4
    assert failed_evaluations[1].passed is False

    # Verify pass rate is ~33.33% (1 out of 3)
    assert 33.0 <= result.pass_rate <= 34.0


async def test_numeric_mode_basic_async():
    """Test basic async numeric mode evaluation."""
    eval = AgentAsJudgeEval(
        criteria="Response must be helpful",
        scoring_strategy="numeric",
        threshold=7,
    )

    # Mock the evaluator for async
    evaluator = eval.get_evaluator_agent()
    evaluator.model = MagicMock()
    mock_response = NumericJudgeResponse(score=8, reason="Mocked async evaluation.")
    mock_output = RunOutput(content=mock_response)
    evaluator.arun = AsyncMock(return_value=mock_output)
    eval.evaluator_agent = evaluator

    result = await eval.arun(
        input="What is Python?",
        output="Python is a programming language.",
        print_results=False,
    )

    assert result is not None
    assert len(result.results) == 1
    assert result.results[0].score is not None
    assert 1 <= result.results[0].score <= 10
    assert isinstance(result.results[0].passed, bool)


async def test_binary_mode_basic_async():
    """Test basic async binary mode evaluation."""
    eval = AgentAsJudgeEval(
        criteria="Response must not contain personal info",
        scoring_strategy="binary",
    )

    # Mock the evaluator for async
    evaluator = eval.get_evaluator_agent()
    evaluator.model = MagicMock()
    mock_response = BinaryJudgeResponse(passed=True, reason="Mocked async binary evaluation.")
    mock_output = RunOutput(content=mock_response)
    evaluator.arun = AsyncMock(return_value=mock_output)
    eval.evaluator_agent = evaluator

    result = await eval.arun(
        input="Tell me about privacy",
        output="Privacy is important.",
        print_results=False,
    )

    assert result is not None
    assert len(result.results) == 1
    assert result.results[0].score is None  # Binary mode doesn't have scores
    assert isinstance(result.results[0].passed, bool)
