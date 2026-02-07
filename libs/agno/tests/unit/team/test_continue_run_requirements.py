import pytest

from agno.agent import Agent
from agno.models.response import ToolExecution
from agno.run import RunStatus
from agno.run.agent import RunOutput
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team import _run
from agno.team._tools import _propagate_member_pause
from agno.tools.function import UserInputField
from agno.utils.team import get_member_id


def _make_requirement(tool_call_id: str, **kwargs) -> RunRequirement:
    return RunRequirement(
        tool_execution=ToolExecution(
            tool_call_id=tool_call_id,
            tool_name="test_tool",
            tool_args={},
            requires_confirmation=True,
            **kwargs,
        )
    )


def test_propagate_still_paused_member_requirements_from_agent():
    team_run = TeamRunOutput(run_id="team_run")
    req = _make_requirement("tool_1")
    paused_member = RunOutput(
        run_id="agent_run_1",
        agent_id="agent_1",
        agent_name="MemberAgent",
        status=RunStatus.paused,
        requirements=[req],
    )

    _run._propagate_still_paused_member_requirements(team_run, {"MemberAgent": paused_member})

    assert team_run.requirements is not None
    assert len(team_run.requirements) == 1
    propagated_req = team_run.requirements[0]
    assert propagated_req.member_agent_id == "agent_1"
    assert propagated_req.member_agent_name == "MemberAgent"
    assert propagated_req.member_run_id == "agent_run_1"


def test_propagate_still_paused_member_requirements_from_subteam():
    team_run = TeamRunOutput(run_id="team_run")
    req = _make_requirement("tool_2")
    paused_subteam = TeamRunOutput(
        run_id="subteam_run_1",
        team_id="subteam_1",
        team_name="ResearchSubteam",
        status=RunStatus.paused,
        requirements=[req],
    )

    _run._propagate_still_paused_member_requirements(team_run, {"ResearchSubteam": paused_subteam})

    assert team_run.requirements is not None
    assert len(team_run.requirements) == 1
    propagated_req = team_run.requirements[0]
    assert propagated_req.member_agent_id == "subteam_1"
    assert propagated_req.member_agent_name == "ResearchSubteam"
    assert propagated_req.member_run_id == "subteam_run_1"


def test_propagate_still_paused_member_requirements_replaces_stale_requirements():
    stale_req = _make_requirement("stale_tool")
    stale_req.member_agent_id = "stale_member"
    team_run = TeamRunOutput(run_id="team_run", requirements=[stale_req])

    fresh_req = _make_requirement("fresh_tool")
    paused_member = RunOutput(
        run_id="agent_run_2",
        agent_id="agent_2",
        agent_name="FreshMember",
        status=RunStatus.paused,
        requirements=[fresh_req],
    )

    _run._propagate_still_paused_member_requirements(team_run, {"FreshMember": paused_member})

    assert team_run.requirements is not None
    assert len(team_run.requirements) == 1
    assert team_run.requirements[0].tool_execution.tool_call_id == "fresh_tool"
    assert team_run.requirements[0].member_agent_id == "agent_2"


# ---------------------------------------------------------------------------
# _propagate_member_pause tests
# ---------------------------------------------------------------------------


def test_propagate_member_pause_sets_member_id_from_agent():
    """Verify _propagate_member_pause uses get_member_id correctly for Agent members."""
    team_run = TeamRunOutput(run_id="team_run")
    member_agent = Agent(name="WeatherAgent")
    req = _make_requirement("tc_1")
    member_run = RunOutput(
        run_id="member_run_1",
        status=RunStatus.paused,
        requirements=[req],
    )

    _propagate_member_pause(team_run, member_agent, member_run)

    assert team_run.requirements is not None
    assert len(team_run.requirements) == 1
    propagated = team_run.requirements[0]
    # member_agent_id should be derived from the agent's name/id, not None
    assert propagated.member_agent_id is not None
    assert propagated.member_agent_name == "WeatherAgent"
    assert propagated.member_run_id == "member_run_1"


