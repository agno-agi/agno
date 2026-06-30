"""Integration tests for the Knowledge related methods of the PostgresDb class"""

import time

import pytest

from agno.db.postgres.postgres import PostgresDb
from agno.db.schemas.knowledge import KnowledgeRow


@pytest.fixture(autouse=True)
def cleanup_knowledge(postgres_db_real: PostgresDb):
    """Fixture to clean-up knowledge rows after each test"""
    yield

    with postgres_db_real.Session() as session:
        try:
            knowledge_table = postgres_db_real._get_table("knowledge")
            session.execute(knowledge_table.delete())
            session.commit()
        except Exception:
            session.rollback()


@pytest.fixture
def sample_knowledge_document() -> KnowledgeRow:
    """Fixture returning a sample KnowledgeRow for a document"""
    return KnowledgeRow(
        id="test_knowledge_doc_1",
        name="API Documentation",
        description="Comprehensive API documentation for the platform",
        metadata={
            "format": "markdown",
            "language": "en",
            "version": "1.0.0",
            "tags": ["api", "documentation", "reference"],
            "author": "Engineering Team",
            "last_reviewed": "2024-01-15",
        },
        type="document",
        size=15420,
        linked_to=None,
        access_count=45,
        status="active",
        status_message="Document is up to date and ready for use",
        created_at=int(time.time()) - 3600,  # 1 hour ago
        updated_at=int(time.time()) - 1800,  # 30 minutes ago
    )


@pytest.fixture
def sample_knowledge_dataset() -> KnowledgeRow:
    """Fixture returning a sample KnowledgeRow for a dataset"""
    return KnowledgeRow(
        id="test_knowledge_dataset_1",
        name="Customer Support Conversations",
        description="Training dataset containing customer support chat conversations",
        metadata={
            "format": "json",
            "schema_version": "2.1",
            "total_conversations": 5000,
            "date_range": {"start": "2023-01-01", "end": "2023-12-31"},
            "categories": ["support", "billing", "technical", "general"],
            "data_quality": {"completeness": 0.98, "accuracy": 0.95, "consistency": 0.92},
        },
        type="dataset",
        size=2048000,  # ~2MB
        linked_to="training_pipeline_v2",
        access_count=12,
        status="processed",
        status_message="Dataset has been processed and is ready for training",
        created_at=int(time.time()) - 7200,  # 2 hours ago
        updated_at=int(time.time()) - 3600,  # 1 hour ago
    )


@pytest.fixture
def sample_knowledge_model() -> KnowledgeRow:
    """Fixture returning a sample KnowledgeRow for a model"""
    return KnowledgeRow(
        id="test_knowledge_model_1",
        name="Text Classification Model v3.2",
        description="Fine-tuned BERT model for classifying customer support tickets",
        metadata={
            "model_type": "bert-base-uncased",
            "framework": "transformers",
            "training_data": "customer_support_conversations",
            "performance_metrics": {"accuracy": 0.94, "precision": 0.92, "recall": 0.91, "f1_score": 0.915},
            "hyperparameters": {"learning_rate": 2e-5, "batch_size": 32, "epochs": 10},
            "deployment_info": {
                "environment": "production",
                "endpoint": "https://api.example.com/classify",
                "version": "3.2",
            },
        },
        type="model",
        size=440000000,  # ~440MB
        linked_to="classification_service",
        access_count=234,
        status="deployed",
        status_message="Model is deployed and serving predictions",
        created_at=int(time.time()) - 86400,  # 1 day ago
        updated_at=int(time.time()) - 7200,  # 2 hours ago
    )


def test_upsert_knowledge_content_document(postgres_db_real: PostgresDb, sample_knowledge_document: KnowledgeRow):
    """Test upserting a knowledge document"""
    result = postgres_db_real.upsert_knowledge_content(sample_knowledge_document)

    assert result is not None
    assert isinstance(result, KnowledgeRow)
    assert result.id == sample_knowledge_document.id
    assert result.name == sample_knowledge_document.name
    assert result.description == sample_knowledge_document.description
    assert result.type == sample_knowledge_document.type
    assert result.metadata == sample_knowledge_document.metadata
    assert result.size == sample_knowledge_document.size


def test_upsert_knowledge_content_dataset(postgres_db_real: PostgresDb, sample_knowledge_dataset: KnowledgeRow):
    """Test upserting a knowledge dataset"""
    result = postgres_db_real.upsert_knowledge_content(sample_knowledge_dataset)

    assert result is not None
    assert isinstance(result, KnowledgeRow)
    assert result.id == sample_knowledge_dataset.id
    assert result.name == sample_knowledge_dataset.name
    assert result.type == sample_knowledge_dataset.type
    assert result.linked_to == sample_knowledge_dataset.linked_to


