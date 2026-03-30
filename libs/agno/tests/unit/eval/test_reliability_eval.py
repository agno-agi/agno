"""Unit tests for ReliabilityEval"""

from unittest.mock import patch

from agno.eval.reliability import ReliabilityEval
from agno.models.message import Message
from agno.run.agent import RunOutput


def _make_tool_call(name: str, arguments: str = "{}") -> dict:
    """Helper to create a tool call dict."""
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": arguments}}


def _make_response(*tool_calls: dict) -> RunOutput:
    """Helper to create a RunOutput with tool calls in a single message."""
    mock_message = Message(role="assistant", content="response", tool_calls=list(tool_calls))
    return RunOutput(content="response", messages=[mock_message])


def _run_eval(**kwargs) -> "ReliabilityEval":
    """Helper to run a ReliabilityEval with telemetry mocked out."""
    with patch("agno.api.evals.create_eval_run_telemetry"):
        result = ReliabilityEval(**kwargs).run(print_results=False)
    return result


# ---------------------------------------------------------------------------
# Exact match (default behavior)
# ---------------------------------------------------------------------------


def test_exact_match_passes():
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("multiply")),
        expected_tool_calls=["multiply"],
    )
    assert result.eval_status == "PASSED"
    assert result.passed_tool_calls == ["multiply"]


def test_exact_match_fails_on_unexpected_tool():
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("multiply"), _make_tool_call("exponentiate")),
        expected_tool_calls=["multiply"],
    )
    assert result.eval_status == "FAILED"
    assert "exponentiate" in result.failed_tool_calls


def test_fails_on_missing_expected_tool():
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("multiply")),
        expected_tool_calls=["multiply", "exponentiate"],
    )
    assert result.eval_status == "FAILED"
    assert "exponentiate" in result.missing_tool_calls


def test_fails_when_no_tools_called():
    response = RunOutput(content="no tools", messages=[Message(role="assistant", content="no tools")])
    result = _run_eval(
        agent_response=response,
        expected_tool_calls=["multiply"],
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.missing_tool_calls


# ---------------------------------------------------------------------------
# Subset matching (allow_additional_tool_calls=True)
# ---------------------------------------------------------------------------


def test_subset_matching_passes_with_extra_calls():
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("multiply"), _make_tool_call("exponentiate")),
        expected_tool_calls=["multiply"],
        allow_additional_tool_calls=True,
    )
    assert result.eval_status == "PASSED"
    assert result.passed_tool_calls == ["multiply"]
    assert "exponentiate" in result.additional_tool_calls
    assert result.failed_tool_calls == []


def test_subset_matching_still_fails_on_missing():
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("exponentiate")),
        expected_tool_calls=["multiply"],
        allow_additional_tool_calls=True,
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.missing_tool_calls


# ---------------------------------------------------------------------------
# Argument validation (expected_tool_call_arguments)
# ---------------------------------------------------------------------------


def test_argument_validation_passes():
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("multiply", '{"a": 10, "b": 5}')),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10, "b": 5}},
    )
    assert result.eval_status == "PASSED"
    assert "multiply" in result.passed_argument_checks


def test_argument_validation_fails_on_wrong_args():
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("multiply", '{"a": 10, "b": 3}')),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10, "b": 5}},
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.failed_argument_checks


def test_argument_validation_partial_match():
    """Only specified args are checked; extra args in the actual call are fine."""
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("multiply", '{"a": 10, "b": 5, "c": 99}')),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10}},
    )
    assert result.eval_status == "PASSED"
    assert "multiply" in result.passed_argument_checks


def test_argument_validation_fails_when_tool_not_called():
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("add", '{"a": 1, "b": 2}')),
        expected_tool_call_arguments={"multiply": {"a": 10}},
        allow_additional_tool_calls=True,
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.failed_argument_checks


def test_argument_validation_multiple_calls_any_match():
    """If a tool is called multiple times, at least one must match."""
    result = _run_eval(
        agent_response=_make_response(
            _make_tool_call("multiply", '{"a": 1, "b": 2}'),
            _make_tool_call("multiply", '{"a": 10, "b": 5}'),
        ),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10, "b": 5}},
    )
    assert result.eval_status == "PASSED"
    assert "multiply" in result.passed_argument_checks