def test_propagate_member_pause_does_not_mutate_original_requirements():
    """Verify _propagate_member_pause copies requirements instead of mutating originals."""
    team_run = TeamRunOutput(run_id="team_run")
    member_agent = Agent(name="TestAgent")
    req = _make_requirement("tc_2")
    member_run = RunOutput(
        run_id="member_run_2",
        status=RunStatus.paused,
        requirements=[req],
    )

    _propagate_member_pause(team_run, member_agent, member_run)

    # Original requirement on member_run should not have member context set
    assert req.member_agent_id is None
    assert req.member_agent_name is None
    assert req.member_run_id is None
    # But the team's copy should have it
    assert team_run.requirements[0].member_agent_id is not None


def test_propagate_member_pause_empty_requirements():
    """Verify _propagate_member_pause is a no-op when member has no requirements."""
    team_run = TeamRunOutput(run_id="team_run")
    member_agent = Agent(name="TestAgent")
    member_run = RunOutput(run_id="member_run_3", status=RunStatus.paused, requirements=[])

    _propagate_member_pause(team_run, member_agent, member_run)

    assert team_run.requirements is None


def test_propagate_member_pause_multiple_requirements():
    """Verify _propagate_member_pause handles multiple requirements."""
    team_run = TeamRunOutput(run_id="team_run")
    member_agent = Agent(name="MultiAgent")
    req1 = _make_requirement("tc_a")
    req2 = _make_requirement("tc_b")
    member_run = RunOutput(
        run_id="member_run_4",
        status=RunStatus.paused,
        requirements=[req1, req2],
    )

    _propagate_member_pause(team_run, member_agent, member_run)

    assert team_run.requirements is not None
    assert len(team_run.requirements) == 2
    for prop_req in team_run.requirements:
        assert prop_req.member_agent_name == "MultiAgent"
        assert prop_req.member_run_id == "member_run_4"


# ---------------------------------------------------------------------------
# Nested team routing context preservation
# ---------------------------------------------------------------------------


def test_propagate_member_pause_preserves_leaf_routing_context_for_subteams():
    """Verify nested-team propagation keeps existing leaf member routing context."""
    from agno.team.team import Team

    team_run = TeamRunOutput(run_id="top_run")
    leaf_agent = Agent(name="LeafAgent", id="leaf_1")
    subteam = Team(name="ResearchSubteam", id="subteam_1", members=[leaf_agent], telemetry=False)

    leaf_req = _make_requirement("tc_nested_pause")
    leaf_req.member_agent_id = get_member_id(leaf_agent)
    leaf_req.member_agent_name = leaf_agent.name
    leaf_req.member_run_id = "leaf_run_1"
    paused_subteam = TeamRunOutput(
        run_id="subteam_run_1",
        team_id=subteam.id,
        team_name=subteam.name,
        status=RunStatus.paused,
        requirements=[leaf_req],
    )

    _propagate_member_pause(team_run, subteam, paused_subteam)

    assert team_run.requirements is not None
    propagated = team_run.requirements[0]
    assert propagated.member_agent_id == get_member_id(leaf_agent)
    assert propagated.member_agent_name == "LeafAgent"
    assert propagated.member_run_id == "leaf_run_1"


def test_propagate_still_paused_preserves_leaf_routing_context_for_subteams():
    """Verify chained nested-team propagation keeps existing leaf member routing context."""
    team_run = TeamRunOutput(run_id="top_run")

    leaf_req = _make_requirement("tc_nested_still")
    leaf_req.member_agent_id = "leaf-1"
    leaf_req.member_agent_name = "LeafAgent"
    leaf_req.member_run_id = "leaf_run_2"
    paused_subteam = TeamRunOutput(
        run_id="subteam_run_2",
        team_id="subteam_1",
        team_name="ResearchSubteam",
        status=RunStatus.paused,
        requirements=[leaf_req],
    )

    _run._propagate_still_paused_member_requirements(team_run, {"ResearchSubteam": paused_subteam})

    assert team_run.requirements is not None
    propagated = team_run.requirements[0]
    assert propagated.member_agent_id == "leaf-1"
    assert propagated.member_agent_name == "LeafAgent"
    assert propagated.member_run_id == "leaf_run_2"


