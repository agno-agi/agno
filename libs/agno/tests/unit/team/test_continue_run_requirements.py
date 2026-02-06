from agno.models.response import ToolExecution
from agno.run import RunStatus
from agno.run.agent import RunOutput
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.team import _run


def _make_requirement(tool_call_id: str) -> RunRequirement:
    return RunRequirement(
        tool_execution=ToolExecution(
            tool_call_id=tool_call_id,
            tool_name="test_tool",
            tool_args={},
            requires_confirmation=True,
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
