"""Unit tests for lazy skill tool loading via activate_skill / deactivate_skill meta-tools."""

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from agno.agent._default_tools import make_activate_skill_entrypoint, make_deactivate_skill_entrypoint
from agno.agent.agent import Agent
from agno.run import RunContext
from agno.session import AgentSession
from agno.skills.agent_skills import Skills
from agno.skills.loaders.base import SkillLoader
from agno.skills.skill import Skill
from agno.tools.function import Function

from .conftest import MockSkillLoader


# --- Agent lazy_load_skills Configuration Tests ---


def test_agent_lazy_load_skills_default_false() -> None:
    """Verify that Agent() has lazy_load_skills defaulting to False."""
    agent = Agent()
    assert agent.lazy_load_skills is False


def test_agent_lazy_load_skills_configurable() -> None:
    """Verify that Agent(lazy_load_skills=True) sets lazy_load_skills to True."""
    agent = Agent(lazy_load_skills=True)
    assert agent.lazy_load_skills is True


# --- Skill.tools Field Tests ---


def test_skill_tools_field_default_none() -> None:
    """Verify that Skill instance has tools defaulting to None."""
    skill = Skill(
        name="test-skill",
        description="A test skill for unit testing",
        instructions="Instructions for test skill",
        source_path="/path/to/test-skill",
    )
    assert skill.tools is None


def test_skill_tools_field_accepts_tool_list() -> None:
    """Verify that Skill accepts a list of tool objects and to_dict() returns tools as None."""
    mock_tool = MagicMock()
    skill = Skill(
        name="test-skill",
        description="A test skill for unit testing",
        instructions="Instructions for test skill",
        source_path="/path/to/test-skill",
        tools=[mock_tool],
    )
    assert skill.tools is not None
    assert mock_tool in skill.tools
    assert len(skill.tools) == 1

    skill_dict = skill.to_dict()
    assert skill_dict["tools"] is None


# --- activate_skill Entrypoint Tests ---


def test_activate_skill_entrypoint_happy_path() -> None:
    """Test happy path: activate_skill adds skill to active_skills in session_state."""
    mock_tool = MagicMock()
    skill = Skill(
        name="test-skill",
        description="A test skill for unit testing",
        instructions="Instructions for test skill",
        source_path="/path/to/test-skill",
        tools=[mock_tool],
    )
    loader = MockSkillLoader([skill])
    agent = Agent(skills=Skills(loaders=[loader]), lazy_load_skills=True)
    run_context = MagicMock(spec=RunContext)
    run_context.session_state = {}

    entrypoint = make_activate_skill_entrypoint(agent)
    result = entrypoint(run_context, skill_name="test-skill")

    assert "active_skills" in run_context.session_state
    assert "test-skill" in run_context.session_state["active_skills"]
    assert "activated" in result.lower() or "test-skill" in result


def test_activate_skill_unknown_skill_name() -> None:
    """Test activating an unknown skill returns an error and does not add to active_skills."""
    agent = Agent(skills=Skills(loaders=[]), lazy_load_skills=True)
    run_context = MagicMock(spec=RunContext)
    run_context.session_state = {}

    entrypoint = make_activate_skill_entrypoint(agent)
    result = entrypoint(run_context, skill_name="nonexistent-skill")

    assert "Error" in result or "not found" in result.lower()
    assert "nonexistent-skill" not in run_context.session_state.get("active_skills", [])


def test_activate_skill_idempotent() -> None:
    """Test that activating an already active skill does not duplicate its entry."""
    skill = Skill(
        name="test-skill",
        description="A test skill for unit testing",
        instructions="Instructions for test skill",
        source_path="/path/to/test-skill",
    )
    loader = MockSkillLoader([skill])
    agent = Agent(skills=Skills(loaders=[loader]), lazy_load_skills=True)
    run_context = MagicMock(spec=RunContext)
    run_context.session_state = {"active_skills": ["test-skill"]}

    entrypoint = make_activate_skill_entrypoint(agent)
    result = entrypoint(run_context, skill_name="test-skill")

    assert run_context.session_state["active_skills"].count("test-skill") == 1
    assert "activated" in result.lower() or "test-skill" in result


def test_activate_skill_no_skills_configured() -> None:
    """Test activating a skill when agent has no skills configured."""
    agent = Agent(skills=None, lazy_load_skills=True)
    run_context = MagicMock(spec=RunContext)
    run_context.session_state = {}

    entrypoint = make_activate_skill_entrypoint(agent)
    result = entrypoint(run_context, skill_name="test-skill")

    assert "Error" in result
    assert "No skills configured" in result


def test_activate_skill_session_state_initially_none() -> None:
    """Test activating a skill initializes session_state if it is None."""
    skill = Skill(
        name="test-skill",
        description="A test skill for unit testing",
        instructions="Instructions for test skill",
        source_path="/path/to/test-skill",
    )
    loader = MockSkillLoader([skill])
    agent = Agent(skills=Skills(loaders=[loader]), lazy_load_skills=True)
    run_context = MagicMock(spec=RunContext)
    run_context.session_state = None

    entrypoint = make_activate_skill_entrypoint(agent)
    result = entrypoint(run_context, skill_name="test-skill")

    assert run_context.session_state is not None
    assert "test-skill" in run_context.session_state["active_skills"]


# --- deactivate_skill Entrypoint Tests ---