def test_nested_team_continue_run_routing_succeeds_sync():
    """Verify nested-team HITL requirements route top->subteam->leaf in sync continuation."""
    from agno.team.team import Team

    leaf_agent = Agent(name="LeafAgent", id="leaf_1")
    subteam = Team(name="ResearchSubteam", id="subteam_1", members=[leaf_agent], telemetry=False)
    top_team = Team(name="TopTeam", members=[subteam], telemetry=False)

    leaf_req = _make_requirement("tc_nested_sync")
    leaf_req.member_agent_id = get_member_id(leaf_agent)
    leaf_req.member_agent_name = leaf_agent.name
    leaf_req.member_run_id = "leaf_run_sync"
    paused_subteam = TeamRunOutput(
        run_id="subteam_run_sync",
        team_id=subteam.id,
        team_name=subteam.name,
        status=RunStatus.paused,
        requirements=[leaf_req],
    )

    top_run = TeamRunOutput(run_id="top_run_sync", status=RunStatus.paused)
    _propagate_member_pause(top_run, subteam, paused_subteam)

    call_log = {}

    def _leaf_continue_run(*, run_id, requirements, session_id):
        call_log["leaf"] = {
            "run_id": run_id,
            "session_id": session_id,
            "member_agent_id": requirements[0].member_agent_id,
        }
        return RunOutput(run_id=run_id, status=RunStatus.completed, content="leaf done")

    def _subteam_continue_run(*, run_id, requirements, session_id):
        call_log["subteam"] = {
            "run_id": run_id,
            "session_id": session_id,
            "member_agent_id": requirements[0].member_agent_id,
        }
        nested_run = TeamRunOutput(run_id="nested_sync", status=RunStatus.paused, requirements=requirements)
        _run._route_requirements_to_members(subteam, nested_run, TeamSession(session_id=session_id))
        return TeamRunOutput(run_id=run_id, status=RunStatus.completed, content="subteam done")

    leaf_agent.continue_run = _leaf_continue_run  # type: ignore[method-assign]
    subteam.continue_run = _subteam_continue_run  # type: ignore[method-assign]

    member_results = _run._route_requirements_to_members(top_team, top_run, TeamSession(session_id="sync_session"))

    assert "LeafAgent" in member_results
    assert call_log["subteam"]["run_id"] == "leaf_run_sync"
    assert call_log["subteam"]["member_agent_id"] == get_member_id(leaf_agent)
    assert call_log["leaf"]["run_id"] == "leaf_run_sync"
    assert call_log["leaf"]["member_agent_id"] == get_member_id(leaf_agent)


@pytest.mark.asyncio
async def test_nested_team_continue_run_routing_succeeds_async():
    """Verify nested-team HITL requirements route top->subteam->leaf in async continuation."""
    from agno.team.team import Team

    leaf_agent = Agent(name="LeafAgent", id="leaf_1")
    subteam = Team(name="ResearchSubteam", id="subteam_1", members=[leaf_agent], telemetry=False)
    top_team = Team(name="TopTeam", members=[subteam], telemetry=False)

    leaf_req = _make_requirement("tc_nested_async")
    leaf_req.member_agent_id = get_member_id(leaf_agent)
    leaf_req.member_agent_name = leaf_agent.name
    leaf_req.member_run_id = "leaf_run_async"
    paused_subteam = TeamRunOutput(
        run_id="subteam_run_async",
        team_id=subteam.id,
        team_name=subteam.name,
        status=RunStatus.paused,
        requirements=[leaf_req],
    )

    top_run = TeamRunOutput(run_id="top_run_async", status=RunStatus.paused)
    _propagate_member_pause(top_run, subteam, paused_subteam)

    call_log = {}

    async def _leaf_acontinue_run(*, run_id, requirements, session_id):
        call_log["leaf"] = {
            "run_id": run_id,
            "session_id": session_id,
            "member_agent_id": requirements[0].member_agent_id,
        }
        return RunOutput(run_id=run_id, status=RunStatus.completed, content="leaf done")

    async def _subteam_acontinue_run(*, run_id, requirements, session_id):
        call_log["subteam"] = {
            "run_id": run_id,
            "session_id": session_id,
            "member_agent_id": requirements[0].member_agent_id,
        }
        nested_run = TeamRunOutput(run_id="nested_async", status=RunStatus.paused, requirements=requirements)
        await _run._aroute_requirements_to_members(subteam, nested_run, TeamSession(session_id=session_id))
        return TeamRunOutput(run_id=run_id, status=RunStatus.completed, content="subteam done")

    leaf_agent.acontinue_run = _leaf_acontinue_run  # type: ignore[method-assign]
    subteam.acontinue_run = _subteam_acontinue_run  # type: ignore[method-assign]

    member_results = await _run._aroute_requirements_to_members(
        top_team, top_run, TeamSession(session_id="async_session")
    )

    assert "LeafAgent" in member_results
    assert call_log["subteam"]["run_id"] == "leaf_run_async"
    assert call_log["subteam"]["member_agent_id"] == get_member_id(leaf_agent)
    assert call_log["leaf"]["run_id"] == "leaf_run_async"
    assert call_log["leaf"]["member_agent_id"] == get_member_id(leaf_agent)


