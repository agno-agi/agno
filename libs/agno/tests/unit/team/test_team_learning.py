"""
Unit tests for Team learning context injection.

Tests cover:
- get_system_message / aget_system_message learning context injection
- _set_learning_machine initialization and configuration
- requires_history auto-enable for PROPOSE mode
- Store combinations and edge cases
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent.agent import Agent
from agno.learn.config import LearnedKnowledgeConfig, LearningMode, UserMemoryConfig, UserProfileConfig
from agno.learn.machine import LearningMachine
from agno.run import RunContext
from agno.session import TeamSession
from agno.team._init import _set_learning_machine
from agno.team._messages import aget_system_message, get_system_message
from agno.team.team import Team


def _mock_knowledge():
    kb = MagicMock()
    kb.search.return_value = []
    return kb


def _create_mock_db_class():
    from agno.db.base import BaseDb

    abstract_methods = {}
    for name in dir(BaseDb):
        attr = getattr(BaseDb, name, None)
        if getattr(attr, "__isabstractmethod__", False):
            abstract_methods[name] = MagicMock()
    return type("MockDb", (BaseDb,), abstract_methods)


@pytest.fixture
def mock_db():
    MockDbClass = _create_mock_db_class()
    db = MockDbClass()
    db.to_dict = MagicMock(return_value={"type": "postgres", "id": "test-db"})
    return db


@pytest.fixture
def mock_model():
    model = MagicMock()
    model.get_instructions_for_model = MagicMock(return_value=None)
    model.get_system_message_for_model = MagicMock(return_value=None)
    model.supports_native_structured_outputs = False
    model.supports_json_schema_outputs = False
    return model


@pytest.fixture
def member_agent():
    return Agent(id="member-agent", name="Member Agent", role="A test member")


def _make_team_with_learning(mock_db, mock_model, member_agent, **kwargs) -> Team:
    team = Team(
        id="test-team",
        name="Test Team",
        members=[member_agent],
        db=mock_db,
        learning=True,
        add_learnings_to_context=True,
        **kwargs,
    )
    team.model = mock_model
    _set_learning_machine(team)
    return team


# =============================================================================
# Sync get_system_message tests
# =============================================================================


class TestGetSystemMessageLearningContext:
    def test_learning_context_included_when_enabled(self, mock_db, mock_model, member_agent):
        team = _make_team_with_learning(mock_db, mock_model, member_agent)

        mock_context = "<user_profile>\nName: Test User\nRole: Developer\n</user_profile>"
        team._learning.build_context = MagicMock(return_value=mock_context)

        session = TeamSession(session_id="test-session")
        msg = get_system_message(team, session)

        assert msg is not None
        assert mock_context in msg.content
        team._learning.build_context.assert_called_once()

    def test_learning_context_excluded_when_disabled(self, mock_db, mock_model, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=False,
        )
        team.model = mock_model
        _set_learning_machine(team)

        mock_context = "<user_profile>\nName: Test User\n</user_profile>"
        team._learning.build_context = MagicMock(return_value=mock_context)

        session = TeamSession(session_id="test-session")
        msg = get_system_message(team, session)

        assert msg is not None
        assert "<user_profile>" not in msg.content
        team._learning.build_context.assert_not_called()

    def test_learning_context_not_called_when_no_learning(self, mock_model, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            learning=None,
        )
        team.model = mock_model

        session = TeamSession(session_id="test-session")
        msg = get_system_message(team, session)

        assert msg is not None
        assert team._learning is None

    def test_build_context_receives_correct_args(self, mock_db, mock_model, member_agent):
        team = Team(
            id="my-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=True,
        )
        team.model = mock_model
        _set_learning_machine(team)

        team._learning.build_context = MagicMock(return_value="")

        session = TeamSession(session_id="sess-123")
        run_context = RunContext(
            run_id="test-run",
            session_id="sess-123",
            user_id="user-456",
        )

        get_system_message(team, session, run_context=run_context)

        team._learning.build_context.assert_called_once_with(
            user_id="user-456",
            session_id="sess-123",
            team_id="my-team",
        )

    def test_learning_context_not_added_when_build_context_returns_none(self, mock_db, mock_model, member_agent):
        """Verify None from build_context doesn't add 'None' string to message."""
        team = _make_team_with_learning(mock_db, mock_model, member_agent)
        team._learning.build_context = MagicMock(return_value=None)

        session = TeamSession(session_id="test-session")
        msg = get_system_message(team, session)

        assert msg is not None
        assert "None" not in msg.content
        team._learning.build_context.assert_called_once()

    def test_learning_context_receives_none_values_without_run_context(self, mock_db, mock_model, member_agent):
        """Verify build_context receives None for user_id when no run_context provided."""
        team = _make_team_with_learning(mock_db, mock_model, member_agent)
        team._learning.build_context = MagicMock(return_value="")

        session = TeamSession(session_id="sess-123")
        get_system_message(team, session, run_context=None)

        team._learning.build_context.assert_called_once_with(
            user_id=None,
            session_id="sess-123",
            team_id="test-team",
        )

    def test_learning_context_forwards_empty_user_id(self, mock_db, mock_model, member_agent):
        """Verify empty string user_id is forwarded as-is, not normalized."""
        team = _make_team_with_learning(mock_db, mock_model, member_agent)
        team._learning.build_context = MagicMock(return_value="")

        session = TeamSession(session_id="sess-123")
        run_context = RunContext(
            run_id="test-run",
            session_id="sess-123",
            user_id="",
        )

        get_system_message(team, session, run_context=run_context)

        team._learning.build_context.assert_called_once_with(
            user_id="",
            session_id="sess-123",
            team_id="test-team",
        )

    def test_custom_system_message_bypasses_learning_context(self, mock_db, mock_model, member_agent):
        """Verify custom system_message returns early without calling build_context."""
        custom_msg = "You are a custom assistant."
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=True,
            system_message=custom_msg,
        )
        team.model = mock_model
        _set_learning_machine(team)

        team._learning.build_context = MagicMock(return_value="<user_profile>Test</user_profile>")

        session = TeamSession(session_id="test-session")
        msg = get_system_message(team, session)

        assert msg.content == custom_msg
        team._learning.build_context.assert_not_called()


