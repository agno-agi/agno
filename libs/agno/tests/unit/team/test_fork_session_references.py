"""Verify that run identities and references remain consistent when a session is forked."""

from copy import deepcopy

import pytest

from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._run import _build_forked_team_session


def _paused_session() -> TeamSession:
    approval = RunRequirement(
        id="approval-1",
        tool_execution=ToolExecution(tool_call_id="call-1", tool_name="publish", requires_confirmation=True),
    )
    leaf = RunOutput(
        run_id="leaf-run",
        agent_id="worker",
        session_id="source",
        parent_run_id="inner-run",
        status=RunStatus.paused,
        requirements=[approval],
    )
    member_approval = deepcopy(approval)
    member_approval.member_agent_id = "worker"
    member_approval.member_run_id = leaf.run_id
    member_approval._member_run_response = leaf
    inner = TeamRunOutput(
        run_id="inner-run",
        team_id="inner",
        session_id="source",
        parent_run_id="root-run",
        status=RunStatus.paused,
        member_responses=[leaf],
        requirements=[member_approval],
        tools=[ToolExecution(tool_call_id="delegate-leaf", child_run_id=leaf.run_id)],
    )
    root_approval = deepcopy(member_approval)
    root_approval._member_run_response = inner
    root = TeamRunOutput(
        run_id="root-run",
        team_id="root",
        session_id="source",
        parent_run_id="external-workflow-run",
        status=RunStatus.paused,
        member_responses=[inner],
        requirements=[root_approval],
        tools=[ToolExecution(tool_call_id="delegate-inner", child_run_id=inner.run_id)],
    )
    # After database deserialization, nested and independently stored representations of one run are different objects.
    return TeamSession(session_id="source", team_id="root", runs=[root, deepcopy(leaf), deepcopy(inner)])


@pytest.mark.parametrize("round_trip", [False, True])
def test_fork_rewrites_nested_and_sibling_run_references(round_trip):
    source = _paused_session()
    if round_trip:
        source = TeamSession.from_dict(source.to_dict())
    before = source.to_dict()

    forked = _build_forked_team_session(source, new_user_id=None)
    root, sibling_leaf, sibling_inner = forked.runs
    inner = root.member_responses[0]
    leaf = inner.member_responses[0]

    assert {root.run_id, inner.run_id, leaf.run_id}.isdisjoint({"root-run", "inner-run", "leaf-run"})
    assert len({root.run_id, inner.run_id, leaf.run_id}) == 3
    assert inner.run_id == sibling_inner.run_id
    assert leaf.run_id == sibling_leaf.run_id == sibling_inner.member_responses[0].run_id
    assert leaf.parent_run_id == sibling_leaf.parent_run_id == inner.run_id
    assert inner.parent_run_id == sibling_inner.parent_run_id == root.run_id
    for run in [root, inner, leaf, sibling_leaf, sibling_inner, sibling_inner.member_responses[0]]:
        assert run.session_id == forked.session_id
        assert run.status == RunStatus.paused
        assert run.forked_from_session_id == "source"
    for run in [root, inner, sibling_inner]:
        assert run.requirements[0].member_run_id == leaf.run_id
        assert run.requirements[0].member_agent_id == "worker"
        assert run.requirements[0].id == "approval-1"
        assert run.requirements[0].tool_execution.tool_call_id == "call-1"
    assert root.tools[0].child_run_id == inner.run_id
    assert inner.tools[0].child_run_id == leaf.run_id
    assert root.parent_run_id == "external-workflow-run"
    assert source.to_dict() == before


def test_fork_rewrites_cached_member_outputs_and_shared_objects_once():
    source = _paused_session()
    root = source.runs[0]
    inner = root.member_responses[0]
    leaf = inner.member_responses[0]
    # An in-process cache may be the only place that retains a member run, or it may share objects with stored rows.
    root.member_responses = []
    source.runs = [root, leaf]

    forked = _build_forked_team_session(source, new_user_id=None)
    forked_root, forked_leaf = forked.runs
    cached_inner = forked_root.requirements[0]._member_run_response
    cached_leaf = cached_inner.requirements[0]._member_run_response

    assert cached_leaf is forked_leaf
    assert cached_inner.run_id != "inner-run"
    assert cached_leaf.run_id != "leaf-run"
    assert cached_inner.parent_run_id == forked_root.run_id
    assert cached_leaf.parent_run_id == cached_inner.run_id
    assert forked_root.requirements[0].member_run_id == forked_leaf.run_id
    assert cached_inner.session_id == cached_leaf.session_id == forked.session_id
    assert inner.run_id == "inner-run"
    assert leaf.run_id == "leaf-run"


def test_refork_preserves_origin_but_allocates_independent_run_ids():
    first = _build_forked_team_session(_paused_session(), new_user_id="owner")
    second = _build_forked_team_session(first, new_user_id=None)
    first_root = first.runs[0]
    second_root = second.runs[0]
    first_leaf = first_root.member_responses[0].member_responses[0]
    second_leaf = second_root.member_responses[0].member_responses[0]

    assert second.session_data["forked_from_session_id"] == first.session_id
    assert second.user_id == "owner"
    assert second_leaf.forked_from_session_id == "source"
    assert second_leaf.run_id != first_leaf.run_id
    assert second_root.requirements[0].member_run_id == second_leaf.run_id
    assert first_root.requirements[0].member_run_id == first_leaf.run_id