# ---------------------------------------------------------------------------
# _propagate_still_paused with multiple members
# ---------------------------------------------------------------------------


def test_propagate_still_paused_multiple_members():
    """Verify requirements from multiple paused members are all propagated."""
    team_run = TeamRunOutput(run_id="team_run")
    req_a = _make_requirement("tool_a")
    req_b = _make_requirement("tool_b")
    paused_a = RunOutput(
        run_id="run_a", agent_id="agent_a", agent_name="AgentA", status=RunStatus.paused, requirements=[req_a]
    )
    paused_b = RunOutput(
        run_id="run_b", agent_id="agent_b", agent_name="AgentB", status=RunStatus.paused, requirements=[req_b]
    )

    _run._propagate_still_paused_member_requirements(team_run, {"AgentA": paused_a, "AgentB": paused_b})

    assert team_run.requirements is not None
    assert len(team_run.requirements) == 2
    ids = {r.member_agent_id for r in team_run.requirements}
    assert "agent_a" in ids
    assert "agent_b" in ids


def test_propagate_still_paused_skips_empty_requirements():
    """Verify members with empty requirements are skipped."""
    team_run = TeamRunOutput(run_id="team_run")
    paused_empty = RunOutput(
        run_id="run_empty", agent_id="agent_e", agent_name="EmptyAgent", status=RunStatus.paused, requirements=[]
    )
    req = _make_requirement("tool_real")
    paused_real = RunOutput(
        run_id="run_real", agent_id="agent_r", agent_name="RealAgent", status=RunStatus.paused, requirements=[req]
    )

    _run._propagate_still_paused_member_requirements(team_run, {"EmptyAgent": paused_empty, "RealAgent": paused_real})

    assert team_run.requirements is not None
    assert len(team_run.requirements) == 1
    assert team_run.requirements[0].member_agent_id == "agent_r"


# ---------------------------------------------------------------------------
# TeamRunOutput requirements serialization roundtrip
# ---------------------------------------------------------------------------


def test_team_run_output_requirements_roundtrip():
    """Verify requirements survive to_dict/from_dict roundtrip."""
    req = _make_requirement("tc_roundtrip")
    req.member_agent_id = "agent_x"
    req.member_agent_name = "AgentX"
    req.member_run_id = "run_x"
    req.confirm()

    team_run = TeamRunOutput(
        run_id="roundtrip_run",
        status=RunStatus.paused,
        requirements=[req],
    )

    serialized = team_run.to_dict()
    assert "requirements" in serialized
    assert len(serialized["requirements"]) == 1

    restored = TeamRunOutput.from_dict(serialized)
    assert restored.requirements is not None
    assert len(restored.requirements) == 1
    restored_req = restored.requirements[0]
    assert isinstance(restored_req, RunRequirement)
    assert restored_req.member_agent_id == "agent_x"
    assert restored_req.member_agent_name == "AgentX"
    assert restored_req.member_run_id == "run_x"
    assert restored_req.tool_execution.tool_call_id == "tc_roundtrip"
    assert restored_req.is_resolved()


def test_team_run_output_no_requirements_roundtrip():
    """Verify roundtrip works when requirements is None."""
    team_run = TeamRunOutput(run_id="no_req_run")
    serialized = team_run.to_dict()
    assert "requirements" not in serialized

    restored = TeamRunOutput.from_dict(serialized)
    assert restored.requirements is None


# ---------------------------------------------------------------------------
# continue_run_dispatch error paths
# ---------------------------------------------------------------------------


def test_continue_run_dispatch_raises_without_args():
    """Verify continue_run_dispatch raises ValueError when neither run_response nor run_id given."""
    from agno.team.team import Team

    team = Team(name="TestTeam", members=[Agent(name="A")])

    with pytest.raises(ValueError, match="Either run_response or run_id must be provided"):
        _run.continue_run_dispatch(team)