def test_deactivate_skill_entrypoint_happy_path() -> None:
    """Test happy path: deactivate_skill removes skill from active_skills in session_state."""
    skill = Skill(
        name="test-skill",
        description="A test skill for unit testing",
        instructions="Instructions for test skill",
        source_path="/path/to/test-skill",
    )
    loader = MockSkillLoader([skill])
    agent = Agent(skills=Skills(loaders=[loader]), lazy_load_skills=True)
    run_context = MagicMock(spec=RunContext)
    run_context.session_state = {"active_skills": ["test-skill"]}

    entrypoint = make_deactivate_skill_entrypoint(agent)
    result = entrypoint(run_context, skill_name="test-skill")

    assert "test-skill" not in run_context.session_state["active_skills"]
    assert "deactivated" in result.lower() or "test-skill" in result


def test_deactivate_skill_not_active() -> None:
    """Test deactivating a skill that was not active returns appropriate message."""
    agent = Agent(lazy_load_skills=True)
    run_context = MagicMock(spec=RunContext)
    run_context.session_state = {"active_skills": []}

    entrypoint = make_deactivate_skill_entrypoint(agent)
    result = entrypoint(run_context, skill_name="test-skill")

    assert "not active" in result.lower()
    assert "test-skill" in result


def test_deactivate_skill_session_state_initially_none() -> None:
    """Test deactivating a skill initializes session_state if it is None."""
    agent = Agent(lazy_load_skills=True)
    run_context = MagicMock(spec=RunContext)
    run_context.session_state = None

    entrypoint = make_deactivate_skill_entrypoint(agent)
    result = entrypoint(run_context, skill_name="test-skill")

    assert run_context.session_state is not None
    assert "not active" in result.lower()


# --- Backward Compatibility Tests ---


def test_backward_compat_eager_mode_skills_object() -> None:
    """Test backward compatibility: eager mode (lazy_load_skills=False) preserves skills behavior."""
    skills = Skills(loaders=[])
    agent = Agent(skills=skills, lazy_load_skills=False)

    assert agent.skills is skills
    assert agent.lazy_load_skills is False

    tools = agent.skills.get_tools()
    assert len(tools) > 0
    tool_names = [t.name for t in tools if isinstance(t, Function)]
    assert "get_skill_instructions" in tool_names
    assert "get_skill_reference" in tool_names
    assert "get_skill_script" in tool_names


# --- get_tools Integration Tests ---


def test_get_tools_lazy_mode_injects_active_skill_tools() -> None:
    """Test that get_tools() in lazy mode injects tools for active skills from session state."""
    from unittest.mock import MagicMock, patch
    from agno.agent._tools import get_tools
    from agno.run import RunContext
    from agno.session import AgentSession

    mock_tool = MagicMock()
    mock_tool.name = "my_tool"
    skill = Skill(
        name="test-skill",
        description="A test skill",
        instructions="Instructions",
        source_path="/path/to/test-skill",
        tools=[mock_tool],
    )
    loader = MockSkillLoader([skill])
    agent = Agent(skills=Skills(loaders=[loader]), lazy_load_skills=True)

    mock_session = MagicMock(spec=AgentSession)
    mock_session.session_state = {"active_skills": ["test-skill"]}
    mock_run_context = MagicMock(spec=RunContext)
    mock_run_response = MagicMock()

    with patch("agno.agent._tools._raise_if_async_tools_in_list"):
        tools = get_tools(
            agent=agent,
            run_response=mock_run_response,
            run_context=mock_run_context,
            session=mock_session,
        )

    tool_names = [t.name for t in tools if hasattr(t, "name")]
    assert "activate_skill" in tool_names
    assert "deactivate_skill" in tool_names
    assert mock_tool in tools


def test_get_tools_lazy_mode_no_active_skills() -> None:
    """Test that get_tools() in lazy mode only exposes meta-tools when no skills are active."""
    from unittest.mock import MagicMock, patch
    from agno.agent._tools import get_tools
    from agno.run import RunContext
    from agno.session import AgentSession

    skill = Skill(
        name="test-skill",
        description="A test skill",
        instructions="Instructions",
        source_path="/path/to/test-skill",
        tools=[MagicMock()],
    )
    loader = MockSkillLoader([skill])
    agent = Agent(skills=Skills(loaders=[loader]), lazy_load_skills=True)

    mock_session = MagicMock(spec=AgentSession)
    mock_session.session_state = {"active_skills": []}
    mock_run_context = MagicMock(spec=RunContext, knowledge=None)
    mock_run_response = MagicMock()

    tools = get_tools(
        agent=agent,
        run_response=mock_run_response,
        run_context=mock_run_context,
        session=mock_session,
    )

    tool_names = [t.name for t in tools if hasattr(t, "name")]
    assert "activate_skill" in tool_names
    assert "deactivate_skill" in tool_names
    # skill's actual tool should NOT be injected
    assert len([t for t in tools if not hasattr(t, "name") or t.name not in ("activate_skill", "deactivate_skill")]) == 0


def test_activate_then_deactivate_multi_skill() -> None:
    """Test that activating two skills and deactivating one leaves only the other active."""
    skill_a = Skill(
        name="skill-a",
        description="Skill A",
        instructions="Instructions A",
        source_path="/path/to/skill-a",
    )
    skill_b = Skill(
        name="skill-b",
        description="Skill B",
        instructions="Instructions B",
        source_path="/path/to/skill-b",
    )
    loader = MockSkillLoader([skill_a, skill_b])
    agent = Agent(skills=Skills(loaders=[loader]), lazy_load_skills=True)

    from unittest.mock import MagicMock
    run_context = MagicMock()
    run_context.session_state = {}

    activate = make_activate_skill_entrypoint(agent)
    deactivate = make_deactivate_skill_entrypoint(agent)

    activate(run_context, skill_name="skill-a")
    activate(run_context, skill_name="skill-b")
    assert set(run_context.session_state["active_skills"]) == {"skill-a", "skill-b"}

    deactivate(run_context, skill_name="skill-a")
    assert run_context.session_state["active_skills"] == ["skill-b"]
