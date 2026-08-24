"""Contract tests for the team leader's generated system message.

These pin the two properties that went unchecked for six months: the user's
identity opens the prompt, and the prompt never names a tool the run will not
attach.
"""

import re

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team.mode import TeamMode
from agno.team.team import Team

MODES = [m.value for m in TeamMode]


def _team(**kwargs) -> Team:
    members = [
        Agent(name="Researcher", id="researcher", model=OpenAIChat("gpt-4o"), role="Search the web"),
        Agent(name="Writer", id="writer", model=OpenAIChat("gpt-4o"), role="Write prose"),
    ]
    kwargs.setdefault("members", members)
    return Team(name="Content Team", id="content-team", model=OpenAIChat("gpt-4o"), **kwargs)


def _session() -> TeamSession:
    return TeamSession(session_id="s1", team_id="content-team")


@pytest.mark.parametrize("mode", MODES)
def test_user_identity_precedes_framework_block(mode):
    """description/role/instructions render before <team>, as they do for an Agent."""
    team = _team(mode=mode, description="A team that researches.", role="Lead", instructions=["Cite sources."])
    content = team.get_system_message(session=_session()).content

    assert content.startswith("<description>")
    assert content.index("<description>") < content.index("<your_role>") < content.index("<team>")
    assert content.index("<team>") > content.index("Cite sources.")


@pytest.mark.parametrize("mode", MODES)
def test_team_block_is_well_formed(mode):
    team = _team(mode=mode)
    content = team.get_system_message(session=_session()).content

    for tag in ("team", "team_members", "delegation"):
        assert content.count(f"<{tag}>") == 1, tag
        assert content.count(f"</{tag}>") == 1, tag
        assert content.index(f"<{tag}>") < content.index(f"</{tag}>"), tag

    # The roster holds member records; prose belongs outside it.
    roster = content[content.index("<team_members>") : content.index("</team_members>")]
    assert "`" not in roster


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_sync_and_async_builders_agree(mode):
    team = _team(mode=mode, description="D", instructions=["I"], get_member_information_tool=True)
    assert (
        team.get_system_message(session=_session()).content
        == (await team.aget_system_message(session=_session())).content
    )


@pytest.mark.parametrize("mode", MODES)
def test_every_tool_named_in_the_prompt_is_attached(mode):
    """A backticked identifier in the delegation block must resolve to a real tool.

    This is the check that would have caught the prompt drifting away from the tools
    its own mode attaches.
    """
    # get_member_information_tool on, so the widened <team> window has something to check.
    team = _team(mode=mode, get_member_information_tool=True)
    team.initialize_team()
    run_context = RunContext(session_state={}, run_id="r1", session_id="s1")

    tools = team._determine_tools_for_model(
        model=team.model,
        run_response=TeamRunOutput(run_id="r1"),
        run_context=run_context,
        team_run_context={},
        session=_session(),
    )
    attached = set()
    for t in tools:
        name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else None)
        if not name:
            continue
        attached.add(name)
        # Argument names are quoted in the prompt too, and drift the same way.
        params = getattr(t, "parameters", None)
        if isinstance(params, dict):
            attached.update(params.get("properties", {}).keys())

    # Scan the whole <team> block, not just <delegation>: the get_member_information
    # sentence sits between the roster and the delegation block, and drifted there.
    content = team.get_system_message(session=_session()).content
    block = content[content.index("<team>") : content.index("</team>")]
    named = set(re.findall(r"`([a-z_][a-z0-9_]*)`", block))

    assert named, "the delegation block should name the tools it expects to be called"
    assert named <= attached, f"{mode}: prompt names unattached tools/args {sorted(named - attached)}"


def test_get_member_information_is_named_only_where_it_is_attached():
    """Tasks mode takes the task-tool branch, which never attaches it."""
    for mode in MODES:
        content = _team(mode=mode, get_member_information_tool=True).get_system_message(session=_session()).content
        assert ("get_member_information" in content) is (mode != TeamMode.tasks.value)