def test_continue_run_dispatch_raises_without_session_id():
    """Verify continue_run_dispatch raises ValueError when run_id given without session_id."""
    from agno.team.team import Team

    team = Team(name="TestTeam", members=[Agent(name="A")])

    with pytest.raises(ValueError, match="Session ID is required"):
        _run.continue_run_dispatch(team, run_id="some_run_id")


def test_continue_run_dispatch_run_id_normalizes_dict_requirements(monkeypatch):
    """Verify sync run_id continuation accepts dict requirements payloads."""
    from agno.team.team import Team

    team = Team(name="TestTeam", members=[Agent(name="A")])
    paused_run = TeamRunOutput(run_id="team_run_1", session_id="session_1", status=RunStatus.paused)
    team_session = TeamSession(session_id="session_1", runs=[paused_run])

    req = _make_requirement("tc_dict_sync", confirmed=True)
    req.member_agent_id = "agent_1"
    req.member_agent_name = "AgentOne"
    req.member_run_id = "member_run_1"
    req_dict = req.to_dict()

    monkeypatch.setattr(team, "_has_async_db", lambda: False)
    monkeypatch.setattr(team, "initialize_team", lambda debug_mode=None: None)
    monkeypatch.setattr(team, "_initialize_session", lambda session_id=None, user_id=None: ("session_1", user_id))
    monkeypatch.setattr(team, "_read_or_create_session", lambda session_id, user_id=None: team_session)
    monkeypatch.setattr(team, "_cleanup_and_store", lambda run_response, session: None)

    routed: dict = {}

    def _fake_route_requirements_to_members(_team, run_response, _session):
        routed["requirements"] = run_response.requirements
        return {"AgentOne": RunOutput(run_id="member_run_1", content="member complete", status=RunStatus.completed)}

    monkeypatch.setattr(_run, "_route_requirements_to_members", _fake_route_requirements_to_members)
    monkeypatch.setattr(
        _run,
        "run",
        lambda *_args, **_kwargs: TeamRunOutput(
            run_id="continued_sync", content="team complete", status=RunStatus.completed
        ),
    )

    result = _run.continue_run_dispatch(team, run_id="team_run_1", requirements=[req_dict], session_id="session_1")

    assert result.run_id == "continued_sync"
    assert routed["requirements"] is not None
    assert all(isinstance(item, RunRequirement) for item in routed["requirements"])
    assert routed["requirements"][0].member_agent_id == "agent_1"
    assert routed["requirements"][0].member_run_id == "member_run_1"


@pytest.mark.asyncio
async def test_acontinue_run_impl_run_id_normalizes_dict_requirements(monkeypatch):
    """Verify async run_id continuation accepts dict requirements payloads."""
    from agno.team.team import Team

    team = Team(name="TestTeam", members=[Agent(name="A")])
    paused_run = TeamRunOutput(run_id="team_run_2", session_id="session_2", status=RunStatus.paused)
    team_session = TeamSession(session_id="session_2", runs=[paused_run])

    req = _make_requirement("tc_dict_async", confirmed=True)
    req.member_agent_id = "agent_2"
    req.member_agent_name = "AgentTwo"
    req.member_run_id = "member_run_2"
    req_dict = req.to_dict()

    async def _fake_aread_or_create_session(*_args, **_kwargs):
        return team_session

    async def _fake_acleanup_and_store(*_args, **_kwargs):
        return None

    routed: dict = {}

    async def _fake_aroute_requirements_to_members(_team, run_response, _session):
        routed["requirements"] = run_response.requirements
        return {"AgentTwo": RunOutput(run_id="member_run_2", content="member complete", status=RunStatus.completed)}

    async def _fake_arun(*_args, **_kwargs):
        return TeamRunOutput(run_id="continued_async", content="team complete", status=RunStatus.completed)

    monkeypatch.setattr(team, "_aread_or_create_session", _fake_aread_or_create_session)
    monkeypatch.setattr(team, "_acleanup_and_store", _fake_acleanup_and_store)
    monkeypatch.setattr(_run, "_aroute_requirements_to_members", _fake_aroute_requirements_to_members)
    monkeypatch.setattr(_run, "arun", _fake_arun)

    result = await _run._acontinue_run_impl(
        team,
        run_id="team_run_2",
        requirements=[req_dict],
        session_id="session_2",
    )

    assert result.run_id == "continued_async"
    assert routed["requirements"] is not None
    assert all(isinstance(item, RunRequirement) for item in routed["requirements"])
    assert routed["requirements"][0].member_agent_id == "agent_2"
    assert routed["requirements"][0].member_run_id == "member_run_2"