def test_argument_validation_multiple_specs():
    """List of specs: each spec must match at least one call."""
    result = _run_eval(
        agent_response=_make_response(
            _make_tool_call("add", '{"a": 2, "b": 2}'),
            _make_tool_call("add", '{"a": 3, "b": 3}'),
        ),
        expected_tool_calls=["add"],
        expected_tool_call_arguments={
            "add": [{"a": 2, "b": 2}, {"a": 3, "b": 3}],
        },
    )
    assert result.eval_status == "PASSED"
    assert "add" in result.passed_argument_checks


def test_argument_validation_multiple_specs_one_missing():
    """If one spec has no matching call, it fails."""
    result = _run_eval(
        agent_response=_make_response(
            _make_tool_call("add", '{"a": 2, "b": 2}'),
        ),
        expected_tool_calls=["add"],
        expected_tool_call_arguments={
            "add": [{"a": 2, "b": 2}, {"a": 3, "b": 3}],
        },
    )
    assert result.eval_status == "FAILED"
    assert "add" in result.failed_argument_checks


def test_argument_validation_none_arguments():
    """arguments=None should not crash."""
    tc = {"id": "call_1", "type": "function", "function": {"name": "multiply", "arguments": None}}
    response = RunOutput(content="response", messages=[Message(role="assistant", content="response", tool_calls=[tc])])
    result = _run_eval(
        agent_response=response,
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10}},
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.failed_argument_checks


def test_argument_validation_fails_when_no_tools_called():
    """Arg checks should fail, not be silently skipped, when no tools are called."""
    response = RunOutput(content="no tools", messages=[Message(role="assistant", content="no tools")])
    result = _run_eval(
        agent_response=response,
        expected_tool_call_arguments={"multiply": {"a": 10}},
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.failed_argument_checks


# ---------------------------------------------------------------------------
# Multi-message tool call collection
# ---------------------------------------------------------------------------


def test_collects_all_tool_calls_across_messages():
    """All tool calls from all messages must be collected."""
    messages = [
        Message(role="assistant", content="r1", tool_calls=[_make_tool_call("add"), _make_tool_call("subtract")]),
        Message(role="assistant", content="r2", tool_calls=[_make_tool_call("multiply")]),
    ]
    response = RunOutput(content="response", messages=messages)
    result = _run_eval(
        agent_response=response,
        expected_tool_calls=["add", "subtract", "multiply"],
    )
    assert result.eval_status == "PASSED"
    assert result.missing_tool_calls == []


def test_does_not_mutate_original_messages():
    """Eval must not mutate the original RunOutput messages."""
    msg1 = Message(role="assistant", content="r1", tool_calls=[_make_tool_call("add")])
    msg2 = Message(role="assistant", content="r2", tool_calls=[_make_tool_call("multiply")])
    response = RunOutput(content="response", messages=[msg1, msg2])

    original_len1 = len(msg1.tool_calls)
    original_len2 = len(msg2.tool_calls)

    _run_eval(agent_response=response, expected_tool_calls=["add", "multiply"])

    assert len(msg1.tool_calls) == original_len1
    assert len(msg2.tool_calls) == original_len2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_missing_tool_not_double_counted_in_arg_checks():
    """If a tool is missing, don't also add it to failed_argument_checks."""
    result = _run_eval(
        agent_response=_make_response(_make_tool_call("add", '{"a": 1}')),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10}},
        allow_additional_tool_calls=True,
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.missing_tool_calls
    assert "multiply" not in result.failed_argument_checks


def test_combined_subset_and_argument_check():
    result = _run_eval(
        agent_response=_make_response(
            _make_tool_call("multiply", '{"a": 10, "b": 5}'),
            _make_tool_call("exponentiate", '{"base": 50, "exp": 2}'),
        ),
        expected_tool_calls=["multiply"],
        allow_additional_tool_calls=True,
        expected_tool_call_arguments={"multiply": {"a": 10, "b": 5}},
    )
    assert result.eval_status == "PASSED"
    assert "multiply" in result.passed_tool_calls
    assert "exponentiate" in result.additional_tool_calls
    assert "multiply" in result.passed_argument_checks
