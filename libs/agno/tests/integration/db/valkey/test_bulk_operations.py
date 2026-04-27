"""Integration tests for ValkeyDb bulk operations using GLIDE Batch (pipeline)."""

import time as time_module
from datetime import datetime

from agno.db.base import SessionType
from agno.db.schemas.memory import UserMemory
from agno.db.valkey.valkey import ValkeyDb
from agno.session.agent import AgentSession
from agno.session.team import TeamSession

# -- upsert_memories --


def test_upsert_memories_insert(valkey_db: ValkeyDb):
    """Bulk upsert inserts new memories and returns deserialized results."""
    memories = [
        UserMemory(
            memory_id=f"bulk_mem_{i}",
            memory=f"Bulk test memory {i}",
            topics=[f"topic_{i}", "bulk"],
            user_id=f"user_{i}",
            agent_id="agent_1",
            updated_at=datetime.now(),
        )
        for i in range(5)
    ]

    results = valkey_db.upsert_memories(memories)

    assert len(results) == 5
    for i, result in enumerate(results):
        assert isinstance(result, UserMemory)
        assert result.memory_id == f"bulk_mem_{i}"
        assert result.user_id == f"user_{i}"
        assert result.topics is not None
        assert f"topic_{i}" in result.topics


def test_upsert_memories_update(valkey_db: ValkeyDb):
    """Bulk upsert updates existing memories."""
    # Insert initial
    initial = [
        UserMemory(
            memory_id=f"upd_mem_{i}",
            memory=f"Original memory {i}",
            topics=["original"],
            user_id=f"user_{i}",
            updated_at=datetime.now(),
        )
        for i in range(3)
    ]
    valkey_db.upsert_memories(initial)

    # Update
    updated = [
        UserMemory(
            memory_id=f"upd_mem_{i}",
            memory=f"Updated memory {i}",
            topics=["updated"],
            user_id=f"user_{i}",
            agent_id=f"new_agent_{i}",
            updated_at=datetime.now(),
        )
        for i in range(3)
    ]
    results = valkey_db.upsert_memories(updated)

    assert len(results) == 3
    for i, result in enumerate(results):
        assert isinstance(result, UserMemory)
        assert "Updated memory" in result.memory
        assert result.topics == ["updated"]
        assert result.agent_id == f"new_agent_{i}"


def test_upsert_memories_without_deserialize(valkey_db: ValkeyDb):
    """Bulk upsert returns dicts when deserialize=False."""
    memories = [
        UserMemory(
            memory_id=f"raw_mem_{i}",
            memory=f"Raw memory {i}",
            user_id="user_1",
            updated_at=datetime.now(),
        )
        for i in range(3)
    ]

    results = valkey_db.upsert_memories(memories, deserialize=False)

    assert len(results) == 3
    for result in results:
        assert isinstance(result, dict)
        assert "memory_id" in result


def test_upsert_memories_empty_list(valkey_db: ValkeyDb):
    """Bulk upsert with empty list returns empty list."""
    results = valkey_db.upsert_memories([])
    assert results == []


def test_upsert_memories_verifiable_via_get(valkey_db: ValkeyDb):
    """Memories inserted via bulk upsert are retrievable via get_user_memory."""
    memories = [
        UserMemory(
            memory_id=f"verify_mem_{i}",
            memory=f"Verifiable memory {i}",
            user_id="user_1",
            agent_id="agent_1",
            updated_at=datetime.now(),
        )
        for i in range(3)
    ]
    valkey_db.upsert_memories(memories)

    for i in range(3):
        result = valkey_db.get_user_memory(memory_id=f"verify_mem_{i}")
        assert result is not None
        assert isinstance(result, UserMemory)
        assert result.memory == f"Verifiable memory {i}"


# -- delete_user_memories --


def test_delete_user_memories_bulk(valkey_db: ValkeyDb):
    """Bulk delete removes specified memories."""
    memories = [
        UserMemory(
            memory_id=f"del_mem_{i}",
            memory=f"Delete me {i}",
            user_id="user_1",
            updated_at=datetime.now(),
        )
        for i in range(4)
    ]
    valkey_db.upsert_memories(memories)

    # Delete first two
    valkey_db.delete_user_memories(["del_mem_0", "del_mem_1"])

    assert valkey_db.get_user_memory(memory_id="del_mem_0") is None
    assert valkey_db.get_user_memory(memory_id="del_mem_1") is None
    assert valkey_db.get_user_memory(memory_id="del_mem_2") is not None
    assert valkey_db.get_user_memory(memory_id="del_mem_3") is not None


