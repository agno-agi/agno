"""Unit tests for ReliabilityEval.

Since 2.8.0 tool evidence comes from executions (`RunOutput.tools`), not message-side
requests: fixtures build `ToolExecution`s, and an expectation is satisfied only by a
clean one (`tool_call_error` not true). The semantics these tests encode -- unordered
name-set matching, duplicates satisfied by one call, subset argument matching,
allow_additional_tool_calls behavior -- predate the rewrite and are preserved.
"""

from unittest.mock import patch

import pytest

from agno.eval.reliability import ReliabilityEval
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput

_ANNOTATION = "(requested but refused/errored — execution matching, new in 2.8.0)"


def _make_execution(name: str, arguments: dict = None, error: bool = None) -> ToolExecution:
    """Helper to create a tool execution."""
    return ToolExecution(tool_call_id=f"call_{name}", tool_name=name, tool_args=arguments, tool_call_error=error)


def _make_response(*tools: ToolExecution) -> RunOutput:
    """Helper to create a RunOutput with tool executions."""
    return RunOutput(content="response", tools=list(tools))


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
        agent_response=_make_response(_make_execution("multiply")),
        expected_tool_calls=["multiply"],
    )
    assert result.eval_status == "PASSED"
    assert result.passed_tool_calls == ["multiply"]


def test_show_spinner_disabled():
    result = _run_eval(
        agent_response=_make_response(_make_execution("multiply")),
        expected_tool_calls=["multiply"],
        show_spinner=False,
    )
    assert result.eval_status == "PASSED"


def test_exact_match_fails_on_unexpected_tool():
    result = _run_eval(
        agent_response=_make_response(_make_execution("multiply"), _make_execution("exponentiate")),
        expected_tool_calls=["multiply"],
    )
    assert result.eval_status == "FAILED"
    assert "exponentiate" in result.failed_tool_calls


def test_fails_on_missing_expected_tool():
    result = _run_eval(
        agent_response=_make_response(_make_execution("multiply")),
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
# Execution matching (new in 2.8.0): refused, errored, and HITL calls
# ---------------------------------------------------------------------------


def test_successful_call_still_passes():
    result = _run_eval(
        agent_response=_make_response(_make_execution("search", error=False)),
        expected_tool_calls=["search"],
    )
    assert result.eval_status == "PASSED"
    assert result.passed_tool_calls == ["search"]


def test_refused_call_no_longer_passes():
    # A call refused by tool_call_limit never produces an execution: the request and
    # the refusal live on messages only. Under request matching this passed.
    response = RunOutput(
        content="done under duress",
        messages=[
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {"id": "call_search", "type": "function", "function": {"name": "search", "arguments": "{}"}}
                ],
            ),
            Message(
                role="tool",
                content="Tool call limit reached. Tool call search not executed.",
                tool_call_id="call_search",
                tool_name="search",
                tool_call_error=True,
            ),
        ],
        tools=[],
    )
    result = _run_eval(agent_response=response, expected_tool_calls=["search"])
    assert result.eval_status == "FAILED"
    assert result.passed_tool_calls == []
    assert any(entry.startswith("search") for entry in result.missing_tool_calls)


def test_errored_execution_no_longer_passes():
    result = _run_eval(
        agent_response=_make_response(_make_execution("search", error=True)),
        expected_tool_calls=["search"],
    )
    assert result.eval_status == "FAILED"
    assert result.passed_tool_calls == []
    assert any(entry.startswith("search") for entry in result.missing_tool_calls)


def test_none_tool_call_error_passes():
    # tool_call_error defaults to None, and a successful execution rehydrated from
    # storage may carry None rather than False.
    result = _run_eval(
        agent_response=_make_response(_make_execution("search", error=None)),
        expected_tool_calls=["search"],
    )
    assert result.eval_status == "PASSED"


def test_approved_hitl_call_still_passes():
    approved = ToolExecution(
        tool_call_id="call_delete",
        tool_name="delete_file",
        requires_confirmation=False,
        confirmed=True,
        tool_call_error=False,
    )
    result = _run_eval(agent_response=_make_response(approved), expected_tool_calls=["delete_file"])
    assert result.eval_status == "PASSED"


def test_rejected_hitl_call_fails():
    # A rejected HITL call produces an execution with tool_call_error=True -- and
    # after the resume neither is_paused nor `requires_confirmation and not confirmed`
    # distinguishes it from an approved call. tool_call_error is the discriminator.
    rejected = ToolExecution(
        tool_call_id="call_delete",
        tool_name="delete_file",
        requires_confirmation=False,
        confirmed=False,
        tool_call_error=True,
    )
    assert rejected.is_paused is False
    assert not (rejected.requires_confirmation and not rejected.confirmed)

    result = _run_eval(agent_response=_make_response(rejected), expected_tool_calls=["delete_file"])
    assert result.eval_status == "FAILED"


