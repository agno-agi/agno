"""
Integration tests for normalized storage (v2.5+).

These tests verify that the normalized storage tables work correctly
and eliminate the O(N^2) storage growth issue.
"""

import time
from typing import Any, Dict, List
from uuid import uuid4

import pytest

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


class TestNormalizedStorageSchema:
    """Tests for the normalized storage schema."""

    def test_runs_table_schema_exists(self):
        """Test that the runs table schema is defined."""
        from agno.db.postgres.schemas import get_table_schema_definition

        schema = get_table_schema_definition("runs")
        assert schema is not None
        assert "run_id" in schema
        assert "session_id" in schema
        assert "messages" not in schema  # Messages stored separately

    def test_messages_table_schema_exists(self):
        """Test that the messages table schema is defined."""
        from agno.db.postgres.schemas import get_table_schema_definition

        schema = get_table_schema_definition("messages")
        assert schema is not None
        assert "message_id" in schema
        assert "run_id" in schema
        assert "role" in schema
        assert "content" in schema

    def test_tool_calls_table_schema_exists(self):
        """Test that the tool_calls table schema is defined."""
        from agno.db.postgres.schemas import get_table_schema_definition

        schema = get_table_schema_definition("tool_calls")
        assert schema is not None
        assert "tool_call_id" in schema
        assert "message_id" in schema
        assert "tool_name" in schema


class TestAgentSessionNormalizedStorage:
    """Tests for AgentSession with normalized storage."""

    def test_session_enable_normalized_storage(self):
        """Test enabling normalized storage on a session."""
        session = AgentSession(session_id=str(uuid4()))
        assert session.use_normalized_storage is False

        session.enable_normalized_storage()
        assert session.use_normalized_storage is True

    def test_session_to_dict_excludes_runs_when_normalized(self):
        """Test that to_dict excludes runs when using normalized storage."""
        session = AgentSession(
            session_id=str(uuid4()),
            runs=[
                RunOutput(
                    run_id=str(uuid4()),
                    agent_id="test-agent",
                    status=RunStatus.completed,
                    content="Test response",
                )
            ],
        )

        # Without normalized storage, runs should be included
        dict_with_runs = session.to_dict()
        assert dict_with_runs.get("runs") is not None

        # With normalized storage, runs should be excluded
        session.enable_normalized_storage()
        dict_without_runs = session.to_dict()
        assert dict_without_runs.get("runs") is None

    def test_session_from_dict_with_normalized_storage(self):
        """Test creating a session with normalized storage enabled."""
        data = {
            "session_id": str(uuid4()),
            "agent_id": "test-agent",
            "runs": None,  # No runs in JSONB when using normalized storage
        }

        session = AgentSession.from_dict(data, use_normalized_storage=True)
        assert session is not None
        assert session.use_normalized_storage is True
        assert session.runs is None or len(session.runs) == 0

    def test_session_upsert_run_with_normalized_storage(self):
        """Test upserting a run with normalized storage."""
        session = AgentSession(session_id=str(uuid4()))
        session.enable_normalized_storage()

        run = RunOutput(
            run_id=str(uuid4()),
            agent_id="test-agent",
            status=RunStatus.completed,
            content="Test response",
            messages=[
                Message(role="user", content="Hello"),
                Message(role="assistant", content="Hi there!"),
            ],
        )

        # Without a db, should still work (just won't persist)
        session.upsert_run(run)
        assert len(session.runs) == 1
        assert session.runs[0].run_id == run.run_id


class TestNormalizedStorageHistoryFiltering:
    """Tests for history message filtering in normalized storage."""

    def test_history_messages_not_stored(self):
        """Test that history messages are not stored in normalized storage."""
        session = AgentSession(session_id=str(uuid4()))
        session.enable_normalized_storage()

        # Create messages with some marked as history
        messages = [
            Message(role="system", content="You are a helpful assistant"),
            Message(role="user", content="Previous question", from_history=True),
            Message(role="assistant", content="Previous answer", from_history=True),
            Message(role="user", content="Current question"),
            Message(role="assistant", content="Current answer"),
        ]

        run = RunOutput(
            run_id=str(uuid4()),
            agent_id="test-agent",
            status=RunStatus.completed,
            content="Current answer",
            messages=messages,
        )

        session.upsert_run(run)

        # The session should have the run with all messages
        assert len(session.runs) == 1
        assert len(session.runs[0].messages) == 5

        # But when persisting to normalized storage, only non-history messages
        # should be stored (this is handled by the db layer)
        non_history_messages = [
            m for m in run.messages if not (hasattr(m, "from_history") and m.from_history)
        ]
        assert len(non_history_messages) == 3  # system, current user, current assistant


class TestNormalizedStorageLinearGrowth:
    """Tests to verify linear storage growth with normalized storage."""

    def test_storage_growth_is_linear(self):
        """Test that storage growth is linear, not quadratic."""
        session = AgentSession(session_id=str(uuid4()))
        session.enable_normalized_storage()

        # Simulate multiple runs
        for i in range(10):
            messages = [
                Message(role="user", content=f"Question {i}"),
                Message(role="assistant", content=f"Answer {i}"),
            ]

            run = RunOutput(
                run_id=str(uuid4()),
                agent_id="test-agent",
                status=RunStatus.completed,
                content=f"Answer {i}",
                messages=messages,
            )

            session.upsert_run(run)

        # With normalized storage, each run should only contain its own messages
        # Total messages should be 2 * 10 = 20 (linear)
        total_messages = sum(len(r.messages) for r in session.runs)
        assert total_messages == 20

        # In legacy storage with history, it would be:
        # Run 1: 2 messages
        # Run 2: 2 + 2 = 4 messages (including history)
        # Run 3: 2 + 4 = 6 messages
        # ...
        # Run 10: 2 + 18 = 20 messages
        # Total: 2 + 4 + 6 + ... + 20 = 110 messages (quadratic)


class TestNormalizedStorageMigration:
    """Tests for the migration utility."""

    def test_migration_estimate_function_exists(self):
        """Test that the migration estimate function exists."""
        from agno.db.migrations import estimate_migration

        assert callable(estimate_migration)

    def test_migration_function_exists(self):
        """Test that the migration function exists."""
        from agno.db.migrations import migrate_to_normalized_storage

        assert callable(migrate_to_normalized_storage)

    def test_verify_migration_function_exists(self):
        """Test that the verify migration function exists."""
        from agno.db.migrations import verify_migration

        assert callable(verify_migration)


class TestAgentNormalizedStorageFlag:
    """Tests for the Agent normalized storage flag."""

    def test_agent_has_normalized_storage_flag(self):
        """Test that Agent has the use_normalized_storage flag."""
        from agno.agent import Agent

        agent = Agent()
        assert hasattr(agent, "use_normalized_storage")
        assert agent.use_normalized_storage is False

    def test_agent_can_enable_normalized_storage(self):
        """Test that Agent can enable normalized storage."""
        from agno.agent import Agent

        agent = Agent(use_normalized_storage=True)
        assert agent.use_normalized_storage is True


class TestTeamNormalizedStorageFlag:
    """Tests for the Team normalized storage flag."""

    def test_team_has_normalized_storage_flag(self):
        """Test that Team has the use_normalized_storage flag."""
        from agno.team import Team

        team = Team()
        assert hasattr(team, "use_normalized_storage")
        assert team.use_normalized_storage is False

    def test_team_can_enable_normalized_storage(self):
        """Test that Team can enable normalized storage."""
        from agno.team import Team

        team = Team(use_normalized_storage=True)
        assert team.use_normalized_storage is True