# =============================================================================
# Async aget_system_message tests
# =============================================================================


class TestAgetSystemMessageLearningContext:
    @pytest.mark.asyncio
    async def test_async_learning_context_included(self, mock_db, mock_model, member_agent):
        team = _make_team_with_learning(mock_db, mock_model, member_agent)

        mock_context = "<user_memory>\nPrefers Python\n</user_memory>"
        team._learning.abuild_context = AsyncMock(return_value=mock_context)

        session = TeamSession(session_id="test-session")
        msg = await aget_system_message(team, session)

        assert msg is not None
        assert mock_context in msg.content
        team._learning.abuild_context.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_learning_context_excluded_when_disabled(self, mock_db, mock_model, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=False,
        )
        team.model = mock_model
        _set_learning_machine(team)

        team._learning.abuild_context = AsyncMock(return_value="<user_memory>Test</user_memory>")

        session = TeamSession(session_id="test-session")
        msg = await aget_system_message(team, session)

        assert msg is not None
        assert "<user_memory>" not in msg.content
        team._learning.abuild_context.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_async_build_context_receives_correct_args(self, mock_db, mock_model, member_agent):
        team = Team(
            id="async-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=True,
        )
        team.model = mock_model
        _set_learning_machine(team)

        team._learning.abuild_context = AsyncMock(return_value="")

        session = TeamSession(session_id="async-sess")
        run_context = RunContext(
            run_id="async-run",
            session_id="async-sess",
            user_id="async-user",
        )

        await aget_system_message(team, session, run_context=run_context)

        team._learning.abuild_context.assert_awaited_once_with(
            user_id="async-user",
            session_id="async-sess",
            team_id="async-team",
        )

    @pytest.mark.asyncio
    async def test_async_learning_context_not_added_when_returns_none(self, mock_db, mock_model, member_agent):
        """Verify None from abuild_context doesn't add 'None' string to message."""
        team = _make_team_with_learning(mock_db, mock_model, member_agent)
        team._learning.abuild_context = AsyncMock(return_value=None)

        session = TeamSession(session_id="test-session")
        msg = await aget_system_message(team, session)

        assert msg is not None
        assert "None" not in msg.content
        team._learning.abuild_context.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_empty_learning_context_not_added(self, mock_db, mock_model, member_agent):
        """Verify empty string from abuild_context is skipped."""
        team = _make_team_with_learning(mock_db, mock_model, member_agent)
        team._learning.abuild_context = AsyncMock(return_value="")

        session = TeamSession(session_id="test-session")
        msg = await aget_system_message(team, session)

        assert msg is not None
        assert "\n\n\n" not in msg.content
        team._learning.abuild_context.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_async_learning_context_receives_none_values_without_run_context(
        self, mock_db, mock_model, member_agent
    ):
        """Verify abuild_context receives None for user_id when no run_context provided."""
        team = _make_team_with_learning(mock_db, mock_model, member_agent)
        team._learning.abuild_context = AsyncMock(return_value="")

        session = TeamSession(session_id="async-sess")
        await aget_system_message(team, session, run_context=None)

        team._learning.abuild_context.assert_awaited_once_with(
            user_id=None,
            session_id="async-sess",
            team_id="test-team",
        )


