"""Integration tests for AsyncOracleDb knowledge methods"""

import time

import pytest

from agno.db.oracle import AsyncOracleDb
from agno.db.schemas.knowledge import KnowledgeRow


@pytest.mark.asyncio
async def test_upsert_and_get_knowledge_content(async_oracle_db_real):
    """Test upserting and retrieving knowledge content"""
    knowledge = KnowledgeRow(
        id="test-knowledge-1",
        name="Test Document",
        description="A test document",
        type="document",
        size=1024,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    # Upsert knowledge
    result = await async_oracle_db_real.upsert_knowledge_content(knowledge)
    assert result is not None
    assert result.id == "test-knowledge-1"

    # Get knowledge back
    retrieved = await async_oracle_db_real.get_knowledge_content("test-knowledge-1")
    assert retrieved is not None
    assert retrieved.name == "Test Document"
    assert retrieved.type == "document"


@pytest.mark.asyncio
async def test_get_knowledge_contents_with_pagination(async_oracle_db_real):
    """Test getting knowledge contents with pagination"""
    # Create multiple knowledge items
    for i in range(5):
        knowledge = KnowledgeRow(
            id=f"test-pagination-knowledge-{i}",
            name=f"Document {i}",
            description=f"Test document {i}",
            type="document",
            size=1024 + i * 100,
            created_at=int(time.time()),
            updated_at=int(time.time()),
        )
        await async_oracle_db_real.upsert_knowledge_content(knowledge)

    # Get with pagination
    contents, total = await async_oracle_db_real.get_knowledge_contents(limit=2, page=1)
    assert len(contents) <= 2
    assert total >= 5


@pytest.mark.asyncio
async def test_delete_knowledge_content(async_oracle_db_real):
    """Test deleting knowledge content"""
    knowledge = KnowledgeRow(
        id="test-delete-knowledge",
        name="To be deleted",
        description="Document to be deleted",
        type="document",
        size=512,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    # Upsert and then delete
    await async_oracle_db_real.upsert_knowledge_content(knowledge)
    await async_oracle_db_real.delete_knowledge_content("test-delete-knowledge")

    # Verify it's gone
    retrieved = await async_oracle_db_real.get_knowledge_content("test-delete-knowledge")
    assert retrieved is None


@pytest.mark.asyncio
async def test_upsert_knowledge_updates_existing(async_oracle_db_real):
    """Test that upserting updates existing knowledge"""
    knowledge = KnowledgeRow(
        id="test-update-knowledge",
        name="Original Name",
        description="Original description",
        type="document",
        size=2048,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    # Initial upsert
    await async_oracle_db_real.upsert_knowledge_content(knowledge)

    # Update
    knowledge.name = "Updated Name"
    await async_oracle_db_real.upsert_knowledge_content(knowledge)

    # Verify update
    retrieved = await async_oracle_db_real.get_knowledge_content("test-update-knowledge")
    assert retrieved is not None
    assert retrieved.name == "Updated Name"


@pytest.mark.asyncio
async def test_upsert_knowledge_with_empty_description_round_trips(async_oracle_db_real):
    """Oracle stores the empty string as NULL; the row must still write and validate on read"""
    knowledge = KnowledgeRow(
        id="test-knowledge-empty-desc",
        name="Empty Description Document",
        description="",
        metadata={"origin": "test"},
        type="Text",
        size=10,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    result = await async_oracle_db_real.upsert_knowledge_content(knowledge)
    assert result is not None

    retrieved = await async_oracle_db_real.get_knowledge_content("test-knowledge-empty-desc")
    assert retrieved is not None
    assert retrieved.description == ""
    assert retrieved.metadata == {"origin": "test"}


@pytest.mark.asyncio
async def test_fresh_instance_against_existing_tables_serializes_json(async_oracle_db_real, async_oracle_engine):
    """A new AsyncOracleDb over already-created tables must keep JSON binds working.

    Regression: the exists-path reflected the table with autoload_with, which loses
    the OracleJSON column type and made dict binds fail with DPY-3002.
    """
    seed = KnowledgeRow(
        id="test-knowledge-seed",
        name="Seed Document",
        description="seed",
        type="Text",
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )
    assert await async_oracle_db_real.upsert_knowledge_content(seed) is not None

    fresh_db = AsyncOracleDb(
        db_engine=async_oracle_engine,
        session_table="test_sessions",
        memory_table="test_memories",
        metrics_table="test_metrics",
        eval_table="test_evals",
        knowledge_table="test_knowledge",
    )
    knowledge = KnowledgeRow(
        id="test-knowledge-fresh",
        name="Fresh Instance Document",
        description="written by a second instance",
        metadata={"tier": "pro", "hosts": 3},
        type="Text",
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )

    result = await fresh_db.upsert_knowledge_content(knowledge)
    assert result is not None

    retrieved = await fresh_db.get_knowledge_content("test-knowledge-fresh")
    assert retrieved is not None
    assert retrieved.metadata == {"tier": "pro", "hosts": 3}
