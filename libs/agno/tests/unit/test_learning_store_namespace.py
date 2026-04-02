from unittest.mock import MagicMock

from agno.learn.config import (
    DecisionLogConfig,
    SessionContextConfig,
    UserMemoryConfig,
)
from agno.learn.machine import LearningMachine
from agno.learn.schemas import DecisionLog, Memories, SessionContext
from agno.learn.stores.decision_log import DecisionLogStore
from agno.learn.stores.session_context import SessionContextStore
from agno.learn.stores.user_memory import UserMemoryStore


def _mock_db():
    db = MagicMock()
    db.upsert_learning = MagicMock()
    return db


# ---------------------------------------------------------------------------
# DecisionLogStore — namespace passed to upsert_learning
# ---------------------------------------------------------------------------


class TestDecisionLogStoreNamespace:
    def test_save_passes_namespace_from_config(self):
        db = _mock_db()
        store = DecisionLogStore(config=DecisionLogConfig(db=db, namespace="content_team"))
        decision = DecisionLog(
            id="d1",
            decision="use caching",
            reasoning="reduce latency",
            agent_id="agent1",
        )

        store.save(decision)

        db.upsert_learning.assert_called_once()
        assert db.upsert_learning.call_args.kwargs["namespace"] == "content_team"

    def test_save_passes_none_when_no_namespace(self):
        db = _mock_db()
        store = DecisionLogStore(config=DecisionLogConfig(db=db))
        decision = DecisionLog(
            id="d2",
            decision="skip cache",
            reasoning="not needed",
            agent_id="agent1",
        )

        store.save(decision)

        db.upsert_learning.assert_called_once()
        assert db.upsert_learning.call_args.kwargs["namespace"] is None


# ---------------------------------------------------------------------------
# UserMemoryStore — namespace passed to upsert_learning
# ---------------------------------------------------------------------------


class TestUserMemoryStoreNamespace:
    def test_save_passes_namespace_from_config(self):
        db = _mock_db()
        store = UserMemoryStore(config=UserMemoryConfig(db=db, namespace="sales_west"))
        memories = Memories(user_id="u1", memories=[])

        store.save(user_id="u1", memories=memories)

        db.upsert_learning.assert_called_once()
        assert db.upsert_learning.call_args.kwargs["namespace"] == "sales_west"

    def test_save_passes_none_when_no_namespace(self):
        db = _mock_db()
        store = UserMemoryStore(config=UserMemoryConfig(db=db))
        memories = Memories(user_id="u1", memories=[])

        store.save(user_id="u1", memories=memories)

        db.upsert_learning.assert_called_once()
        assert db.upsert_learning.call_args.kwargs["namespace"] is None


# ---------------------------------------------------------------------------
# SessionContextStore — namespace passed to upsert_learning
# ---------------------------------------------------------------------------


class TestSessionContextStoreNamespace:
    def test_save_passes_namespace_from_config(self):
        db = _mock_db()
        store = SessionContextStore(config=SessionContextConfig(db=db, namespace="engineering"))
        context = SessionContext(session_id="s1", summary="test session")

        store.save(session_id="s1", context=context)

        db.upsert_learning.assert_called_once()
        assert db.upsert_learning.call_args.kwargs["namespace"] == "engineering"

    def test_save_passes_none_when_no_namespace(self):
        db = _mock_db()
        store = SessionContextStore(config=SessionContextConfig(db=db))
        context = SessionContext(session_id="s1", summary="test session")

        store.save(session_id="s1", context=context)

        db.upsert_learning.assert_called_once()
        assert db.upsert_learning.call_args.kwargs["namespace"] is None


# ---------------------------------------------------------------------------
# LearningMachine — namespace propagates to store configs
# ---------------------------------------------------------------------------


class TestLearningMachineNamespacePropagation:
    def test_namespace_propagates_to_decision_log_config(self):
        db = _mock_db()
        lm = LearningMachine(
            db=db,
            namespace="content_team",
            decision_log=True,
        )
        store = lm.stores["decision_log"]
        assert store.config.namespace == "content_team"

    def test_namespace_propagates_to_user_memory_config(self):
        db = _mock_db()
        lm = LearningMachine(
            db=db,
            namespace="sales_west",
            user_memory=True,
        )
        store = lm.stores["user_memory"]
        assert store.config.namespace == "sales_west"

    def test_namespace_propagates_to_session_context_config(self):
        db = _mock_db()
        lm = LearningMachine(
            db=db,
            namespace="engineering",
            session_context=True,
        )
        store = lm.stores["session_context"]
        assert store.config.namespace == "engineering"

    def test_explicit_config_namespace_not_overridden(self):
        db = _mock_db()
        lm = LearningMachine(
            db=db,
            namespace="global_default",
            decision_log=DecisionLogConfig(namespace="explicit_ns"),
        )
        store = lm.stores["decision_log"]
        # Explicit config namespace takes precedence over machine namespace
        assert store.config.namespace == "explicit_ns"

    def test_default_namespace_is_global(self):
        db = _mock_db()
        lm = LearningMachine(
            db=db,
            decision_log=True,
            user_memory=True,
            session_context=True,
        )
        # LearningMachine defaults to namespace="global", propagated to all stores
        assert lm.stores["decision_log"].config.namespace == "global"
        assert lm.stores["user_memory"].config.namespace == "global"
        assert lm.stores["session_context"].config.namespace == "global"