# =============================================================================
# _set_learning_machine tests
# =============================================================================


class TestSetLearningMachine:
    def _make_team(self, mode: LearningMode, add_history: bool = False, db=None) -> Team:
        if db is None:
            MockDbClass = _create_mock_db_class()
            db = MockDbClass()
            db.to_dict = MagicMock(return_value={"type": "postgres", "id": "test-db"})

        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            db=db,
            learning=LearningMachine(
                learned_knowledge=LearnedKnowledgeConfig(
                    mode=mode,
                    knowledge=_mock_knowledge(),
                ),
            ),
            add_history_to_context=add_history,
        )
        return team

    def test_propose_enables_history(self):
        team = self._make_team(LearningMode.PROPOSE)
        assert team.add_history_to_context is False

        _set_learning_machine(team)
        assert team.add_history_to_context is True

    def test_propose_preserves_existing_history_true(self):
        team = self._make_team(LearningMode.PROPOSE, add_history=True)
        _set_learning_machine(team)
        assert team.add_history_to_context is True

    def test_agentic_does_not_enable_history(self):
        team = self._make_team(LearningMode.AGENTIC)
        _set_learning_machine(team)
        assert team.add_history_to_context is False

    def test_always_does_not_enable_history(self):
        team = self._make_team(LearningMode.ALWAYS)
        _set_learning_machine(team)
        assert team.add_history_to_context is False

    def test_learning_true_creates_default_machine_with_correct_config(self, mock_db, mock_model):
        """Verify learning=True creates LearningMachine with team db/model and default stores."""
        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            db=mock_db,
            learning=True,
        )
        team.model = mock_model
        _set_learning_machine(team)

        assert team._learning is not None
        assert isinstance(team._learning, LearningMachine)
        assert team._learning.db is mock_db
        assert team._learning.model is mock_model
        assert team._learning.user_profile is True
        assert team._learning.user_memory is True
        assert team.learning is True

    def test_learning_false_no_machine(self, mock_db):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            db=mock_db,
            learning=False,
        )
        _set_learning_machine(team)

        assert team._learning is None
        assert team._learning_init_attempted is True

    def test_learning_none_sets_none_and_marks_attempted(self, mock_db):
        """Verify learning=None sets _learning to None and marks init attempted."""
        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            db=mock_db,
            learning=None,
        )
        _set_learning_machine(team)

        assert team._learning is None
        assert team._learning_init_attempted is True

    def test_learning_without_db_warns_and_does_not_create_machine(self):
        """Verify learning=True without db logs warning and sets _learning to None."""
        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            learning=True,
        )
        _set_learning_machine(team)

        assert team._learning is None
        assert team._learning_init_attempted is True

    def test_injects_missing_db_and_model_into_provided_machine(self, mock_db, mock_model):
        """Verify _set_learning_machine injects team db/model when machine has None."""
        machine = LearningMachine(user_profile=True)
        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            db=mock_db,
            learning=machine,
        )
        team.model = mock_model
        _set_learning_machine(team)

        assert team._learning is machine
        assert machine.db is mock_db
        assert machine.model is mock_model

    def test_preserves_existing_machine_db_and_model(self, mock_db, mock_model):
        """Verify _set_learning_machine does not overwrite existing db/model on machine."""
        MockDbClass = _create_mock_db_class()
        existing_db = MockDbClass()
        existing_model = MagicMock()

        machine = LearningMachine(
            db=existing_db,
            model=existing_model,
            user_profile=True,
        )
        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            db=mock_db,
            learning=machine,
        )
        team.model = mock_model
        _set_learning_machine(team)

        assert team._learning is machine
        assert machine.db is existing_db
        assert machine.model is existing_model

    def test_does_not_mutate_public_learning_field(self, mock_db, mock_model):
        """Verify _set_learning_machine sets _learning without changing public learning field."""
        machine = LearningMachine(user_profile=True)
        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            db=mock_db,
            learning=machine,
        )
        team.model = mock_model
        _set_learning_machine(team)

        assert team.learning is machine
        assert team._learning is machine

        team2 = Team(
            id="test-team-2",
            name="Test Team 2",
            members=[Agent(id="b", name="B", role="test")],
            db=mock_db,
            learning=True,
        )
        _set_learning_machine(team2)

        assert team2.learning is True
        assert team2._learning is not None

    def test_user_profile_propose_enables_history(self, mock_db):
        """Verify UserProfileConfig with PROPOSE mode enables add_history_to_context."""
        machine = LearningMachine(
            user_profile=UserProfileConfig(mode=LearningMode.PROPOSE),
        )
        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            db=mock_db,
            learning=machine,
            add_history_to_context=False,
        )
        _set_learning_machine(team)

        assert team.add_history_to_context is True

    def test_user_memory_propose_enables_history(self, mock_db):
        """Verify UserMemoryConfig with PROPOSE mode enables add_history_to_context."""
        machine = LearningMachine(
            user_memory=UserMemoryConfig(mode=LearningMode.PROPOSE),
        )
        team = Team(
            id="test-team",
            name="Test Team",
            members=[Agent(id="a", name="A", role="test")],
            db=mock_db,
            learning=machine,
            add_history_to_context=False,
        )
        _set_learning_machine(team)

        assert team.add_history_to_context is True


