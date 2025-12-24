"""Integration tests for string sanitization in AsyncPostgresDb operations.

These tests verify that null bytes (\x00) are properly removed from strings
before storing them in PostgreSQL to prevent CharacterNotInRepertoireError.
"""

import time

import pytest
import pytest_asyncio

from agno.db.postgres import AsyncPostgresDb
from agno.db.schemas.knowledge import KnowledgeRow
from agno.db.schemas.memory import UserMemory
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.session.agent import AgentSession


@pytest_asyncio.fixture(autouse=True)
async def cleanup_all_tables(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up all test data after each test"""
    yield

    try:
        # Clean up all tables
        for table_type in ["memories", "sessions", "knowledge", "evals", "traces", "spans", "culture"]:
            try:
                table = await async_postgres_db_real._get_table(table_type)
                async with async_postgres_db_real.async_session_factory() as session:
                    await session.execute(table.delete())
                    await session.commit()
            except Exception:
                pass  # Ignore cleanup errors for tables that don't exist
    except Exception:
        pass  # Ignore cleanup errors


# =============================================================================
# Memory Sanitization Tests
# =============================================================================


@pytest.mark.asyncio
async def test_memory_upsert_sanitizes_input_field(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in memory.input field are sanitized."""
    memory = UserMemory(
        memory_id="test_memory_null_input",
        memory={"content": "Test memory"},
        input="Test input with\x00null byte",
        user_id="test_user_1",
        agent_id="test_agent_1",
    )

    # Should not raise CharacterNotInRepertoireError
    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    assert result.input == "Test input withnull byte"  # Null byte removed
    assert "\x00" not in result.input

    # Verify stored value doesn't have null bytes
    retrieved = await async_postgres_db_real.get_user_memory("test_memory_null_input", "test_user_1")
    assert retrieved is not None
    assert "\x00" not in retrieved.input
    assert retrieved.input == "Test input withnull byte"


@pytest.mark.asyncio
async def test_memory_upsert_sanitizes_feedback_field(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in memory.feedback field are sanitized."""
    memory = UserMemory(
        memory_id="test_memory_null_feedback",
        memory={"content": "Test memory"},
        input="Test input",
        feedback="Feedback with\x00null\x00bytes",
        user_id="test_user_1",
        agent_id="test_agent_1",
    )

    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    assert result.feedback == "Feedback withnullbytes"  # Null bytes removed
    assert "\x00" not in result.feedback

    # Verify stored value
    retrieved = await async_postgres_db_real.get_user_memory("test_memory_null_feedback", "test_user_1")
    assert retrieved is not None
    assert "\x00" not in retrieved.feedback


@pytest.mark.asyncio
async def test_memory_upsert_sanitizes_nested_jsonb_strings(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in nested JSONB fields (memory, topics) are sanitized."""
    memory = UserMemory(
        memory_id="test_memory_null_jsonb",
        memory={"content": "Test\x00memory", "description": "Desc\x00with\x00nulls"},
        input="Test input",
        topics=["topic1\x00", "topic2", "topic\x003"],
        user_id="test_user_1",
        agent_id="test_agent_1",
        created_at=int(time.time()),
    )

    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    assert "\x00" not in result.memory["content"]
    assert "\x00" not in result.memory["description"]
    assert all("\x00" not in topic for topic in result.topics)

    # Verify stored values
    retrieved = await async_postgres_db_real.get_user_memory("test_memory_null_jsonb", "test_user_1")
    assert retrieved is not None
    assert "\x00" not in retrieved.memory["content"]
    assert all("\x00" not in topic for topic in retrieved.topics)


@pytest.mark.asyncio
async def test_memory_upsert_handles_multiple_null_bytes(async_postgres_db_real: AsyncPostgresDb):
    """Test that multiple null bytes are all removed."""
    memory = UserMemory(
        memory_id="test_memory_multiple_nulls",
        memory={"content": "Test"},
        input="\x00\x00\x00Multiple\x00nulls\x00\x00",
        feedback="\x00\x00\x00",
        user_id="test_user_1",
        agent_id="test_agent_1",
    )

    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    assert result.input == "Multiplenulls"  # All null bytes removed
    assert result.feedback == ""  # Only null bytes, so empty string
    assert "\x00" not in result.input
    assert "\x00" not in result.feedback


# =============================================================================
# Knowledge Sanitization Tests
# =============================================================================


@pytest.mark.asyncio
async def test_knowledge_upsert_sanitizes_string_fields(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in knowledge string fields are sanitized."""
    knowledge = KnowledgeRow(
        id="test_knowledge_null_strings",
        name="Knowledge\x00Name",
        description="Description\x00with\x00nulls",
        type="document\x00",
        status="active\x00",
        status_message="Message\x00here",
        linked_to="link\x00to",
        external_id="ext\x00id",
        metadata={"key": "value"},
        created_at=int(time.time()),
    )

    result = await async_postgres_db_real.upsert_knowledge_content(knowledge)

    assert result is not None
    # Verify stored values (sanitization happens in DB, so check retrieved value)
    retrieved = await async_postgres_db_real.get_knowledge_content("test_knowledge_null_strings")
    assert retrieved is not None
    assert "\x00" not in retrieved.name
    assert "\x00" not in retrieved.description
    assert "\x00" not in retrieved.type
    assert "\x00" not in retrieved.status
    assert "\x00" not in retrieved.status_message
    assert "\x00" not in retrieved.linked_to
    assert "\x00" not in retrieved.external_id


@pytest.mark.asyncio
async def test_knowledge_upsert_sanitizes_metadata_jsonb(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in knowledge.metadata JSONB field are sanitized."""
    knowledge = KnowledgeRow(
        id="test_knowledge_null_metadata",
        name="Test Knowledge",
        description="Test description",
        metadata={
            "key1": "value\x00with\x00nulls",
            "key2": ["list\x00item1", "list\x00item2"],
            "key3": {"nested": "nested\x00value", "nested_list": ["a\x00", "b\x00"]},
        },
        created_at=int(time.time()),
    )

    result = await async_postgres_db_real.upsert_knowledge_content(knowledge)

    assert result is not None
    # upsert_knowledge_content returns the original object, so verify stored values from DB
    retrieved = await async_postgres_db_real.get_knowledge_content("test_knowledge_null_metadata")
    assert retrieved is not None
    assert "\x00" not in retrieved.metadata["key1"]
    assert all("\x00" not in item for item in retrieved.metadata["key2"])
    assert "\x00" not in retrieved.metadata["key3"]["nested"]
    assert all("\x00" not in item for item in retrieved.metadata["key3"]["nested_list"])


# =============================================================================
# Session Sanitization Tests
# =============================================================================


@pytest.mark.asyncio
async def test_session_upsert_sanitizes_nested_jsonb_fields(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in session JSONB fields are sanitized."""
    agent_run = RunOutput(
        run_id="test_run_1",
        agent_id="test_agent_1",
        user_id="test_user_1",
        status=RunStatus.completed,
        messages=[],
    )

    session = AgentSession(
        session_id="test_session_null_jsonb",
        agent_id="test_agent_1",
        user_id="test_user_1",
        session_data={"name": "Session\x00Name", "data": "Value\x00here"},
        agent_data={"name": "Agent\x00Name", "model": "gpt-4"},
        metadata={"key": "value\x00with\x00nulls"},
        runs=[agent_run],
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    result = await async_postgres_db_real.upsert_session(session)

    assert result is not None
    assert "\x00" not in result.session_data["name"]
    assert "\x00" not in result.session_data["data"]
    assert "\x00" not in result.agent_data["name"]
    assert "\x00" not in result.metadata["key"]

    # Verify stored values
    from agno.db.base import SessionType

    retrieved = await async_postgres_db_real.get_session("test_session_null_jsonb", SessionType.AGENT)
    assert retrieved is not None
    assert "\x00" not in str(retrieved.session_data)
    assert "\x00" not in str(retrieved.agent_data)
    assert "\x00" not in str(retrieved.metadata)


@pytest.mark.asyncio
async def test_session_upsert_sanitizes_summary_field(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in session summary field are sanitized."""
    from agno.session.summary import SessionSummary

    agent_run = RunOutput(
        run_id="test_run_2",
        agent_id="test_agent_1",
        user_id="test_user_1",
        status=RunStatus.completed,
        messages=[],
    )

    session = AgentSession(
        session_id="test_session_null_summary",
        agent_id="test_agent_1",
        user_id="test_user_1",
        session_data={},
        summary=SessionSummary(summary="Summary\x00with\x00null\x00bytes"),
        runs=[agent_run],
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    result = await async_postgres_db_real.upsert_session(session)

    assert result is not None
    assert result.summary is not None
    assert "\x00" not in result.summary.summary

    # Verify stored value
    from agno.db.base import SessionType

    retrieved = await async_postgres_db_real.get_session("test_session_null_summary", SessionType.AGENT)
    assert retrieved is not None
    assert retrieved.summary is not None
    assert "\x00" not in retrieved.summary.summary


# =============================================================================
# Trace and Span Sanitization Tests
# =============================================================================


@pytest.mark.asyncio
async def test_trace_upsert_sanitizes_fields(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in trace fields are sanitized."""
    from datetime import datetime, timezone

    from agno.tracing.schemas import Trace

    trace = Trace(
        trace_id="test_trace_null",
        name="Trace\x00Name",
        status="OK",
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        duration_ms=100,
        total_spans=1,
        error_count=0,
        run_id=None,
        session_id=None,
        user_id=None,
        agent_id=None,
        team_id=None,
        workflow_id=None,
        created_at=datetime.now(timezone.utc),
    )

    # upsert_trace returns None, so we verify by querying
    await async_postgres_db_real.upsert_trace(trace)

    # Verify stored values by querying directly
    async with async_postgres_db_real.async_session_factory() as session:
        traces_table = await async_postgres_db_real._get_table("traces")
        result_query = await session.execute(traces_table.select().where(traces_table.c.trace_id == "test_trace_null"))
        row = result_query.fetchone()
        assert row is not None
        assert "\x00" not in str(row.name) if row.name else True
        assert "\x00" not in str(row.status) if row.status else True


@pytest.mark.asyncio
async def test_span_upsert_sanitizes_fields(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in span fields are sanitized."""
    from datetime import datetime, timezone

    from agno.tracing.schemas import Span

    span = Span(
        span_id="test_span_null",
        trace_id="test_trace_null",
        parent_span_id=None,
        name="Span\x00Name",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=datetime.now(timezone.utc),
        end_time=datetime.now(timezone.utc),
        duration_ms=50,
        attributes={"key": "value\x00with\x00nulls", "list": ["item\x00"]},
        created_at=datetime.now(timezone.utc),
    )

    # create_span returns None, so we verify by querying
    await async_postgres_db_real.create_span(span)

    # Verify stored values
    async with async_postgres_db_real.async_session_factory() as session:
        spans_table = await async_postgres_db_real._get_table("spans")
        result_query = await session.execute(spans_table.select().where(spans_table.c.span_id == "test_span_null"))
        row = result_query.fetchone()
        assert row is not None
        assert "\x00" not in str(row.name) if row.name else True
        assert "\x00" not in str(row.attributes) if row.attributes else True


# =============================================================================
# Eval Sanitization Tests
# =============================================================================


@pytest.mark.asyncio
async def test_eval_upsert_sanitizes_fields(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in eval fields are sanitized."""
    from agno.db.schemas.evals import EvalRunRecord, EvalType

    eval_run = EvalRunRecord(
        run_id="test_eval_null",
        eval_type=EvalType.ACCURACY,
        name="Eval\x00Name",
        evaluated_component_name="Component\x00Name",
        eval_data={"key": "value\x00with\x00nulls", "list": ["item\x00"]},
        eval_input={"input": "input\x00value"},
        agent_id="test_agent_1",
        created_at=int(time.time()),
    )

    result = await async_postgres_db_real.create_eval_run(eval_run)

    assert result is not None
    # create_eval_run returns the original object, so verify stored values from DB
    retrieved = await async_postgres_db_real.get_eval_run("test_eval_null")
    assert retrieved is not None
    assert "\x00" not in retrieved.name
    assert "\x00" not in retrieved.evaluated_component_name
    assert "\x00" not in str(retrieved.eval_data)
    assert "\x00" not in str(retrieved.eval_input)


# =============================================================================
# Cultural Knowledge Sanitization Tests
# =============================================================================


@pytest.mark.asyncio
async def test_cultural_knowledge_upsert_sanitizes_fields(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in cultural knowledge fields are sanitized."""
    from agno.db.schemas.culture import CulturalKnowledge

    cultural_knowledge = CulturalKnowledge(
        id="test_culture_null",
        name="Culture\x00Name",
        summary="Summary\x00with\x00nulls",
        input="Input\x00value",
        content="Content\x00with\x00nulls",
        metadata={"meta": "meta\x00value", "nested": {"inner": "inner\x00value"}},
    )

    result = await async_postgres_db_real.upsert_cultural_knowledge(cultural_knowledge)

    assert result is not None
    assert "\x00" not in result.name
    assert "\x00" not in result.summary
    assert "\x00" not in result.input
    assert "\x00" not in result.content
    assert "\x00" not in str(result.metadata)

    # Verify stored values
    retrieved = await async_postgres_db_real.get_cultural_knowledge("test_culture_null")
    assert retrieved is not None
    assert "\x00" not in retrieved.name
    assert "\x00" not in retrieved.content
    assert "\x00" not in str(retrieved.metadata)


# =============================================================================
# Edge Cases
# =============================================================================


@pytest.mark.asyncio
async def test_sanitization_preserves_normal_strings(async_postgres_db_real: AsyncPostgresDb):
    """Test that normal strings without null bytes are preserved unchanged."""
    memory = UserMemory(
        memory_id="test_memory_normal",
        memory={"content": "Normal content"},
        input="Normal input string",
        feedback="Normal feedback",
        user_id="test_user_1",
        agent_id="test_agent_1",
    )

    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    assert result.input == "Normal input string"
    assert result.feedback == "Normal feedback"
    assert result.memory["content"] == "Normal content"


@pytest.mark.asyncio
async def test_sanitization_handles_none_values(async_postgres_db_real: AsyncPostgresDb):
    """Test that None values are handled correctly (not sanitized)."""
    memory = UserMemory(
        memory_id="test_memory_none",
        memory={"content": "Test"},
        input=None,
        feedback=None,
        user_id="test_user_1",
        agent_id="test_agent_1",
    )

    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    assert result.input is None
    assert result.feedback is None


@pytest.mark.asyncio
async def test_sanitization_handles_empty_strings(async_postgres_db_real: AsyncPostgresDb):
    """Test that empty strings are handled correctly."""
    memory = UserMemory(
        memory_id="test_memory_empty",
        memory={"content": "Test"},
        input="",
        feedback="",
        user_id="test_user_1",
        agent_id="test_agent_1",
    )

    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    assert result.input == ""
    assert result.feedback == ""


@pytest.mark.asyncio
async def test_sanitization_handles_only_null_bytes(async_postgres_db_real: AsyncPostgresDb):
    """Test that strings containing only null bytes become empty strings."""
    memory = UserMemory(
        memory_id="test_memory_only_nulls",
        memory={"content": "Test"},
        input="\x00\x00\x00",
        user_id="test_user_1",
        agent_id="test_agent_1",
    )

    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    assert result.input == ""  # All null bytes removed, empty string


@pytest.mark.asyncio
async def test_sanitization_handles_deeply_nested_structures(async_postgres_db_real: AsyncPostgresDb):
    """Test that null bytes in deeply nested JSONB structures are sanitized."""
    memory = UserMemory(
        memory_id="test_memory_deep_nested",
        memory={
            "level1": {
                "level2": {
                    "level3": {
                        "level4": "deep\x00value",
                        "list": [{"item": "item\x00value"}, {"item2": "item2\x00"}],
                    }
                }
            },
            "simple": "simple\x00value",
        },
        input="Test input",
        user_id="test_user_1",
        agent_id="test_agent_1",
        created_at=int(time.time()),
    )

    result = await async_postgres_db_real.upsert_user_memory(memory)

    assert result is not None
    # Verify all nested strings are sanitized
    assert "\x00" not in result.memory["level1"]["level2"]["level3"]["level4"]
    assert "\x00" not in result.memory["level1"]["level2"]["level3"]["list"][0]["item"]
    assert "\x00" not in result.memory["level1"]["level2"]["level3"]["list"][1]["item2"]
    assert "\x00" not in result.memory["simple"]

    # Verify stored values
    retrieved = await async_postgres_db_real.get_user_memory("test_memory_deep_nested", "test_user_1")
    assert retrieved is not None
    assert "\x00" not in str(retrieved.memory)
