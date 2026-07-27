"""Unit tests for ToolCallScorer: execution matching, HITL cases, argument subsets."""

import pytest

from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.scorer import ToolCallScorer


def _run_with(*tools: ToolExecution) -> RunOutput:
    return RunOutput(content="done", tools=list(tools))


def test_tool_call_scorer_counts_approved_hitl():
    # An approved-and-executed HITL call: requires_confirmation cleared, confirmed
    # True, tool_call_error falsy. It counts.
    run = _run_with(
        ToolExecution(tool_name="delete_file", requires_confirmation=False, confirmed=True, tool_call_error=False)
    )
    result = ToolCallScorer(["delete_file"]).score(run)
    assert result.passed is True
    assert result.value == 1.0


def test_tool_call_scorer_rejects_rejected_hitl():
    # A rejected HITL call produces a ToolExecution with tool_call_error=True -- and
    # both is_paused and `requires_confirmation and not confirmed` are false for it,
    # so tool_call_error is the only discriminator that catches it.
    rejected = ToolExecution(
        tool_name="delete_file", requires_confirmation=False, confirmed=False, tool_call_error=True
    )
    assert rejected.is_paused is False
    assert not (rejected.requires_confirmation and not rejected.confirmed)

    result = ToolCallScorer(["delete_file"]).score(_run_with(rejected))
    assert result.passed is False
    assert result.value == 0.0


def test_tool_call_scorer_none_error_counts_as_success():
    # tool_call_error defaults to None, and a successful execution rehydrated from
    # storage may carry None rather than False. `not t.tool_call_error`, never `== False`.
    run = _run_with(ToolExecution(tool_name="search", tool_call_error=None))
    result = ToolCallScorer(["search"]).score(run)
    assert result.passed is True


def test_tool_call_scorer_rejects_refused():
    # A call refused by tool_call_limit never produces a ToolExecution: the refusal
    # exists only as a message-side tool_call_error. Matching on run.tools excludes it.
    refusal_message = Message(
        role="tool",
        content="Tool call limit reached. Tool call search not executed.",
        tool_call_id="call_search",
        tool_name="search",
        tool_call_error=True,
    )
    run = RunOutput(content="done", messages=[refusal_message], tools=None)
    result = ToolCallScorer(["search"]).score(run)
    assert result.passed is False


def test_tool_call_scorer_rejects_errored():
    run = _run_with(ToolExecution(tool_name="search", tool_call_error=True))
    result = ToolCallScorer(["search"]).score(run)
    assert result.passed is False


def test_tool_call_scorer_argument_subset():
    run = _run_with(ToolExecution(tool_name="search", tool_args={"query": "agno", "limit": 5}))

    # Expected keys must match by equality; extra actual keys are allowed.
    assert ToolCallScorer(["search"], arguments={"search": {"query": "agno"}}).score(run).passed is True
    assert ToolCallScorer(["search"], arguments={"search": {"query": "other"}}).score(run).passed is False
    # No type coercion: "5" does not match 5.
    typed = _run_with(ToolExecution(tool_name="search", tool_args={"limit": "5"}))
    assert ToolCallScorer(["search"], arguments={"search": {"limit": 5}}).score(typed).passed is False
    # An errored execution cannot satisfy an argument spec.
    errored = _run_with(ToolExecution(tool_name="search", tool_args={"query": "agno"}, tool_call_error=True))
    assert ToolCallScorer(["search"], arguments={"search": {"query": "agno"}}).score(errored).passed is False


def test_tool_call_scorer_no_tools_scores_zero():
    result = ToolCallScorer(["search"]).score(RunOutput(content="no tools", tools=None))
    assert result.value == 0.0
    assert result.passed is False
    assert result.reason is not None


def test_tool_call_scorer_value_is_fraction_of_checks():
    # Name expectations and argument specs are equally weighted checks.
    run = _run_with(ToolExecution(tool_name="search", tool_args={"query": "agno"}))
    result = ToolCallScorer(["search", "summarize"], arguments={"search": {"query": "agno"}}).score(run)
    assert result.value == pytest.approx(2 / 3)
    assert result.passed is False


