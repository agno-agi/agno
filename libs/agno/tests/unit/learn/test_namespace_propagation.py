"""Tests verifying that namespace is propagated to upsert_learning() in all learn stores.

Regression tests for the bug where DecisionLogStore, UserMemoryStore, and
SessionContextStore called db.upsert_learning() without passing the namespace
parameter, causing entries from different agents to share the same
namespace=NULL bucket and contaminate each other's records.

EntityMemoryStore already passed namespace correctly; this test suite confirms
the same pattern is applied to the other three stores.
"""

from unittest.mock import MagicMock, patch

import pytest

from agno.learn.config import DecisionLogConfig, SessionContextConfig, UserMemoryConfig
from agno.learn.stores.decision_log import DecisionLog, DecisionLogStore
from agno.learn.stores.session_context import SessionContextStore
from agno.learn.stores.user_memory import UserMemoryStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_db():
    db = MagicMock()
    db.upsert_learning = MagicMock(return_value=None)
    return db


# ---------------------------------------------------------------------------
# DecisionLogStore
# ---------------------------------------------------------------------------


class TestDecisionLogStoreNamespacePropagation:
    """namespace from DecisionLogConfig must reach upsert_learning()."""

    def test_save_passes_namespace(self):
        """DecisionLogStore.save() must pass namespace=config.namespace."""
        db = _mock_db()
        store = DecisionLogStore(config=DecisionLogConfig(db=db, namespace="agent-42"))

        decision = DecisionLog(
            id="d1",
            agent_id="agent-42",
            decision="go left",
            reasoning="because reasons",
        )
        store.save(decision)

        db.upsert_learning.assert_called_once()
        call_kwargs = db.upsert_learning.call_args.kwargs
        assert call_kwargs.get("namespace") == "agent-42", (
            "DecisionLogStore.save() did not propagate namespace to upsert_learning()"
        )

    def test_save_passes_none_namespace_when_not_configured(self):
        """If no namespace is set, None is passed (no change in existing behaviour)."""
        db = _mock_db()
        store = DecisionLogStore(config=DecisionLogConfig(db=db))

        decision = DecisionLog(id="d2", agent_id="a", decision="stay", reasoning="ok")
        store.save(decision)

        call_kwargs = db.upsert_learning.call_args.kwargs
        assert call_kwargs.get("namespace") is None


# ---------------------------------------------------------------------------
# UserMemoryStore
# ---------------------------------------------------------------------------


class TestUserMemoryStoreNamespacePropagation:
    """namespace from UserMemoryConfig must reach upsert_learning()."""

    def test_save_passes_namespace(self):
        """UserMemoryStore.save() must pass namespace=config.namespace."""
        db = _mock_db()
        store = UserMemoryStore(config=UserMemoryConfig(db=db, namespace="team-x"))

        # Provide a minimal memories-like object that serialises to a non-empty dict.
        memories = MagicMock()
        with patch(
            "agno.learn.stores.user_memory.to_dict_safe", return_value={"key": "val"}
        ):
            store.save(user_id="user-1", memories=memories, agent_id="agent-1")

        db.upsert_learning.assert_called_once()
        call_kwargs = db.upsert_learning.call_args.kwargs
        assert call_kwargs.get("namespace") == "team-x", (
            "UserMemoryStore.save() did not propagate namespace to upsert_learning()"
        )

    def test_save_passes_none_namespace_when_not_configured(self):
        """If no namespace is set, None is passed."""
        db = _mock_db()
        store = UserMemoryStore(config=UserMemoryConfig(db=db))

        memories = MagicMock()
        with patch(
            "agno.learn.stores.user_memory.to_dict_safe", return_value={"key": "val"}
        ):
            store.save(user_id="user-1", memories=memories)

        call_kwargs = db.upsert_learning.call_args.kwargs
        assert call_kwargs.get("namespace") is None


# ---------------------------------------------------------------------------
# SessionContextStore
# ---------------------------------------------------------------------------


class TestSessionContextStoreNamespacePropagation:
    """namespace from SessionContextConfig must reach upsert_learning()."""

    def test_save_passes_namespace(self):
        """SessionContextStore.save() must pass namespace=config.namespace."""
        db = _mock_db()
        store = SessionContextStore(config=SessionContextConfig(db=db, namespace="global"))

        context = MagicMock()
        with patch(
            "agno.learn.stores.session_context.to_dict_safe", return_value={"summary": "x"}
        ):
            store.save(session_id="sess-1", context=context)

        db.upsert_learning.assert_called_once()
        call_kwargs = db.upsert_learning.call_args.kwargs
        assert call_kwargs.get("namespace") == "global", (
            "SessionContextStore.save() did not propagate namespace to upsert_learning()"
        )

    def test_save_passes_none_namespace_when_not_configured(self):
        """If no namespace is set, None is passed."""
        db = _mock_db()
        store = SessionContextStore(config=SessionContextConfig(db=db))

        context = MagicMock()
        with patch(
            "agno.learn.stores.session_context.to_dict_safe", return_value={"summary": "x"}
        ):
            store.save(session_id="sess-1", context=context)

        call_kwargs = db.upsert_learning.call_args.kwargs
        assert call_kwargs.get("namespace") is None