def test_retry_that_succeeds_still_passes():
    # An errored execution of an expected tool does not poison the eval: a later
    # clean execution of the same name satisfies the expectation.
    result = _run_eval(
        agent_response=_make_response(_make_execution("search", error=True), _make_execution("search")),
        expected_tool_calls=["search"],
    )
    assert result.eval_status == "PASSED"
    assert result.passed_tool_calls == ["search"]


def test_strict_mode_fails_on_errored_additional_call():
    # Strict mode polices the attempt, not its success: with
    # allow_additional_tool_calls=False, an unexpected call that errored still fails.
    result = _run_eval(
        agent_response=_make_response(_make_execution("multiply"), _make_execution("exponentiate", error=True)),
        expected_tool_calls=["multiply"],
        allow_additional_tool_calls=False,
    )
    assert result.eval_status == "FAILED"
    assert "exponentiate" in result.failed_tool_calls


def test_failure_message_names_execution_matching():
    # When a request existed but no clean execution did, the missing entry must say
    # the eval changed, and assert_passed must carry the evidence in its message.
    response = RunOutput(
        content="done",
        messages=[
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {"id": "call_search", "type": "function", "function": {"name": "search", "arguments": "{}"}}
                ],
            ),
        ],
        tools=[_make_execution("search", error=True)],
    )
    result = _run_eval(agent_response=response, expected_tool_calls=["search"])
    assert result.eval_status == "FAILED"
    assert f"search {_ANNOTATION}" in result.missing_tool_calls

    with pytest.raises(AssertionError) as excinfo:
        result.assert_passed()
    assert "missing_tool_calls" in str(excinfo.value)
    assert _ANNOTATION in str(excinfo.value)

    # A tool that was never requested at all stays a bare name.
    never_requested = _run_eval(
        agent_response=RunOutput(content="no tools"),
        expected_tool_calls=["search"],
    )
    assert never_requested.missing_tool_calls == ["search"]


def test_team_member_executions_matched():
    # Delegated tool calls live on member responses; a leader-only read would lose
    # every one of them.
    from agno.run.team import TeamRunOutput

    member = RunOutput(content="42", tools=[_make_execution("multiply")])
    team_response = TeamRunOutput(
        content="42",
        tools=[_make_execution("delegate_task_to_member")],
        member_responses=[member],
    )
    result = _run_eval(
        team_response=team_response,
        expected_tool_calls=["multiply"],
        allow_additional_tool_calls=True,
    )
    assert result.eval_status == "PASSED"
    assert "multiply" in result.passed_tool_calls


def test_nested_team_member_executions_matched():
    # Members can themselves be teams; a grandchild agent's clean execution satisfies
    # the expectation exactly like a direct member's.
    from agno.run.team import TeamRunOutput

    grandchild = RunOutput(content="42", tools=[_make_execution("multiply")])
    inner_team = TeamRunOutput(content="42", member_responses=[grandchild])
    team_response = TeamRunOutput(content="42", member_responses=[inner_team])
    result = _run_eval(team_response=team_response, expected_tool_calls=["multiply"])
    assert result.eval_status == "PASSED"
    assert result.passed_tool_calls == ["multiply"]
    assert result.missing_tool_calls == []


def test_nested_team_depth_two_delegations_policed_like_depth_zero():
    # An inner leader's own delegation execution is subject to strict mode at every
    # depth, exactly as a depth-0 leader's already is: list it or allow additionals.
    from agno.run.team import TeamRunOutput

    leaf = RunOutput(content="42", tools=[_make_execution("multiply")])
    depth_two_leader = TeamRunOutput(
        content="42",
        tools=[_make_execution("delegate_task_to_member")],
        member_responses=[leaf],
    )
    middle = TeamRunOutput(content="42", member_responses=[depth_two_leader])
    outer = TeamRunOutput(content="42", member_responses=[middle])

    strict = _run_eval(team_response=outer, expected_tool_calls=["multiply"])
    assert strict.eval_status == "FAILED"
    assert "delegate_task_to_member" in strict.failed_tool_calls

    listed = _run_eval(team_response=outer, expected_tool_calls=["multiply", "delegate_task_to_member"])
    assert listed.eval_status == "PASSED"
    assert "multiply" in listed.passed_tool_calls


def test_from_history_requests_ignored():
    # Prior-turn messages injected by add_history_to_context carry tool_calls this
    # run never made; strict mode must not fail today's run over yesterday's tools.
    response = RunOutput(
        content="done",
        tools=[_make_execution("multiply")],
        messages=[
            Message(
                role="assistant",
                content=None,
                from_history=True,
                tool_calls=[{"id": "h1", "type": "function", "function": {"name": "prior_tool", "arguments": "{}"}}],
            ),
        ],
    )
    result = _run_eval(agent_response=response, expected_tool_calls=["multiply"])
    assert result.eval_status == "PASSED"
    assert result.failed_tool_calls == []
    assert result.passed_tool_calls == ["multiply"]