def test_conflicting_flags_render_the_mode_that_actually_runs():
    """respond_directly + delegate_to_all_members resolves to broadcast, prompt included."""
    team = _team(respond_directly=True, delegate_to_all_members=True)
    team.initialize_team()
    assert team.mode == TeamMode.broadcast

    content = team.get_system_message(session=_session()).content
    assert "broadcast mode" in content
    assert "route mode" not in content
    assert "`delegate_task_to_member`" not in content


def test_member_isolation_claim_tracks_the_context_flags():
    """The unconditional claim is false once the team forwards history or interactions."""
    plain = _team().get_system_message(session=_session()).content
    assert "Members do not see this conversation." in plain

    sharing = _team(add_team_history_to_members=True).get_system_message(session=_session()).content
    assert "Members do not see this conversation." not in sharing
    assert "not the conversation itself" in sharing


def test_member_ids_line_is_suppressed_for_broadcast():
    """delegate_task_to_members takes no member id, so naming ids there is noise."""
    for mode in MODES:
        content = _team(mode=mode).get_system_message(session=_session()).content
        assert ("Member ids are the ids shown" in content) is (mode != TeamMode.broadcast.value)


def test_prompt_names_member_tools_only_when_the_roster_shows_them():
    without = _team().get_system_message(session=_session()).content
    assert "role, description, and tools" not in without
    assert "Tools:" not in without

    with_tools = _team(add_member_tools_to_context=True).get_system_message(session=_session()).content
    assert "role, description, and tools" in with_tools


def test_verbatim_input_closer_tracks_determine_input_for_members():
    """Tasks mode always delivers the leader's text; the delegate tools may not."""
    for mode in MODES:
        content = _team(mode=mode, determine_input_for_members=False).get_system_message(session=_session()).content
        expected = mode != TeamMode.tasks.value
        assert ("receives the user's message verbatim" in content) is expected


def test_multi_line_instruction_is_not_rendered_as_a_list_item():
    """A block instruction keeps its own bullets; only single-line entries are bulleted."""
    block = "You are Agno.\n\nWho you are:\n- The platform.\n- Warm and quick."
    content = _team(instructions=[block, "File relentlessly."]).get_system_message(session=_session()).content

    assert content.startswith(block)
    assert "- You are Agno." not in content
    assert "\n\n- File relentlessly." in content


def test_single_line_instructions_are_still_bulleted():
    content = _team(instructions=["First.", "Second."]).get_system_message(session=_session()).content
    assert content.startswith("- First.\n- Second.\n\n")


def test_sub_team_member_renders_its_role():
    sub = Team(
        name="Research Team",
        id="research-team",
        model=OpenAIChat("gpt-4o"),
        role="Handles all research",
        members=[Agent(name="R", id="r", model=OpenAIChat("gpt-4o"))],
    )
    content = _team(members=[sub]).get_system_message(session=_session()).content
    assert 'type="team"' in content
    assert "Role: Handles all research" in content


@pytest.mark.parametrize("mode", MODES)
def test_opening_states_delegation_as_need_not_as_self_assessment(mode):
    """The opening tells the leader to delegate when a member is needed, not when the
    member would do it better than the leader.

    A comparison invites the leader to rate its own ability against the roster, and a
    small model rates itself well enough to keep the parts it thinks it can do and skip
    the member the request named for them. The need rule ties delegation to the request.
    """
    content = _team(mode=mode).get_system_message(session=_session()).content
    block = content[content.index("<team>") : content.index("<team_members>")]

    assert "Delegate to members when their expertise or tools are needed" in block
    assert "better than" not in block
    assert "fit it better" not in content


@pytest.mark.parametrize("mode", MODES)
def test_opening_makes_no_identity_claim(mode):
    """The opening states what the leader has, not who it is; identity is the user's."""
    content = _team(mode=mode, description="A team that researches.").get_system_message(session=_session()).content
    opening = content[content.index("<team>") + len("<team>\n") :].split("\n", 1)[0]

    assert opening.startswith("You have a team of specialists")
    for claim in ("You are", "You coordinate", "You act as"):
        assert claim not in opening