def test_upsert_knowledge_content_model(postgres_db_real: PostgresDb, sample_knowledge_model: KnowledgeRow):
    """Test upserting a knowledge model"""
    result = postgres_db_real.upsert_knowledge_content(sample_knowledge_model)

    assert result is not None
    assert isinstance(result, KnowledgeRow)
    assert result.id == sample_knowledge_model.id
    assert result.name == sample_knowledge_model.name
    assert result.type == sample_knowledge_model.type
    assert result.status == sample_knowledge_model.status


def test_upsert_knowledge_content_update(postgres_db_real: PostgresDb, sample_knowledge_document: KnowledgeRow):
    """Test updating existing knowledge content"""
    # Insert initial content
    postgres_db_real.upsert_knowledge_content(sample_knowledge_document)

    # Update the content
    sample_knowledge_document.description = "Updated API documentation with new endpoints"
    sample_knowledge_document.access_count = 50
    sample_knowledge_document.status = "updated"

    result = postgres_db_real.upsert_knowledge_content(sample_knowledge_document)

    assert result is not None
    assert result.description == "Updated API documentation with new endpoints"
    assert result.access_count == 50
    assert result.status == "updated"


def test_get_knowledge_content_by_id(postgres_db_real: PostgresDb, sample_knowledge_document: KnowledgeRow):
    """Test getting knowledge content by ID"""
    postgres_db_real.upsert_knowledge_content(sample_knowledge_document)

    result = postgres_db_real.get_knowledge_content(sample_knowledge_document.id)  # type: ignore

    assert result is not None
    assert isinstance(result, KnowledgeRow)
    assert result.id == sample_knowledge_document.id
    assert result.name == sample_knowledge_document.name
    assert result.description == sample_knowledge_document.description
    assert result.metadata == sample_knowledge_document.metadata


def test_get_knowledge_contents_no_pagination(postgres_db_real: PostgresDb):
    """Test getting all knowledge contents without pagination"""
    # Create multiple knowledge rows
    knowledge_rows = []
    for i in range(3):
        knowledge_row = KnowledgeRow(
            id=f"test_knowledge_{i}",
            name=f"Test Knowledge {i}",
            description=f"Description for test knowledge {i}",
            type="document",
            size=1000 + (i * 100),
            access_count=i * 5,
            status="active",
        )
        knowledge_rows.append(knowledge_row)
        postgres_db_real.upsert_knowledge_content(knowledge_row)

    result, total_count = postgres_db_real.get_knowledge_contents()

    assert isinstance(result, list)
    assert len(result) == 3
    assert total_count == 3
    assert all(isinstance(row, KnowledgeRow) for row in result)


def test_get_knowledge_contents_with_pagination(postgres_db_real: PostgresDb):
    """Test getting knowledge contents with pagination"""
    # Create multiple knowledge rows
    for i in range(5):
        knowledge_row = KnowledgeRow(
            id=f"test_knowledge_page_{i}",
            name=f"Test Knowledge Page {i}",
            description=f"Description for test knowledge page {i}",
            type="document",
            size=1000 + (i * 100),
            access_count=i * 2,
            status="active",
        )
        postgres_db_real.upsert_knowledge_content(knowledge_row)

    # Test pagination
    page1, total_count = postgres_db_real.get_knowledge_contents(limit=2, page=1)
    assert len(page1) == 2
    assert total_count == 5

    page2, _ = postgres_db_real.get_knowledge_contents(limit=2, page=2)
    assert len(page2) == 2

    # Verify no overlap
    page1_ids = {row.id for row in page1}
    page2_ids = {row.id for row in page2}
    assert len(page1_ids & page2_ids) == 0


def test_get_knowledge_contents_with_sorting(postgres_db_real: PostgresDb):
    """Test getting knowledge contents with sorting"""
    # Create knowledge rows with different sizes for sorting
    knowledge_rows = []
    sizes = [5000, 1000, 3000]
    for i, size in enumerate(sizes):
        knowledge_row = KnowledgeRow(
            id=f"test_knowledge_sort_{i}",
            name=f"Test Knowledge Sort {i}",
            description=f"Description for sorting test {i}",
            type="document",
            size=size,
            access_count=i * 3,
            status="active",
        )
        knowledge_rows.append(knowledge_row)
        postgres_db_real.upsert_knowledge_content(knowledge_row)
        time.sleep(0.1)  # Small delay for created_at timestamps

    # Test sorting by size ascending
    results_asc, _ = postgres_db_real.get_knowledge_contents(sort_by="size", sort_order="asc")
    assert len(results_asc) == 3
    assert results_asc[0].size == 1000
    assert results_asc[1].size == 3000
    assert results_asc[2].size == 5000


def test_delete_knowledge_content(postgres_db_real: PostgresDb, sample_knowledge_document: KnowledgeRow):
    """Test deleting knowledge content"""
    postgres_db_real.upsert_knowledge_content(sample_knowledge_document)

    # Verify it exists
    knowledge = postgres_db_real.get_knowledge_content(sample_knowledge_document.id)  # type: ignore
    assert knowledge is not None

    # Delete it
    postgres_db_real.delete_knowledge_content(sample_knowledge_document.id)  # type: ignore

    # Verify it's gone
    knowledge = postgres_db_real.get_knowledge_content(sample_knowledge_document.id)  # type: ignore
    assert knowledge is None