def test_delete_user_memories_with_user_id_filter(valkey_db: ValkeyDb):
    """Bulk delete with user_id only deletes memories belonging to that user."""
    memories = [
        UserMemory(memory_id="alice_mem", memory="Alice", user_id="alice", updated_at=datetime.now()),
        UserMemory(memory_id="bob_mem", memory="Bob", user_id="bob", updated_at=datetime.now()),
    ]
    valkey_db.upsert_memories(memories)

    # Bob tries to delete Alice's memory
    valkey_db.delete_user_memories(["alice_mem"], user_id="bob")
    assert valkey_db.get_user_memory(memory_id="alice_mem") is not None

    # Alice deletes her own
    valkey_db.delete_user_memories(["alice_mem"], user_id="alice")
    assert valkey_db.get_user_memory(memory_id="alice_mem") is None


def test_delete_user_memories_empty_list(valkey_db: ValkeyDb):
    """Bulk delete with empty list is a no-op."""
    valkey_db.delete_user_memories([])  # Should not raise


# -- upsert_sessions --


def test_upsert_sessions_agent(valkey_db: ValkeyDb):
    """Bulk upsert inserts multiple agent sessions."""
    sessions = [
        AgentSession(
            session_id=f"bulk_sess_{i}",
            agent_id=f"agent_{i}",
            user_id="user_1",
            session_data={"session_name": f"Session {i}"},
            created_at=int(time_module.time()),
        )
        for i in range(5)
    ]

    results = valkey_db.upsert_sessions(sessions)

    assert len(results) == 5
    for i, result in enumerate(results):
        assert isinstance(result, AgentSession)
        assert result.session_id == f"bulk_sess_{i}"
        assert result.agent_id == f"agent_{i}"


def test_upsert_sessions_mixed_types(valkey_db: ValkeyDb):
    """Bulk upsert handles mixed session types."""
    sessions = [
        AgentSession(
            session_id="agent_sess",
            agent_id="agent_1",
            user_id="user_1",
            created_at=int(time_module.time()),
        ),
        TeamSession(
            session_id="team_sess",
            team_id="team_1",
            user_id="user_1",
            created_at=int(time_module.time()),
        ),
    ]

    results = valkey_db.upsert_sessions(sessions)

    assert len(results) == 2
    assert isinstance(results[0], AgentSession)
    assert isinstance(results[1], TeamSession)


def test_upsert_sessions_user_id_ownership(valkey_db: ValkeyDb):
    """Bulk upsert rejects sessions that change user_id ownership."""
    # Insert session owned by alice
    alice_session = AgentSession(
        session_id="owned_sess",
        agent_id="agent_1",
        user_id="alice",
        created_at=int(time_module.time()),
    )
    valkey_db.upsert_session(alice_session)

    # Try to bulk-upsert same session_id with bob's user_id
    bob_session = AgentSession(
        session_id="owned_sess",
        agent_id="agent_1",
        user_id="bob",
        created_at=int(time_module.time()),
    )
    results = valkey_db.upsert_sessions([bob_session])

    # Should be rejected
    assert len(results) == 0

    # Original session unchanged
    original = valkey_db.get_session(session_id="owned_sess", session_type=SessionType.AGENT)
    assert original is not None
    assert original.user_id == "alice"


def test_upsert_sessions_verifiable_via_get(valkey_db: ValkeyDb):
    """Sessions inserted via bulk upsert are retrievable via get_session."""
    sessions = [
        AgentSession(
            session_id=f"verify_sess_{i}",
            agent_id="agent_1",
            user_id="user_1",
            created_at=int(time_module.time()),
        )
        for i in range(3)
    ]
    valkey_db.upsert_sessions(sessions)

    for i in range(3):
        result = valkey_db.get_session(session_id=f"verify_sess_{i}", session_type=SessionType.AGENT)
        assert result is not None
        assert isinstance(result, AgentSession)


def test_upsert_sessions_empty_list(valkey_db: ValkeyDb):
    """Bulk upsert with empty list returns empty list."""
    results = valkey_db.upsert_sessions([])
    assert results == []


# -- delete_sessions --


