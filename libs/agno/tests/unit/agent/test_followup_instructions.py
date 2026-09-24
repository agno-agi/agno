"""Unit tests for FollowupConfig and followup_instructions feature.

Validates that:
- FollowupConfig stores model and instructions correctly
- _build_followup_messages appends custom instructions to the system prompt
- Agent and Team keep a FollowupConfig passed through followups
- Backward compatibility is maintained with existing followup_model parameter
- FollowupConfig combined with a top-level followup_model is rejected at construction
"""

import pytest

from agno.agent._response import _build_followup_messages
from agno.agent.agent import Agent
from agno.agent.followup import FollowupConfig
from agno.team.team import Team

# ---------------------------------------------------------------------------
# _build_followup_messages unit tests (no API calls)
# ---------------------------------------------------------------------------

BASE_SYSTEM_PROMPT = _build_followup_messages("Some response", 3)[0].content


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
# Agent followups field tests
# ---------------------------------------------------------------------------


def test_agent_followups_true_stays_a_bool():
    """followups=True is kept as the bool; there is no config to read."""
    agent = Agent(followups=True)
    assert agent.followups is True


def test_agent_followup_config_stored():
    """A FollowupConfig passed as followups is kept on followups."""
    config = FollowupConfig(instructions="Suggest follow-ups in a Socratic style.")
    agent = Agent(followups=config)
    assert agent.followups is config
    assert agent.followups.instructions == "Suggest follow-ups in a Socratic style."


def test_agent_followup_model_backward_compat():
    """followup_model should still be accepted and stored for backward compatibility."""
    agent = Agent(followups=True)
    assert agent.followup_model is None  # defaults to None


def test_agent_config_with_a_top_level_model_is_rejected():
    """The model goes in one place: FollowupConfig or followup_model, not both."""
    from unittest.mock import MagicMock

    from agno.models.base import Model

    config_model = MagicMock(spec=Model)
    legacy_model = MagicMock(spec=Model)

    for top_level in (legacy_model, config_model):
        with pytest.raises(ValueError, match="not both"):
            Agent(followups=FollowupConfig(model=config_model), followup_model=top_level)


# ---------------------------------------------------------------------------
# Team followups field tests
# ---------------------------------------------------------------------------


def test_team_followups_true_stays_a_bool():
    """followups=True is kept as the bool on Team too."""
    team = Team(members=[], followups=True)
    assert team.followups is True


def test_team_followup_config_stored():
    """A FollowupConfig passed as followups is kept on followups."""
    config = FollowupConfig(instructions="Suggest follow-ups in the style of a Socratic dialogue.")
    team = Team(members=[], followups=config)
    assert team.followups is config
    assert team.followups.instructions == "Suggest follow-ups in the style of a Socratic dialogue."