# ---------------------------------------------------------------------------
# deepcopy prevents ToolExecution aliasing
# ---------------------------------------------------------------------------


def test_propagate_member_pause_deepcopy_prevents_tool_execution_aliasing():
    """Verify that resolving the team's copy does not mutate the member's original ToolExecution."""
    team_run = TeamRunOutput(run_id="team_run")
    member_agent = Agent(name="DeepCopyAgent")
    req = _make_requirement("tc_alias")
    member_run = RunOutput(
        run_id="member_run_alias",
        status=RunStatus.paused,
        requirements=[req],
    )

    _propagate_member_pause(team_run, member_agent, member_run)

    # Resolve the team-level copy
    team_req = team_run.requirements[0]
    team_req.confirm()

    # The team copy should be resolved
    assert team_req.tool_execution.confirmed is True
    assert team_req.is_resolved()

    # The original member requirement should NOT be affected
    assert req.tool_execution.confirmed is not True
    assert req.confirmation is None


def test_propagate_still_paused_does_not_mutate_original_requirements():
    """Verify _propagate_still_paused_member_requirements copies instead of mutating originals."""
    team_run = TeamRunOutput(run_id="team_run")
    req = _make_requirement("tc_still")
    paused_member = RunOutput(
        run_id="agent_run_still",
        agent_id="agent_still",
        agent_name="StillPausedAgent",
        status=RunStatus.paused,
        requirements=[req],
    )

    _run._propagate_still_paused_member_requirements(team_run, {"StillPausedAgent": paused_member})

    # Original requirement should not have member context
    assert req.member_agent_id is None
    assert req.member_agent_name is None
    assert req.member_run_id is None

    # Team copy should have member context
    assert team_run.requirements[0].member_agent_id == "agent_still"
    assert team_run.requirements[0].member_agent_name == "StillPausedAgent"
    assert team_run.requirements[0].member_run_id == "agent_run_still"


def test_propagate_still_paused_deepcopy_prevents_tool_execution_aliasing():
    """Verify resolving the team copy from _propagate_still_paused does not mutate originals."""
    team_run = TeamRunOutput(run_id="team_run")
    req = _make_requirement("tc_still_alias")
    paused_member = RunOutput(
        run_id="agent_run_alias2",
        agent_id="agent_alias2",
        agent_name="AliasAgent",
        status=RunStatus.paused,
        requirements=[req],
    )

    _run._propagate_still_paused_member_requirements(team_run, {"AliasAgent": paused_member})

    # Resolve the team-level copy
    team_req = team_run.requirements[0]
    team_req.confirm()

    # The original should NOT be affected
    assert req.tool_execution.confirmed is not True
    assert req.confirmation is None


# ---------------------------------------------------------------------------
# RunRequirement.provide_user_input
# ---------------------------------------------------------------------------


def test_provide_user_input_sets_values_and_marks_answered():
    """Verify provide_user_input correctly sets field values and marks tool as answered."""
    te = ToolExecution(
        tool_call_id="tc_ui",
        tool_name="get_info",
        tool_args={},
        requires_user_input=True,
        user_input_schema=[
            UserInputField(name="city", field_type=str, description="City name"),
            UserInputField(name="country", field_type=str, description="Country name"),
        ],
    )
    req = RunRequirement(tool_execution=te)

    assert req.needs_user_input is True
    assert not req.is_resolved()

    req.provide_user_input({"city": "Tokyo", "country": "Japan"})

    assert req.tool_execution.answered is True
    assert req.user_input_schema[0].value == "Tokyo"
    assert req.user_input_schema[1].value == "Japan"
    assert not req.needs_user_input
    assert req.is_resolved()