def test_from_history_request_does_not_annotate_missing():
    # A from_history request is not evidence the CURRENT run attempted the tool, so
    # the missing entry stays unannotated.
    response = RunOutput(
        content="no tools this turn",
        tools=[],
        messages=[
            Message(
                role="assistant",
                content=None,
                from_history=True,
                tool_calls=[{"id": "h1", "type": "function", "function": {"name": "search", "arguments": "{}"}}],
            ),
        ],
    )
    result = _run_eval(agent_response=response, expected_tool_calls=["search"])
    assert result.eval_status == "FAILED"
    assert result.missing_tool_calls == ["search"]


# ---------------------------------------------------------------------------
# Subset matching (allow_additional_tool_calls=True)
# ---------------------------------------------------------------------------


def test_subset_matching_passes_with_extra_calls():
    result = _run_eval(
        agent_response=_make_response(_make_execution("multiply"), _make_execution("exponentiate")),
        expected_tool_calls=["multiply"],
        allow_additional_tool_calls=True,
    )
    assert result.eval_status == "PASSED"
    assert result.passed_tool_calls == ["multiply"]
    assert "exponentiate" in result.additional_tool_calls
    assert result.failed_tool_calls == []


def test_subset_matching_still_fails_on_missing():
    result = _run_eval(
        agent_response=_make_response(_make_execution("exponentiate")),
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
        agent_response=_make_response(_make_execution("multiply", {"a": 10, "b": 5})),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10, "b": 5}},
    )
    assert result.eval_status == "PASSED"
    assert "multiply" in result.passed_argument_checks


def test_argument_check_matches_tool_args():
    # Arguments are read from ToolExecution.tool_args -- an already-parsed dict, not
    # the message-side JSON string.
    execution = _make_execution("multiply", {"a": 10, "b": 5})
    assert isinstance(execution.tool_args, dict)
    result = _run_eval(
        agent_response=_make_response(execution),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10}},
    )
    assert result.eval_status == "PASSED"
    assert "multiply" in result.passed_argument_checks


def test_argument_check_ignores_errored_execution():
    # Only clean executions can satisfy an argument spec: matching arguments on an
    # errored execution do not count.
    result = _run_eval(
        agent_response=_make_response(
            _make_execution("multiply", {"a": 10, "b": 5}, error=True),
            _make_execution("multiply", {"a": 1, "b": 1}),
        ),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10, "b": 5}},
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.failed_argument_checks


def test_argument_validation_fails_on_wrong_args():
    result = _run_eval(
        agent_response=_make_response(_make_execution("multiply", {"a": 10, "b": 3})),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10, "b": 5}},
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.failed_argument_checks


def test_argument_validation_partial_match():
    """Only specified args are checked; extra args in the actual call are fine."""
    result = _run_eval(
        agent_response=_make_response(_make_execution("multiply", {"a": 10, "b": 5, "c": 99})),
        expected_tool_calls=["multiply"],
        expected_tool_call_arguments={"multiply": {"a": 10}},
    )
    assert result.eval_status == "PASSED"
    assert "multiply" in result.passed_argument_checks


def test_argument_validation_fails_when_tool_not_called():
    result = _run_eval(
        agent_response=_make_response(_make_execution("add", {"a": 1, "b": 2})),
        expected_tool_call_arguments={"multiply": {"a": 10}},
        allow_additional_tool_calls=True,
    )
    assert result.eval_status == "FAILED"
    assert "multiply" in result.failed_argument_checks


def test_argument_validation_multiple_calls_any_match():
    """If a tool is called multiple times, at least one must match."""
    result = _run_eval(
        agent_response=_make_response(
            _make_execution("multiply", {"a": 1, "b": 2}),
            _make_execution("multiply", {"a": 10, "b": 5}),
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
            _make_execution("add", {"a": 2, "b": 2}),
            _make_execution("add", {"a": 3, "b": 3}),
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
            _make_execution("add", {"a": 2, "b": 2}),
        ),
        expected_tool_calls=["add"],
        expected_tool_call_arguments={
            "add": [{"a": 2, "b": 2}, {"a": 3, "b": 3}],
        },
    )
    assert result.eval_status == "FAILED"
    assert "add" in result.failed_argument_checks