def test_knowledge_table_creation_and_structure(postgres_db_real: PostgresDb):
    """Test that the knowledge table is created with the correct structure"""
    knowledge_table = postgres_db_real._get_table("knowledge", create_table_if_not_found=True)

    assert knowledge_table is not None
    assert knowledge_table.name == "test_knowledge"
    assert knowledge_table.schema == postgres_db_real.db_schema

    # Verify essential columns exist
    column_names = [col.name for col in knowledge_table.columns]
    expected_columns = [
        "id",
        "name",
        "description",
        "metadata",
        "type",
        "size",
        "linked_to",
        "access_count",
        "status",
        "status_message",
        "created_at",
        "updated_at",
    ]
    for col in expected_columns:
        assert col in column_names, f"Missing column: {col}"


def test_comprehensive_knowledge_row_fields(postgres_db_real: PostgresDb):
    """Test that all KnowledgeRow fields are properly handled"""
    comprehensive_knowledge = KnowledgeRow(
        id="comprehensive_knowledge_test",
        name="Comprehensive Knowledge Test",
        description="A comprehensive knowledge row to test all field handling",
        metadata={
            "comprehensive": True,
            "nested_data": {
                "level1": {"level2": {"data": "deeply nested value", "numbers": [1, 2, 3, 4, 5], "boolean": True}}
            },
            "arrays": ["item1", "item2", "item3"],
            "performance_data": {
                "metrics": {"accuracy": 0.98, "precision": 0.97, "recall": 0.96, "f1": 0.965},
                "benchmarks": [
                    {"name": "test1", "score": 95.5},
                    {"name": "test2", "score": 98.2},
                    {"name": "test3", "score": 92.8},
                ],
            },
        },
        type="comprehensive_test",
        size=1234567,
        linked_to="related_comprehensive_item",
        access_count=999,
        status="comprehensive_active",
        status_message="All fields are populated and being tested comprehensively",
        created_at=int(time.time()) - 86400,
        updated_at=int(time.time()) - 3600,
    )

    # Upsert the comprehensive knowledge
    result = postgres_db_real.upsert_knowledge_content(comprehensive_knowledge)
    assert result is not None

    # Retrieve and verify all fields are preserved
    retrieved = postgres_db_real.get_knowledge_content(comprehensive_knowledge.id)  # type: ignore
    assert retrieved is not None
    assert isinstance(retrieved, KnowledgeRow)

    # Verify all fields
    assert retrieved.id == comprehensive_knowledge.id
    assert retrieved.name == comprehensive_knowledge.name
    assert retrieved.description == comprehensive_knowledge.description
    assert retrieved.metadata == comprehensive_knowledge.metadata
    assert retrieved.type == comprehensive_knowledge.type
    assert retrieved.size == comprehensive_knowledge.size
    assert retrieved.linked_to == comprehensive_knowledge.linked_to
    assert retrieved.access_count == comprehensive_knowledge.access_count
    assert retrieved.status == comprehensive_knowledge.status
    assert retrieved.status_message == comprehensive_knowledge.status_message
    assert retrieved.created_at == comprehensive_knowledge.created_at
    assert retrieved.updated_at == comprehensive_knowledge.updated_at


def test_knowledge_with_auto_generated_id(postgres_db_real: PostgresDb):
    """Test auto id generation for knowledge content"""
    knowledge_without_id = KnowledgeRow(
        name="Auto ID Knowledge",
        description="Knowledge row that should get an auto-generated ID",
        type="auto_test",
        size=500,
        status="active",
    )

    # Asserting the ID was generated
    assert knowledge_without_id.id is not None
    assert len(knowledge_without_id.id) > 0

    result = postgres_db_real.upsert_knowledge_content(knowledge_without_id)
    assert result is not None
    assert result.id == knowledge_without_id.id


def test_knowledge_with_none_optional_fields(postgres_db_real: PostgresDb):
    """Test knowledge row with minimal required fields and None optional fields"""
    minimal_knowledge = KnowledgeRow(
        id="minimal_knowledge_test",
        name="Minimal Knowledge",
        description="Knowledge with minimal fields",
        metadata=None,
        type=None,
        size=None,
        linked_to=None,
        access_count=None,
        status=None,
        status_message=None,
        created_at=None,
        updated_at=None,
    )

    result = postgres_db_real.upsert_knowledge_content(minimal_knowledge)
    assert result is not None
    assert result.name == "Minimal Knowledge"
    assert result.description == "Knowledge with minimal fields"

    # Retrieve and verify None fields are handled properly
    retrieved = postgres_db_real.get_knowledge_content(minimal_knowledge.id)  # type: ignore
    assert retrieved is not None
    assert retrieved.name == "Minimal Knowledge"