def test_tool_call_scorer_set_semantics_and_additional():
    # Duplicate expected names are satisfied by a single call; extra clean calls fail
    # only under allow_additional=False, and only `passed` -- never `value`.
    run = _run_with(ToolExecution(tool_name="search"), ToolExecution(tool_name="summarize"))
    assert ToolCallScorer(["search", "search"]).score(run).passed is True

    strict = ToolCallScorer(["search"], allow_additional=False).score(run)
    assert strict.value == 1.0
    assert strict.passed is False
    assert "additional" in (strict.reason or "")

    relaxed = ToolCallScorer(["search"]).score(run)
    assert relaxed.passed is True


def test_tool_call_scorer_ignores_per_task_expected():
    # Tool expectations live on the constructor; the protocol's per-task expected is
    # a different thing and this scorer ignores it.
    run = _run_with(ToolExecution(tool_name="search"))
    result = ToolCallScorer(["search"]).score(run, expected=["something", "else"])
    assert result.passed is True


def test_tool_call_scorer_team_top_level_only():
    # Only the leader's executions are inspected; member tools are named as a
    # limitation in the reason rather than silently under-scoring.
    member = RunOutput(content="42", tools=[ToolExecution(tool_name="multiply")])
    team_run = TeamRunOutput(
        content="42",
        tools=[ToolExecution(tool_name="delegate_task_to_member")],
        member_responses=[member],
    )
    result = ToolCallScorer(["multiply"]).score(team_run)
    assert result.passed is False
    assert "member" in (result.reason or "")


def test_tool_call_scorer_nested_team_members_named_in_reason():
    # A member can itself be a sub-team whose leader ran no tools while its own
    # members did; the limitation note must fire for that nesting too.
    grand_member = RunOutput(content="42", tools=[ToolExecution(tool_name="multiply")])
    sub_team = TeamRunOutput(content="42", tools=None, member_responses=[grand_member])
    team_run = TeamRunOutput(
        content="42",
        tools=[ToolExecution(tool_name="delegate_task_to_member")],
        member_responses=[sub_team],
    )
    result = ToolCallScorer(["multiply"]).score(team_run)
    assert result.passed is False
    assert "member" in (result.reason or "")


def test_tool_call_scorer_requires_a_check():
    with pytest.raises(ValueError, match="expected_tools"):
        ToolCallScorer([])
    # A truthy arguments dict whose spec lists are empty contributes zero checks --
    # it must not construct a scorer that vacuously greens every run.
    with pytest.raises(ValueError, match="empty"):
        ToolCallScorer([], arguments={"search": []})
    # A bare string would be exploded into per-character expectations.
    with pytest.raises(TypeError, match="bare string"):
        ToolCallScorer("search")


def test_tool_call_scorer_arguments_only_strict_mode_satisfiable():
    # A tool named only in `arguments` is a required check, not an "additional" call:
    # an arguments-only strict scorer must pass a run containing exactly that call.
    run = _run_with(ToolExecution(tool_name="search", tool_args={"query": "agno"}))
    result = ToolCallScorer([], arguments={"search": {"query": "agno"}}, allow_additional=False).score(run)
    assert result.passed is True
    assert result.value == 1.0

    # A genuinely unrelated clean call still fails strict mode.
    with_extra = _run_with(
        ToolExecution(tool_name="search", tool_args={"query": "agno"}),
        ToolExecution(tool_name="summarize"),
    )
    strict = ToolCallScorer([], arguments={"search": {"query": "agno"}}, allow_additional=False).score(with_extra)
    assert strict.passed is False


def test_tool_call_scorer_rejects_still_paused():
    # A still-paused call (awaiting confirmation, never resumed) has tool_call_error=None
    # but is_paused=True -- it never executed, so it must not satisfy the expectation.
    paused = ToolExecution(tool_name="delete_file", requires_confirmation=True, confirmed=None, tool_call_error=None)
    assert paused.is_paused is True

    result = ToolCallScorer(["delete_file"]).score(_run_with(paused))
    assert result.passed is False
    assert result.value == 0.0