def test_delete_sessions_bulk(valkey_db: ValkeyDb):
    """Bulk delete removes specified sessions."""
    sessions = [
        AgentSession(
            session_id=f"del_sess_{i}",
            agent_id="agent_1",
            user_id="user_1",
            created_at=int(time_module.time()),
        )
        for i in range(4)
    ]
    valkey_db.upsert_sessions(sessions)

    # Delete first two
    valkey_db.delete_sessions(["del_sess_0", "del_sess_1"])

    assert valkey_db.get_session(session_id="del_sess_0", session_type=SessionType.AGENT) is None
    assert valkey_db.get_session(session_id="del_sess_1", session_type=SessionType.AGENT) is None
    assert valkey_db.get_session(session_id="del_sess_2", session_type=SessionType.AGENT) is not None
    assert valkey_db.get_session(session_id="del_sess_3", session_type=SessionType.AGENT) is not None


def test_delete_sessions_with_user_id_filter(valkey_db: ValkeyDb):
    """Bulk delete with user_id only deletes sessions belonging to that user."""
    alice = AgentSession(
        session_id="alice_sess",
        agent_id="agent_1",
        user_id="alice",
        created_at=int(time_module.time()),
    )
    bob = AgentSession(
        session_id="bob_sess",
        agent_id="agent_1",
        user_id="bob",
        created_at=int(time_module.time()),
    )
    valkey_db.upsert_sessions([alice, bob])

    # Bob tries to delete both
    valkey_db.delete_sessions(["alice_sess", "bob_sess"], user_id="bob")

    # Alice's session survives
    assert valkey_db.get_session(session_id="alice_sess", session_type=SessionType.AGENT) is not None
    # Bob's session is gone
    assert valkey_db.get_session(session_id="bob_sess", session_type=SessionType.AGENT) is None


def test_delete_sessions_empty_list(valkey_db: ValkeyDb):
    """Bulk delete with empty list is a no-op."""
    valkey_db.delete_sessions([])  # Should not raise


# -- create_spans --


def test_create_spans_bulk(valkey_db: ValkeyDb):
    """Bulk create_spans stores all spans retrievable via get_span."""
    from agno.tracing.schemas import Span

    now = datetime.now()
    spans = [
        Span(
            span_id=f"span_{i}",
            trace_id="trace_1",
            parent_span_id=None,
            name=f"test_span_{i}",
            span_kind="internal",
            status_code="OK",
            status_message=None,
            start_time=now,
            end_time=now,
            duration_ms=100,
            attributes={},
            created_at=now,
        )
        for i in range(5)
    ]

    valkey_db.create_spans(spans)

    for i in range(5):
        result = valkey_db.get_span(f"span_{i}")
        assert result is not None
        assert result.span_id == f"span_{i}"
        assert result.trace_id == "trace_1"


def test_create_spans_empty_list(valkey_db: ValkeyDb):
    """Bulk create_spans with empty list is a no-op."""
    valkey_db.create_spans([])  # Should not raise


# -- delete_eval_runs --


def test_delete_eval_runs_bulk(valkey_db: ValkeyDb):
    """Bulk delete removes specified eval runs and cleans up index entries."""
    from agno.db.schemas.evals import EvalRunRecord, EvalType

    eval_runs = [
        EvalRunRecord(
            run_id=f"eval_run_{i}",
            eval_type=EvalType.ACCURACY,
            eval_data={"score": 0.9 + i * 0.01},
            agent_id="agent_1",
            model_id="model_1",
        )
        for i in range(4)
    ]
    for run in eval_runs:
        valkey_db.create_eval_run(run)

    # Verify all exist
    for i in range(4):
        assert valkey_db.get_eval_run(f"eval_run_{i}") is not None

    # Delete first two
    valkey_db.delete_eval_runs(["eval_run_0", "eval_run_1"])

    assert valkey_db.get_eval_run("eval_run_0") is None
    assert valkey_db.get_eval_run("eval_run_1") is None
    assert valkey_db.get_eval_run("eval_run_2") is not None
    assert valkey_db.get_eval_run("eval_run_3") is not None


def test_delete_eval_runs_nonexistent(valkey_db: ValkeyDb):
    """Bulk delete with nonexistent IDs is a no-op."""
    valkey_db.delete_eval_runs(["nonexistent_1", "nonexistent_2"])  # Should not raise


def test_delete_eval_runs_empty_list(valkey_db: ValkeyDb):
    """Bulk delete with empty list is a no-op."""
    valkey_db.delete_eval_runs([])  # Should not raise
