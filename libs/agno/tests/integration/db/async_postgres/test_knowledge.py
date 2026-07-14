"""Integration tests for the Knowledge related methods of the AsyncPostgresDb class"""

import time
from typing import List

import pytest
import pytest_asyncio

from agno.db.postgres import AsyncPostgresDb
from agno.db.schemas.knowledge import KnowledgeRow


@pytest_asyncio.fixture(autouse=True)
async def cleanup_knowledge(async_postgres_db_real: AsyncPostgresDb):
    """Fixture to clean-up knowledge rows after each test"""
    yield

    try:
        knowledge_table = await async_postgres_db_real._get_table("knowledge")
        async with async_postgres_db_real.async_session_factory() as session:
            await session.execute(knowledge_table.delete())
            await session.commit()
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture
def sample_knowledge_row() -> KnowledgeRow:
    """Fixture returning a sample KnowledgeRow"""
    return KnowledgeRow(
        id="test_knowledge_1",
        name="Test Knowledge Document",
        description="A test document for knowledge management",
        metadata={"category": "testing", "priority": "high"},
        type="document",
        size=1024,
        linked_to="test_agent_1",
        access_count=0,
        status="active",
        status_message="Knowledge is ready",
        created_at=int(time.time()),
        updated_at=int(time.time()),
        external_id="ext_123",
    )


@pytest.fixture
def sample_knowledge_rows() -> List[KnowledgeRow]:
    """Fixture returning multiple sample KnowledgeRows"""
    rows = []
    for i in range(5):
        rows.append(
            KnowledgeRow(
                id=f"test_knowledge_{i}",
                name=f"Test Knowledge Document {i}",
                description=f"A test document {i} for knowledge management",
                metadata={"category": "testing", "index": i},
                type="document" if i % 2 == 0 else "file",
                size=1024 + i * 100,
                linked_to=f"test_agent_{i % 2}",
                access_count=i,
                status="active" if i % 3 != 0 else "inactive",
                created_at=int(time.time()) + i,
                updated_at=int(time.time()) + i,
            )
        )
    return rows


@pytest.mark.asyncio
async def test_upsert_knowledge_content(async_postgres_db_real: AsyncPostgresDb, sample_knowledge_row: KnowledgeRow):
    """Test upserting knowledge content"""
    # First insert
    result = await async_postgres_db_real.upsert_knowledge_content(sample_knowledge_row)

    assert result is not None
    assert result.id == "test_knowledge_1"
    assert result.name == "Test Knowledge Document"
    assert result.description == "A test document for knowledge management"

    # Update the knowledge
    sample_knowledge_row.description = "Updated description"
    sample_knowledge_row.access_count = 5
    updated_result = await async_postgres_db_real.upsert_knowledge_content(sample_knowledge_row)

    assert updated_result is not None
    assert updated_result.description == "Updated description"
    assert updated_result.access_count == 5


@pytest.mark.asyncio
async def test_get_knowledge_content(async_postgres_db_real: AsyncPostgresDb, sample_knowledge_row: KnowledgeRow):
    """Test getting a single knowledge content"""
    # First upsert the knowledge
    await async_postgres_db_real.upsert_knowledge_content(sample_knowledge_row)

    # Now get it back
    result = await async_postgres_db_real.get_knowledge_content("test_knowledge_1")

    assert result is not None
    assert isinstance(result, KnowledgeRow)
    assert result.id == "test_knowledge_1"
    assert result.name == "Test Knowledge Document"
    assert result.metadata["category"] == "testing"


@pytest.mark.asyncio
async def test_get_knowledge_content_not_found(async_postgres_db_real: AsyncPostgresDb):
    """Test getting knowledge content that doesn't exist"""
    result = await async_postgres_db_real.get_knowledge_content("nonexistent_id")

    assert result is None


@pytest.mark.asyncio
async def test_get_knowledge_contents_all(
    async_postgres_db_real: AsyncPostgresDb, sample_knowledge_rows: List[KnowledgeRow]
):
    """Test getting all knowledge contents"""
    # Insert all knowledge rows
    for row in sample_knowledge_rows:
        await async_postgres_db_real.upsert_knowledge_content(row)

    # Get all contents
    contents, total_count = await async_postgres_db_real.get_knowledge_contents()

    assert len(contents) == 5
    assert total_count == 5
    assert all(isinstance(row, KnowledgeRow) for row in contents)


@pytest.mark.asyncio
async def test_get_knowledge_contents_with_pagination(
    async_postgres_db_real: AsyncPostgresDb, sample_knowledge_rows: List[KnowledgeRow]
):
    """Test getting knowledge contents with pagination"""
    # Insert all knowledge rows
    for row in sample_knowledge_rows:
        await async_postgres_db_real.upsert_knowledge_content(row)

    # Test pagination - get first page
    contents, total_count = await async_postgres_db_real.get_knowledge_contents(limit=2, page=1)

    assert len(contents) == 2
    assert total_count == 5

    # Test pagination - get second page
    contents, total_count = await async_postgres_db_real.get_knowledge_contents(limit=2, page=2)

    assert len(contents) == 2
    assert total_count == 5

    # Test pagination - get last page
    contents, total_count = await async_postgres_db_real.get_knowledge_contents(limit=2, page=3)

    assert len(contents) == 1  # Only 1 item on last page
    assert total_count == 5