def test_argument_validation_none_arguments():
    """tool_args=None should not crash; it reads as {}."""
    result = _run_eval(
        agent_response=_make_response(_make_execution("multiply", None)),
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
# Multi-execution collection
# ---------------------------------------------------------------------------


def test_collects_all_tool_calls_across_messages():
    """All executions across the run must be collected."""
    response = _make_response(
        _make_execution("add"),
        _make_execution("subtract"),
        _make_execution("multiply"),
    )
    result = _run_eval(
        agent_response=response,
        expected_tool_calls=["add", "subtract", "multiply"],
    )
    assert result.eval_status == "PASSED"
    assert result.missing_tool_calls == []


def test_does_not_mutate_original_messages():
    """Eval must not mutate the original RunOutput."""
    response = _make_response(_make_execution("add"), _make_execution("multiply"))
    original_tools = list(response.tools)
    original_args = [t.tool_args for t in response.tools]

    _run_eval(agent_response=response, expected_tool_calls=["add", "multiply"])

    assert response.tools == original_tools
    assert [t.tool_args for t in response.tools] == original_args


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_missing_tool_not_double_counted_in_arg_checks():
    """If a tool is missing, don't also add it to failed_argument_checks."""
    result = _run_eval(
        agent_response=_make_response(_make_execution("add", {"a": 1})),
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
            _make_execution("multiply", {"a": 10, "b": 5}),
            _make_execution("exponentiate", {"base": 50, "exp": 2}),
        ),
        expected_tool_calls=["multiply"],
        allow_additional_tool_calls=True,
        expected_tool_call_arguments={"multiply": {"a": 10, "b": 5}},
    )
    assert result.eval_status == "PASSED"
    assert "multiply" in result.passed_tool_calls
    assert "exponentiate" in result.additional_tool_calls
    assert "multiply" in result.passed_argument_checks


def test_strict_mode_fails_on_refused_additional_call():
    # A call refused by tool_call_limit never produces an execution: the request is
    # its only trace. Strict mode polices the attempt whether or not it executed.
    response = RunOutput(
        content="done",
        messages=[
            Message(
                role="assistant",
                content=None,
                tool_calls=[
                    {"id": "c1", "type": "function", "function": {"name": "search", "arguments": "{}"}},
                    {"id": "c2", "type": "function", "function": {"name": "delete_db", "arguments": "{}"}},
                ],
            ),
            Message(
                role="tool",
                content="Tool call limit reached. Tool call delete_db not executed.",
                tool_call_id="c2",
                tool_name="delete_db",
                tool_call_error=True,
            ),
        ],
        tools=[_make_execution("search")],
    )

    strict = _run_eval(agent_response=response, expected_tool_calls=["search"], allow_additional_tool_calls=False)
    assert strict.eval_status == "FAILED"
    assert "delete_db" in strict.failed_tool_calls

    # Lenient mode keeps the refused attempt visible as an additional call.
    lenient = _run_eval(agent_response=response, expected_tool_calls=["search"], allow_additional_tool_calls=True)
    assert lenient.eval_status == "PASSED"
    assert "delete_db" in lenient.additional_tool_calls


# ---------------------------------------------------------------------------
# Preserved semantics pinned explicitly (plan R4: duplicates and per-call shape)
# ---------------------------------------------------------------------------


def test_duplicate_expected_names_satisfied_by_one_call():
    # Set semantics, preserved from the request-matching era: expecting the same
    # name twice is satisfied by a single clean execution.
    result = _run_eval(
        agent_response=_make_response(_make_execution("search")),
        expected_tool_calls=["search", "search"],
    )
    assert result.eval_status == "PASSED"
    assert result.passed_tool_calls == ["search"]


def test_passed_tool_calls_keeps_one_entry_per_execution():
    # The per-call shape is a db contract (the asdict payload is logged): two clean
    # executions of one expected name yield two entries, not a deduped set.
    result = _run_eval(
        agent_response=_make_response(_make_execution("search"), _make_execution("search")),
        expected_tool_calls=["search"],
    )
    assert result.eval_status == "PASSED"
    assert result.passed_tool_calls == ["search", "search"]


def test_still_paused_call_fails():
    # A still-paused call (awaiting confirmation, never resumed) has tool_call_error=None
    # but is_paused=True -- it never executed, so it must not satisfy the expectation.
    paused = ToolExecution(
        tool_call_id="call_delete_file",
        tool_name="delete_file",
        requires_confirmation=True,
        confirmed=None,
        tool_call_error=None,
    )
    assert paused.is_paused is True
    result = _run_eval(
        agent_response=_make_response(paused),
        expected_tool_calls=["delete_file"],
    )
    assert result.eval_status == "FAILED"
    # The expected tool is reported missing (annotated), and -- since the per-call loop
    # excludes still-paused calls -- it is NOT also in passed_tool_calls (no
    # self-contradictory payload).
    assert any("delete_file" in entry for entry in result.missing_tool_calls)
    assert "delete_file" not in result.passed_tool_calls