# =============================================================================
# Learning context position tests
# =============================================================================


class TestLearningContextPosition:
    def test_learning_context_after_identity_before_knowledge(self, mock_db, mock_model, member_agent):
        """Verify learning context appears after description/role but before knowledge."""
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=True,
            description="Test description",
            role="Test role",
            instructions="Test instructions",
        )
        team.model = mock_model
        _set_learning_machine(team)

        mock_learning = "<user_profile>\nTest Learning Content\n</user_profile>"
        team._learning.build_context = MagicMock(return_value=mock_learning)

        session = TeamSession(session_id="test-session")
        msg = get_system_message(team, session)

        content = msg.content
        description_pos = content.find("<description>")
        role_pos = content.find("<your_role>")
        learning_pos = content.find("<user_profile>")

        assert description_pos < learning_pos
        assert role_pos < learning_pos

    def test_learning_context_before_knowledge_context(self, mock_db, mock_model, member_agent):
        """Verify learning context appears before knowledge context when both enabled."""
        mock_knowledge = MagicMock()
        mock_knowledge.build_context = MagicMock(return_value="<knowledge_marker>KB Content</knowledge_marker>")

        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=True,
            knowledge=mock_knowledge,
            search_knowledge=True,
            add_search_knowledge_instructions=True,
        )
        team.model = mock_model
        _set_learning_machine(team)

        mock_learning = "<user_profile>\nLearning Content\n</user_profile>"
        team._learning.build_context = MagicMock(return_value=mock_learning)

        session = TeamSession(session_id="test-session")
        msg = get_system_message(team, session)

        content = msg.content
        learning_pos = content.find("<user_profile>")
        knowledge_pos = content.find("<knowledge_marker>")

        assert learning_pos > 0
        assert knowledge_pos > 0
        assert learning_pos < knowledge_pos

    def test_empty_learning_context_not_added(self, mock_db, mock_model, member_agent):
        team = _make_team_with_learning(mock_db, mock_model, member_agent)
        team._learning.build_context = MagicMock(return_value="")

        session = TeamSession(session_id="test-session")
        msg = get_system_message(team, session)

        assert "\n\n\n" not in msg.content


# =============================================================================
# Configuration tests
# =============================================================================


class TestTeamLearningConfig:
    def test_add_learnings_to_context_default_true(self, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
        )
        assert team.add_learnings_to_context is True

    def test_add_learnings_to_context_can_be_disabled(self, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            add_learnings_to_context=False,
        )
        assert team.add_learnings_to_context is False


# =============================================================================
# Parametrized edge case tests
# =============================================================================


class TestLearningContextFalseyValues:
    @pytest.mark.parametrize("context_value", [None, ""])
    def test_falsey_learning_context_not_added_sync(self, mock_db, mock_model, member_agent, context_value):
        """Verify both None and empty string don't pollute system message."""
        team = _make_team_with_learning(mock_db, mock_model, member_agent)
        team._learning.build_context = MagicMock(return_value=context_value)

        session = TeamSession(session_id="test-session")
        msg = get_system_message(team, session)

        assert msg is not None
        if context_value is None:
            assert "None" not in msg.content
        assert "\n\n\n" not in msg.content
        team._learning.build_context.assert_called_once()

    @pytest.mark.parametrize("context_value", [None, ""])
    @pytest.mark.asyncio
    async def test_falsey_learning_context_not_added_async(self, mock_db, mock_model, member_agent, context_value):
        """Verify both None and empty string don't pollute async system message."""
        team = _make_team_with_learning(mock_db, mock_model, member_agent)
        team._learning.abuild_context = AsyncMock(return_value=context_value)

        session = TeamSession(session_id="test-session")
        msg = await aget_system_message(team, session)

        assert msg is not None
        if context_value is None:
            assert "None" not in msg.content
        assert "\n\n\n" not in msg.content
        team._learning.abuild_context.assert_awaited_once()
