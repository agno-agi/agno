from agno.agent import Agent
from agno.models.response import ToolExecution
from agno.run import RunStatus
from agno.run.agent import RunOutput
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.team import _run
from agno.team._tools import _propagate_member_pause


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

    try:
        _run.continue_run_dispatch(team)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Either run_response or run_id must be provided" in str(e)


def test_continue_run_dispatch_raises_without_session_id():
    """Verify continue_run_dispatch raises ValueError when run_id given without session_id."""
    from agno.team.team import Team

    team = Team(name="TestTeam", members=[Agent(name="A")])

    try:
        _run.continue_run_dispatch(team, run_id="some_run_id")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Session ID is required" in str(e)
