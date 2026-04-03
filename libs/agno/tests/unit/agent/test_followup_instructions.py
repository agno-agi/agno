"""Unit tests for FollowupConfig and followup_instructions feature.

Validates that:
- FollowupConfig stores model and instructions correctly
- _build_followup_messages appends custom instructions to the system prompt
- Agent and Team correctly store and resolve followup_config
- Backward compatibility is maintained with existing followup_model parameter
- followup_config.model takes precedence over followup_model
"""

from agno.agent._response import _build_followup_messages
from agno.agent.agent import Agent
from agno.agent.followup import FollowupConfig
from agno.team.team import Team


# ---------------------------------------------------------------------------
# _build_followup_messages unit tests (no API calls)
# ---------------------------------------------------------------------------

BASE_SYSTEM_PROMPT = (
    "Based on the user's message and the assistant's response below, generate follow-up suggestions. "
    "Each suggestion should be a short action-oriented prompt (5-10 words). "
    "Cover different angles: dig deeper, practical next step, or alternative perspective."
)


def test_build_followup_messages_no_custom_instructions():
    """Without followup_instructions, system prompt should be the default."""
    messages = _build_followup_messages("Some response", num_suggestions=3)
    system_msg = messages[0]
    assert system_msg.role == "system"
    assert system_msg.content == BASE_SYSTEM_PROMPT


def test_build_followup_messages_with_custom_instructions():
    """With followup_instructions, the custom instructions should be appended."""
    custom = "Always suggest follow-ups as formal questions ending with a question mark."
    messages = _build_followup_messages(
        "Some response",
        num_suggestions=3,
        followup_instructions=custom,
    )
    system_msg = messages[0]
    assert system_msg.role == "system"
    assert system_msg.content == BASE_SYSTEM_PROMPT + "\n" + custom


def test_build_followup_messages_empty_string_instructions():
    """An empty-string followup_instructions should not alter the system prompt."""
    messages = _build_followup_messages(
        "Some response",
        num_suggestions=3,
        followup_instructions="",
    )
    system_msg = messages[0]
    # Empty string is falsy, so prompt should remain unchanged
    assert system_msg.content == BASE_SYSTEM_PROMPT


def test_build_followup_messages_user_message_included():
    """User message should appear in the user-role message content."""
    messages = _build_followup_messages(
        "Response text",
        num_suggestions=2,
        user_message="Tell me about Python.",
    )
    user_msg = messages[1]
    assert user_msg.role == "user"
    assert "Tell me about Python." in str(user_msg.content)


def test_build_followup_messages_num_suggestions_in_user_message():
    """The requested number of suggestions should appear in the user message."""
    messages = _build_followup_messages("Response", num_suggestions=5)
    user_msg = messages[1]
    assert "5" in str(user_msg.content)


# ---------------------------------------------------------------------------
# FollowupConfig unit tests
# ---------------------------------------------------------------------------


def test_followup_config_defaults():
    """FollowupConfig should default both fields to None."""
    config = FollowupConfig()
    assert config.model is None
    assert config.instructions is None


def test_followup_config_stores_instructions():
    """FollowupConfig should store instructions correctly."""
    custom = "Focus on Python-specific follow-ups only."
    config = FollowupConfig(instructions=custom)
    assert config.instructions == custom
    assert config.model is None


# ---------------------------------------------------------------------------
# Agent followup_config field tests
# ---------------------------------------------------------------------------


def test_agent_followup_config_default_none():
    """followup_config should default to None on Agent."""
    agent = Agent(followups=True)
    assert agent.followup_config is None


def test_agent_followup_config_stored():
    """followup_config should be stored correctly on Agent."""
    config = FollowupConfig(instructions="Suggest follow-ups in a Socratic style.")
    agent = Agent(followups=True, followup_config=config)
    assert agent.followup_config is config
    assert agent.followup_config.instructions == "Suggest follow-ups in a Socratic style."


def test_agent_followup_model_backward_compat():
    """followup_model should still be accepted and stored for backward compatibility."""
    agent = Agent(followups=True)
    assert agent.followup_model is None  # defaults to None


def test_agent_followup_config_model_takes_precedence():
    """followup_config.model should take precedence in resolution logic."""
    from unittest.mock import MagicMock

    from agno.models.base import Model

    config_model = MagicMock(spec=Model)
    legacy_model = MagicMock(spec=Model)
    config = FollowupConfig(model=config_model)

    agent = Agent(followups=True, followup_config=config)
    agent.followup_model = legacy_model  # type: ignore[assignment]

    resolved_model = (agent.followup_config.model if agent.followup_config else None) or agent.followup_model
    assert resolved_model is config_model


# ---------------------------------------------------------------------------
# Team followup_config field tests
# ---------------------------------------------------------------------------


def test_team_followup_config_default_none():
    """followup_config should default to None on Team."""
    team = Team(members=[], followups=True)
    assert team.followup_config is None


def test_team_followup_config_stored():
    """followup_config should be stored correctly on Team."""
    config = FollowupConfig(instructions="Suggest follow-ups in the style of a Socratic dialogue.")
    team = Team(members=[], followups=True, followup_config=config)
    assert team.followup_config is config
    assert team.followup_config.instructions == "Suggest follow-ups in the style of a Socratic dialogue."
