"""Tests for `Team.expose_sub_team_members`.

When a team contains a sub-team, the parent leader has historically seen the
sub-team's full member tree in its system prompt and could delegate directly
to grandchild agents, bypassing the sub-team's own leader. `expose_sub_team_members`
lets a team opt into treating sub-teams as opaque capabilities.
"""

from agno.agent import Agent
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team.team import Team


def _build_nested_team(expose_sub_team_members: bool) -> Team:
    grandchild_a = Agent(name="Agent A", role="Worker A")
    grandchild_b = Agent(name="Agent B", role="Worker B")
    sub_team = Team(
        name="Sub Team",
        description="Handles sub things",
        members=[grandchild_a, grandchild_b],
    )
    top_team = Team(
        name="Top Team",
        members=[sub_team],
        expose_sub_team_members=expose_sub_team_members,
    )
    return top_team


def test_expose_sub_team_members_default_is_true():
    team = Team(name="T", members=[])
    assert team.expose_sub_team_members is True


def test_prompt_exposes_nested_members_when_flag_true():
    top_team = _build_nested_team(expose_sub_team_members=True)
    content = top_team.get_members_system_message_content()

    assert 'id="sub-team"' in content
    assert 'type="team"' in content
    # Grandchildren are visible to the top team leader.
    assert 'id="agent-a"' in content
    assert 'id="agent-b"' in content
    assert "Role: Worker A" in content


def test_prompt_hides_nested_members_when_flag_false():
    top_team = _build_nested_team(expose_sub_team_members=False)
    content = top_team.get_members_system_message_content()

    # Sub-team itself is still visible as an opaque capability.
    assert 'id="sub-team"' in content
    assert 'type="team"' in content
    assert "Description: Handles sub things" in content

    # But its members must not leak into the top team's prompt.
    assert 'id="agent-a"' not in content
    assert 'id="agent-b"' not in content
    assert "Worker A" not in content
    assert "Worker B" not in content


def test_sub_team_prompt_still_exposes_its_own_members_when_flag_false_on_top():
    """Opting out on the top team must not change the sub-team's own prompt."""
    top_team = _build_nested_team(expose_sub_team_members=False)
    sub_team = top_team.members[0]
    assert isinstance(sub_team, Team)

    sub_content = sub_team.get_members_system_message_content()
    assert 'id="agent-a"' in sub_content
    assert 'id="agent-b"' in sub_content


def test_find_member_by_id_finds_grandchild_when_flag_true():
    top_team = _build_nested_team(expose_sub_team_members=True)
    result = top_team._find_member_by_id("agent-a")
    assert result is not None
    _, member = result
    assert isinstance(member, Agent)
    assert member.name == "Agent A"


def test_find_member_by_id_does_not_find_grandchild_when_flag_false():
    top_team = _build_nested_team(expose_sub_team_members=False)
    assert top_team._find_member_by_id("agent-a") is None
    assert top_team._find_member_by_id("agent-b") is None


def test_find_member_by_id_still_finds_direct_sub_team_when_flag_false():
    top_team = _build_nested_team(expose_sub_team_members=False)
    result = top_team._find_member_by_id("sub-team")
    assert result is not None
    _, member = result
    assert isinstance(member, Team)
    assert member.name == "Sub Team"


def test_delegate_to_grandchild_is_rejected_when_flag_false():
    top_team = _build_nested_team(expose_sub_team_members=False)

    function = top_team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(content="Hello, world!"),
        run_context=RunContext(session_state={}, run_id="test-run", session_id="test-session"),
        team_run_context={},
    )
    response = list(function.entrypoint(member_id="agent-a", task="do something"))
    text = response[0]
    assert "Member with ID agent-a not found in the team" in text
    # The scope phrasing should reflect that sub-teams are opaque.
    assert "any subteams" not in text


def test_delegate_error_mentions_subteams_when_flag_true():
    top_team = _build_nested_team(expose_sub_team_members=True)

    function = top_team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(content="Hello, world!"),
        run_context=RunContext(session_state={}, run_id="test-run", session_id="test-session"),
        team_run_context={},
    )
    response = list(function.entrypoint(member_id="wrong-agent", task="do something"))
    assert "Member with ID wrong-agent not found in the team or any subteams" in response[0]