@pytest.mark.asyncio
async def test_get_knowledge_contents_with_sorting(
    async_postgres_db_real: AsyncPostgresDb, sample_knowledge_rows: List[KnowledgeRow]
):
    """Test getting knowledge contents with sorting"""
    # Insert all knowledge rows
    for row in sample_knowledge_rows:
        await async_postgres_db_real.upsert_knowledge_content(row)

    # Sort by name ascending
    contents, total_count = await async_postgres_db_real.get_knowledge_contents(sort_by="name", sort_order="asc")

    assert len(contents) == 5
    # Should be ordered by name
    names = [content.name for content in contents]
    assert names == sorted(names)

    # Sort by created_at descending
    contents, total_count = await async_postgres_db_real.get_knowledge_contents(sort_by="created_at", sort_order="desc")

    assert len(contents) == 5
    # Should be ordered by created_at (newest first)
    created_at_times = [content.created_at for content in contents]
    assert created_at_times == sorted(created_at_times, reverse=True)


@pytest.mark.asyncio
async def test_delete_knowledge_content(async_postgres_db_real: AsyncPostgresDb, sample_knowledge_row: KnowledgeRow):
    """Test deleting knowledge content"""
    # First insert the knowledge
    await async_postgres_db_real.upsert_knowledge_content(sample_knowledge_row)

    # Verify it exists
    result = await async_postgres_db_real.get_knowledge_content("test_knowledge_1")
    assert result is not None

    # Delete it
    await async_postgres_db_real.delete_knowledge_content("test_knowledge_1")

    # Verify it's gone
    result = await async_postgres_db_real.get_knowledge_content("test_knowledge_1")
    assert result is None


@pytest.mark.asyncio
async def test_upsert_knowledge_content_partial_data(async_postgres_db_real: AsyncPostgresDb):
    """Test upserting knowledge content with minimal data"""
    minimal_knowledge = KnowledgeRow(
        id="minimal_knowledge",
        name="Minimal Knowledge",
        description="Basic description",
    )

    result = await async_postgres_db_real.upsert_knowledge_content(minimal_knowledge)

    assert result is not None
    assert result.id == "minimal_knowledge"
    assert result.name == "Minimal Knowledge"
    assert result.description == "Basic description"

    # Verify we can retrieve it
    retrieved = await async_postgres_db_real.get_knowledge_content("minimal_knowledge")
    assert retrieved is not None
    assert retrieved.name == "Minimal Knowledge"


@pytest.mark.asyncio
async def test_upsert_knowledge_content_update_metadata(
    async_postgres_db_real: AsyncPostgresDb, sample_knowledge_row: KnowledgeRow
):
    """Test updating knowledge content metadata"""
    # First insert
    await async_postgres_db_real.upsert_knowledge_content(sample_knowledge_row)

    # Update metadata
    sample_knowledge_row.metadata = {"category": "updated", "new_field": "new_value"}
    sample_knowledge_row.status = "updated"
    sample_knowledge_row.access_count = 10

    result = await async_postgres_db_real.upsert_knowledge_content(sample_knowledge_row)

    assert result is not None
    assert result.metadata["category"] == "updated"
    assert result.metadata["new_field"] == "new_value"
    assert result.status == "updated"
    assert result.access_count == 10

    # Verify the update persisted
    retrieved = await async_postgres_db_real.get_knowledge_content("test_knowledge_1")
    assert retrieved.metadata["category"] == "updated"
    assert retrieved.status == "updated"
    assert retrieved.access_count == 10


@pytest.mark.asyncio
async def test_knowledge_content_with_null_fields(async_postgres_db_real: AsyncPostgresDb):
    """Test knowledge content with some null/None fields"""
    knowledge_with_nulls = KnowledgeRow(
        id="null_fields_knowledge",
        name="Knowledge with Nulls",
        description="Has some null fields",
        metadata=None,  # This should be allowed
        type=None,
        size=None,
        linked_to=None,
        access_count=None,
        status=None,
        status_message=None,
        created_at=None,
        updated_at=None,
        external_id=None,
    )

    result = await async_postgres_db_real.upsert_knowledge_content(knowledge_with_nulls)

    assert result is not None
    assert result.id == "null_fields_knowledge"
    assert result.name == "Knowledge with Nulls"

    # Verify we can retrieve it
    retrieved = await async_postgres_db_real.get_knowledge_content("null_fields_knowledge")
    assert retrieved is not None
    assert retrieved.name == "Knowledge with Nulls"
