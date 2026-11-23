"""Tests for Skills integration on Team.

Verifies that:
- Skills tools are registered when team.skills is set
- Skills tools are absent when team.skills is None
- Skills system prompt snippet is injected into the system message
- Skills system prompt snippet is omitted when team.skills is None
- deep_copy shares the Skills instance by reference (shared resource)
"""

from unittest.mock import MagicMock

from agno.models.base import Function
from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.skills import LocalSkills, Skills
from agno.team._messages import get_system_message
from agno.team._tools import _determine_tools_for_model
from agno.team.team import Team

SAMPLE_SKILLS_DIR = "cookbook/02_agents/16_skills/sample_skills"

SKILL_TOOL_NAMES = {"get_skill_instructions", "get_skill_reference", "get_skill_script"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run_context():
    return RunContext(run_id="test-run", session_id="test-session")


def _make_session():
    return TeamSession(session_id="test-session")


def _make_run_response():
    return TeamRunOutput(run_id="test-run", session_id="test-session", team_id="test-team")


def _make_model():
    model = MagicMock()
    model.get_tools_for_api.return_value = []
    model.add_tool.return_value = None
    model.get_instructions_for_model = MagicMock(return_value=None)
    model.get_system_message_for_model = MagicMock(return_value=None)
    return model


def _make_skills():
    return Skills(loaders=[LocalSkills(SAMPLE_SKILLS_DIR)])


def _get_skill_tools(tools):
    return [t for t in tools if isinstance(t, Function) and t.name in SKILL_TOOL_NAMES]


# ---------------------------------------------------------------------------
# Tool registration tests
# ---------------------------------------------------------------------------


def test_skills_tools_registered_when_skills_set():
    """Skills tools are present in the tool list when team.skills is set."""
    team = Team(name="test-team", members=[], skills=_make_skills())

    tools = _determine_tools_for_model(
        team=team,
        model=_make_model(),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        team_run_context={},
        session=_make_session(),
        async_mode=False,
    )

    skill_tools = _get_skill_tools(tools)
    assert len(skill_tools) == 3
    tool_names = {t.name for t in skill_tools}
    assert tool_names == SKILL_TOOL_NAMES


def test_skills_tools_absent_when_skills_none():
    """No skills tools are present when team.skills is None."""
    team = Team(name="test-team", members=[])

    tools = _determine_tools_for_model(
        team=team,
        model=_make_model(),
        run_response=_make_run_response(),
        run_context=_make_run_context(),
        team_run_context={},
        session=_make_session(),
        async_mode=False,
    )

    skill_tools = _get_skill_tools(tools)
    assert len(skill_tools) == 0


# ---------------------------------------------------------------------------
# System message tests
# ---------------------------------------------------------------------------


def test_system_message_contains_skills_snippet():
    """System message includes the <skills_system> block when team.skills is set."""
    team = Team(name="test-team", mode="coordinate", members=[], skills=_make_skills())
    team.model = _make_model()
    session = TeamSession(session_id="test-session")

    msg = get_system_message(team, session)

    assert msg is not None
    assert "<skills_system>" in msg.content
    assert "get_skill_instructions" in msg.content


def test_system_message_omits_skills_when_none():
    """System message does not contain skills block when team.skills is None."""
    team = Team(name="test-team", mode="coordinate", members=[])
    team.model = _make_model()
    session = TeamSession(session_id="test-session")

    msg = get_system_message(team, session)

    if msg is not None:
        assert "<skills_system>" not in msg.content


# ---------------------------------------------------------------------------
# Deep copy tests
# ---------------------------------------------------------------------------


def test_deep_copy_shares_skills_by_reference():
    """deep_copy should share the Skills instance (heavy resource), not duplicate it."""
    skills = _make_skills()
    team = Team(name="test-team", members=[], skills=skills)
    copied = team.deep_copy()

    assert copied.skills is skills