def test_provide_user_input_raises_if_not_needed():
    """Verify provide_user_input raises ValueError when requirement does not need user input."""
    te = ToolExecution(
        tool_call_id="tc_conf",
        tool_name="do_thing",
        tool_args={},
        requires_confirmation=True,
    )
    req = RunRequirement(tool_execution=te)

    with pytest.raises(ValueError, match="does not require user input"):
        req.provide_user_input({"x": "y"})


def test_provide_user_input_partial_values():
    """Verify provide_user_input with partial values does NOT mark as answered."""
    te = ToolExecution(
        tool_call_id="tc_partial",
        tool_name="get_info",
        tool_args={},
        requires_user_input=True,
        user_input_schema=[
            UserInputField(name="city", field_type=str, description="City name"),
            UserInputField(name="country", field_type=str, description="Country name"),
        ],
    )
    req = RunRequirement(tool_execution=te)
    req.provide_user_input({"city": "Tokyo"})

    # Partial input should NOT mark as answered
    assert req.tool_execution.answered is not True
    assert req.user_input_schema[0].value == "Tokyo"
    assert req.user_input_schema[1].value is None
    # Requirement should still need user input
    assert req.needs_user_input is True
    assert req.is_resolved() is False

    # Now provide the remaining field
    req.provide_user_input({"country": "Japan"})
    assert req.tool_execution.answered is True
    assert req.is_resolved() is True


# ---------------------------------------------------------------------------
# _build_continuation_message
# ---------------------------------------------------------------------------


def test_build_continuation_message():
    """Verify _build_continuation_message assembles member results."""
    result_a = RunOutput(run_id="run_a", content="Weather is sunny")
    result_b = RunOutput(run_id="run_b", content="Email sent")
    msg = _run._build_continuation_message({"AgentA": result_a, "AgentB": result_b})

    assert "Previously delegated tasks have been completed." in msg
    assert "AgentA" in msg
    assert "Weather is sunny" in msg
    assert "AgentB" in msg
    assert "Email sent" in msg


def test_build_continuation_message_none_content():
    """Verify _build_continuation_message handles None content."""
    result = RunOutput(run_id="run_none", content=None)
    msg = _run._build_continuation_message({"AgentX": result})

    assert "(no content)" in msg


def test_build_continuation_message_structured_content():
    """Verify _build_continuation_message handles BaseModel content."""
    from pydantic import BaseModel

    class WeatherResult(BaseModel):
        city: str
        temperature: int

    result = RunOutput(run_id="run_structured", content=WeatherResult(city="Tokyo", temperature=70))
    msg = _run._build_continuation_message({"AgentX": result})

    # Should serialize as JSON, not the Pydantic __str__ repr
    assert "Tokyo" in msg
    assert "70" in msg
    assert "WeatherResult(" not in msg


# ---------------------------------------------------------------------------
# handle_team_run_paused_stream
# ---------------------------------------------------------------------------


def test_handle_team_run_paused_stream_yields_event():
    """Verify handle_team_run_paused_stream yields a pause event."""
    from unittest.mock import MagicMock

    from agno.team import _hooks

    team_mock = MagicMock()
    team_mock.events_to_skip = None
    team_mock.store_events = True

    req = _make_requirement("tc_stream")
    req.member_agent_name = "StreamAgent"
    team_run = TeamRunOutput(
        run_id="stream_run",
        status=RunStatus.paused,
        requirements=[req],
    )

    session_mock = MagicMock()

    events = list(_hooks.handle_team_run_paused_stream(team_mock, run_response=team_run, session=session_mock))

    # Should yield exactly one event (the pause event)
    assert len(events) == 1
    assert team_run.status == RunStatus.paused


def test_handle_team_run_paused_stream_skips_none_event():
    """Verify handle_team_run_paused_stream does not yield None when event is skipped."""
    from unittest.mock import MagicMock, patch

    from agno.team import _hooks

    team_mock = MagicMock()
    team_mock.events_to_skip = None
    team_mock.store_events = True

    team_run = TeamRunOutput(
        run_id="skip_run",
        status=RunStatus.paused,
        content="paused",
    )
    session_mock = MagicMock()

    # Patch handle_event to return None (simulating an event being skipped)
    with patch("agno.team._hooks.handle_event", return_value=None):
        events = list(_hooks.handle_team_run_paused_stream(team_mock, run_response=team_run, session=session_mock))

    # No events should be yielded since the pause event was None
    assert len(events) == 0
