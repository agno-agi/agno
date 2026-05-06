from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent.agent import Agent
from agno.learn.config import LearnedKnowledgeConfig, LearningMode
from agno.learn.machine import LearningMachine
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


# =============================================================================
# Sync get_system_message tests
# =============================================================================


class TestGetSystemMessageLearningContext:
    def test_learning_context_included_when_enabled(self, mock_db, mock_model, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=True,
        )
        team.model = mock_model
        _set_learning_machine(team)

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

        from agno.run import RunContext

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


# =============================================================================
# Async aget_system_message tests
# =============================================================================


class TestAgetSystemMessageLearningContext:
    @pytest.mark.asyncio
    async def test_async_learning_context_included(self, mock_db, mock_model, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=True,
        )
        team.model = mock_model
        _set_learning_machine(team)

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

        from agno.run import RunContext

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


# =============================================================================
# requires_history auto-enable tests
# =============================================================================


class TestSetLearningMachineHistory:
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


# =============================================================================
# Learning context position tests
# =============================================================================


class TestLearningContextPosition:
    def test_learning_context_after_identity_before_knowledge(self, mock_db, mock_model, member_agent):
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

    def test_empty_learning_context_not_added(self, mock_db, mock_model, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
            add_learnings_to_context=True,
        )
        team.model = mock_model
        _set_learning_machine(team)

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

    def test_learning_true_creates_default_machine(self, mock_db, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=True,
        )
        _set_learning_machine(team)

        assert team._learning is not None
        assert isinstance(team._learning, LearningMachine)

    def test_learning_false_no_machine(self, mock_db, member_agent):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            db=mock_db,
            learning=False,
        )
        _set_learning_machine(team)

        assert team._learning is None

    def test_learning_without_db_warns(self, member_agent, caplog):
        team = Team(
            id="test-team",
            name="Test Team",
            members=[member_agent],
            learning=True,
        )
        _set_learning_machine(team)

        assert team._learning is None
