import asyncio
from copy import deepcopy
from typing import Any

import pytest

from agno.agent import Agent
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team import Team


def test_delegated_member_merges_nested_session_state_after_run(monkeypatch: pytest.MonkeyPatch):
    parent_state = {"nested": {"values": {}}}
    run_context = RunContext(run_id="team-run", session_id="session", session_state=parent_state)
    parent_state_during_member_run: dict[str, Any] = {}
    member = Agent(id="member", name="member")

    def fake_run(*args: Any, session_state: dict[str, Any], **kwargs: Any) -> RunOutput:
        session_state["nested"]["values"]["member"] = True
        parent_state_during_member_run.update(deepcopy(parent_state))
        return RunOutput(run_id="member-run", agent_id="member", content="done")

    monkeypatch.setattr(member, "run", fake_run)
    team = Team(name="test-team", members=[member])
    delegate = team._get_delegate_task_function(
        session=TeamSession(session_id="session"),
        run_response=TeamRunOutput(run_id="team-run", session_id="session"),
        run_context=run_context,
        team_run_context={},
    )

    responses = list(delegate.entrypoint(member_id="member", task="work"))

    assert responses == ["done"]
    assert parent_state_during_member_run == {"nested": {"values": {}}}
    assert parent_state == {"nested": {"values": {"member": True}}}


@pytest.mark.asyncio
async def test_parallel_delegated_members_do_not_share_nested_session_state(monkeypatch: pytest.MonkeyPatch):
    parent_state = {"nested": {"values": {}}}
    run_context = RunContext(run_id="team-run", session_id="session", session_state=parent_state)
    member_states: dict[str, dict[str, Any]] = {}
    parent_snapshots: list[dict[str, Any]] = []
    members_ready = asyncio.Event()
    mutations_recorded = asyncio.Event()

    def make_member(member_id: str) -> Agent:
        member = Agent(id=member_id, name=member_id)

        async def fake_arun(*args: Any, session_state: dict[str, Any], **kwargs: Any) -> RunOutput:
            member_states[member_id] = session_state
            if len(member_states) == 2:
                members_ready.set()
            await members_ready.wait()

            session_state["nested"]["values"][member_id] = True
            parent_snapshots.append(deepcopy(parent_state))
            if len(parent_snapshots) == 2:
                mutations_recorded.set()
            await mutations_recorded.wait()
            return RunOutput(run_id=f"{member_id}-run", agent_id=member_id, content="done")

        monkeypatch.setattr(member, "arun", fake_arun)
        return member

    members = [make_member("member-1"), make_member("member-2")]
    team = Team(name="test-team", members=members, delegate_to_all_members=True)
    delegate = team._get_delegate_task_function(
        session=TeamSession(session_id="session"),
        run_response=TeamRunOutput(run_id="team-run", session_id="session"),
        run_context=run_context,
        team_run_context={},
        async_mode=True,
    )

    responses = [response async for response in delegate.entrypoint(task="work")]

    assert len(responses) == 2
    assert member_states["member-1"]["nested"] is not member_states["member-2"]["nested"]
    assert member_states["member-1"] == {"nested": {"values": {"member-1": True}}}
    assert member_states["member-2"] == {"nested": {"values": {"member-2": True}}}
    assert parent_snapshots == [{"nested": {"values": {}}}, {"nested": {"values": {}}}]
    assert parent_state == {"nested": {"values": {"member-1": True, "member-2": True}}}
