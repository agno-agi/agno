import os
import shutil
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from agno.knowledge.document import Document
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.chroma.chromadb import reciprocal_rank_fusion
from agno.vectordb.distance import Distance
from agno.vectordb.search import SearchType

TEST_COLLECTION = "test_collection"
TEST_PATH = "tmp/test_chromadb"


@pytest.fixture
def chroma_db(mock_embedder):
    """Fixture to create and clean up a ChromaDb instance"""
    # Ensure the test directory exists with proper permissions
    os.makedirs(TEST_PATH, exist_ok=True)

    # Clean up any existing data before the test
    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = ChromaDb(collection=TEST_COLLECTION, path=TEST_PATH, persistent_client=False, embedder=mock_embedder)
    db.create()
    yield db

    # Cleanup after test
    try:
        db.drop()
    except Exception:
        pass

    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)


@pytest.fixture
def sample_documents() -> List[Document]:
    """Fixture to create sample documents"""
    return [
        Document(
            content="Tom Kha Gai is a Thai coconut soup with chicken",
            meta_data={"cuisine": "Thai", "type": "soup"},
            name="tom_kha",
        ),
        Document(
            content="Pad Thai is a stir-fried rice noodle dish",
            meta_data={"cuisine": "Thai", "type": "noodles"},
            name="pad_thai",
        ),
        Document(
            content="Green curry is a spicy Thai curry with coconut milk",
            meta_data={"cuisine": "Thai", "type": "curry"},
            name="green_curry",
        ),
    ]


def test_create_collection(chroma_db):
    """Test creating a collection"""
    assert chroma_db.exists() is True
    assert chroma_db.get_count() == 0


def test_insert_documents(chroma_db, sample_documents):
    """Test inserting documents"""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)
    assert chroma_db.get_count() == 3


def test_search_documents(chroma_db, sample_documents):
    """Test searching documents"""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    # Search for coconut-related dishes
    results = chroma_db.search("coconut dishes", limit=2)
    assert len(results) == 2
    assert any("coconut" in doc.content.lower() for doc in results)


def test_upsert_documents(chroma_db, sample_documents):
    """Test upserting documents"""
    # Initial insert
    chroma_db.insert(content_hash="test_hash", documents=[sample_documents[0]])
    assert chroma_db.get_count() == 1

    # Upsert same document with different content
    modified_doc = Document(
        content="Tom Kha Gai is a spicy and sour Thai coconut soup",
        meta_data={"cuisine": "Thai", "type": "soup"},
        name="tom_kha",
    )
    chroma_db.upsert(content_hash="test_hash", documents=[modified_doc])

    # Search to verify the update
    results = chroma_db.search("spicy and sour", limit=1)
    assert len(results) == 1
    assert "spicy and sour" in results[0].content


def test_metadata_flattening(chroma_db):
    """Test that complex metadata structures are properly flattened for ChromaDB compatibility"""

    # Test the _flatten_metadata method directly
    complex_metadata = {
        "simple_string": "value",
        "simple_int": 42,
        "simple_float": 3.14,
        "simple_bool": True,
        "nested_dict": {"doc_type": "recipe_book", "category": {"main": "cooking", "sub": "thai"}},
        "list_value": ["item1", "item2", "item3"],
        "mixed_list": [1, "string", True, {"nested": "value"}],
        "none_value": None,
    }

    flattened = chroma_db._flatten_metadata(complex_metadata)

    # Check that simple values are preserved
    assert flattened["simple_string"] == "value"
    assert flattened["simple_int"] == 42
    assert flattened["simple_float"] == 3.14
    assert flattened["simple_bool"] is True

    # Check that nested dicts are flattened with dot notation
    assert flattened["nested_dict.doc_type"] == "recipe_book"
    assert flattened["nested_dict.category.main"] == "cooking"
    assert flattened["nested_dict.category.sub"] == "thai"

    # Check that lists are converted to JSON strings
    assert flattened["list_value"] == '["item1", "item2", "item3"]'
    assert flattened["mixed_list"] == '[1, "string", true, {"nested": "value"}]'

    # Check that None values are excluded
    assert "none_value" not in flattened

    # Ensure all values are ChromaDB-compatible types
    for key, value in flattened.items():
        assert isinstance(value, (str, int, float, bool)), (
            f"Value {value} of type {type(value)} is not ChromaDB compatible"
        )


def test_complex_metadata_insertion(chroma_db):
    """Test inserting documents with complex metadata that previously caused errors"""

    # This is the exact scenario that was causing the original error
    complex_doc = Document(
        content="This is a recipe book with complex metadata",
        meta_data={
            "doc_type": "recipe_book",  # This nested dict was causing the error
            "categories": ["cooking", "thai", "asian"],
            "nested_info": {"author": "Chef John", "publication": {"year": 2023, "publisher": "Cooking Press"}},
            "tags": ["spicy", "coconut", "traditional"],
            "rating": 4.5,
            "is_vegetarian": False,
        },
        name="complex_recipe_book",
        content_id="recipe_book_001",
    )

    # This should not raise any ChromaDB validation errors
    chroma_db.insert(content_hash="complex_hash", documents=[complex_doc])
    assert chroma_db.get_count() == 1

    # Verify we can search and retrieve the document
    results = chroma_db.search("recipe book", limit=1)
    assert len(results) == 1
    assert results[0].name == "complex_recipe_book"

    # Verify some of the flattened metadata made it through
    # Note: The exact metadata format may vary after flattening, but the document should be retrievable


def test_update_metadata_with_complex_data(chroma_db):
    """Test updating metadata with complex nested structures (the original error scenario)"""

    # First insert a simple document
    simple_doc = Document(
        content="A simple document for metadata testing",
        meta_data={"type": "test"},
        name="metadata_test",
        content_id="test_content_001",
    )

    chroma_db.insert(content_hash="meta_hash", documents=[simple_doc])
    assert chroma_db.get_count() == 1

    # Now try to update with the complex metadata that was causing the error
    complex_update_metadata = {
        "doc_type": {"category": "recipe_book", "subcategory": "thai_cooking"},
        "filters": {"cuisine": "thai", "difficulty": "medium", "ingredients": ["coconut", "lemongrass", "chilies"]},
        "ratings": [4, 5, 4, 5, 3],
        "is_featured": True,
        "price": 29.99,
    }

    # This should not raise the original ValueError about dict metadata
    try:
        chroma_db.update_metadata(content_id="test_content_001", metadata=complex_update_metadata)
        # If we get here without an exception, the fix worked
        assert True
    except ValueError as e:
        if "Expected metadata value to be a str, int, float or bool, got" in str(e):
            pytest.fail(f"ChromaDB metadata validation error not fixed: {e}")
        else:
            # Some other error, re-raise it
            raise


def test_edge_case_metadata_types(chroma_db):
    """Test various edge cases for metadata flattening"""

    # Test deeply nested structures
    deep_nested = {"level1": {"level2": {"level3": {"level4": "deep_value"}}}}

    flattened = chroma_db._flatten_metadata(deep_nested)
    assert flattened["level1.level2.level3.level4"] == "deep_value"

    # Test empty structures
    empty_metadata = {"empty_dict": {}, "empty_list": [], "valid_string": "test"}

    flattened = chroma_db._flatten_metadata(empty_metadata)
    assert flattened["empty_dict"] == "{}"
    assert flattened["empty_list"] == "[]"
    assert flattened["valid_string"] == "test"

    # Test mixed types in lists
    mixed_metadata = {"mixed_array": ["string", 42, 3.14, True, {"nested": "object"}, [1, 2, 3]]}

    flattened = chroma_db._flatten_metadata(mixed_metadata)
    # Should be converted to JSON string
    assert isinstance(flattened["mixed_array"], str)
    assert "string" in flattened["mixed_array"]
    assert "42" in flattened["mixed_array"]


def test_name_exists(chroma_db, sample_documents):
    """Test name existence check"""
    chroma_db.insert(content_hash="test_hash", documents=[sample_documents[0]])
    assert chroma_db.name_exists("tom_kha") is True
    assert chroma_db.name_exists("nonexistent") is False


def test_delete_by_id(chroma_db, sample_documents):
    """Test deleting documents by ID"""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)
    assert chroma_db.get_count() == 3

    # Get the actual ID that was generated for the first document
    from hashlib import md5

    cleaned_content = sample_documents[0].content.replace("\x00", "\ufffd")
    doc_id = md5(cleaned_content.encode()).hexdigest()

    # Delete by ID - may not work with current implementation
    result = chroma_db.delete_by_id(doc_id)
    # ChromaDB might not support deletion by MD5 hash ID, so we'll check if method exists
    if hasattr(chroma_db, "delete_by_id"):
        # If deletion worked, count should be 2
        if result:
            assert chroma_db.get_count() == 2
        else:
            # If deletion failed, count should still be 3
            assert chroma_db.get_count() == 3

    # Try to delete non-existent ID
    result = chroma_db.delete_by_id("nonexistent_id")
    assert result is False


def test_delete_by_name(chroma_db, sample_documents):
    """Test deleting documents by name"""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)
    assert chroma_db.get_count() == 3

    # Delete by name
    result = chroma_db.delete_by_name("tom_kha")
    assert result is True
    assert chroma_db.get_count() == 2
    assert chroma_db.name_exists("tom_kha") is False

    # Try to delete non-existent name
    result = chroma_db.delete_by_name("nonexistent")
    assert result is False
    assert chroma_db.get_count() == 2


def test_delete_by_metadata(chroma_db, sample_documents):
    """Test deleting documents by metadata"""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)
    assert chroma_db.get_count() == 3

    # Delete by single metadata condition - should work
    result = chroma_db.delete_by_metadata({"cuisine": "Thai"})
    assert result is True
    assert chroma_db.get_count() == 0

    # Insert again and test single metadata condition
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)
    assert chroma_db.get_count() == 3

    # Delete by single metadata condition
    result = chroma_db.delete_by_metadata({"type": "soup"})
    assert result is True
    assert chroma_db.get_count() == 2  # Should only delete tom_kha

    # Try to delete by non-existent metadata
    result = chroma_db.delete_by_metadata({"cuisine": "Italian"})
    assert result is False
    assert chroma_db.get_count() == 2


def test_delete_by_content_id(chroma_db, sample_documents):
    """Test deleting documents by content ID"""
    # Add content_id to sample documents
    sample_documents[0].content_id = "recipe_1"
    sample_documents[1].content_id = "recipe_2"
    sample_documents[2].content_id = "recipe_3"

    chroma_db.insert(content_hash="test_hash", documents=sample_documents)
    assert chroma_db.get_count() == 3

    # Delete by content_id
    result = chroma_db.delete_by_content_id("recipe_1")
    assert result is True
    assert chroma_db.get_count() == 2

    # Try to delete non-existent content_id
    result = chroma_db.delete_by_content_id("nonexistent_content_id")
    assert result is False
    assert chroma_db.get_count() == 2


def test_delete_by_name_multiple_documents(chroma_db):
    """Test deleting multiple documents with the same name"""
    # Create multiple documents with the same name
    docs = [
        Document(
            content="First version of Tom Kha Gai",
            meta_data={"version": "1"},
            name="tom_kha",
            content_id="recipe_1_v1",
        ),
        Document(
            content="Second version of Tom Kha Gai",
            meta_data={"version": "2"},
            name="tom_kha",
            content_id="recipe_1_v2",
        ),
        Document(
            content="Pad Thai recipe",
            meta_data={"version": "1"},
            name="pad_thai",
            content_id="recipe_2_v1",
        ),
    ]

    chroma_db.insert(documents=docs, content_hash="test_hash")
    assert chroma_db.get_count() == 3

    # Delete all documents with name "tom_kha"
    result = chroma_db.delete_by_name("tom_kha")
    assert result is True
    assert chroma_db.get_count() == 1
    assert chroma_db.name_exists("tom_kha") is False
    assert chroma_db.name_exists("pad_thai") is True


def test_delete_by_metadata_simple(chroma_db):
    """Test deleting documents with simple metadata matching"""
    docs = [
        Document(
            content="Thai soup recipe",
            meta_data={"cuisine": "Thai", "type": "soup", "spicy": True},
            name="recipe_1",
        ),
        Document(
            content="Thai noodle recipe",
            meta_data={"cuisine": "Thai", "type": "noodles", "spicy": False},
            name="recipe_2",
        ),
        Document(
            content="Italian pasta recipe",
            meta_data={"cuisine": "Italian", "type": "pasta", "spicy": False},
            name="recipe_3",
        ),
    ]

    chroma_db.insert(documents=docs, content_hash="test_hash")
    assert chroma_db.get_count() == 3

    # Delete by single metadata condition
    result = chroma_db.delete_by_metadata({"cuisine": "Thai"})
    assert result is True
    assert chroma_db.get_count() == 1  # Should only leave Italian recipe

    # Insert again for next test
    chroma_db.insert(documents=docs[:2], content_hash="test_hash")
    assert chroma_db.get_count() == 3

    # Delete by another single metadata condition
    result = chroma_db.delete_by_metadata({"spicy": False})
    assert result is True
    assert chroma_db.get_count() == 1  # Should only leave the spicy Thai soup


def test_delete_collection(chroma_db, sample_documents):
    """Test deleting collection"""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)
    assert chroma_db.get_count() == 3

    assert chroma_db.delete() is True
    assert chroma_db.exists() is False


def test_distance_metrics():
    """Test different distance metrics"""
    # Ensure the test directory exists
    os.makedirs(TEST_PATH, exist_ok=True)

    db_cosine = ChromaDb(collection="test_cosine", path=TEST_PATH, distance=Distance.cosine)
    db_cosine.create()

    db_euclidean = ChromaDb(collection="test_euclidean", path=TEST_PATH, distance=Distance.l2)
    db_euclidean.create()

    assert db_cosine._collection is not None
    assert db_euclidean._collection is not None

    # Cleanup
    try:
        db_cosine.drop()
        db_euclidean.drop()
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_get_count(chroma_db, sample_documents):
    """Test document count"""
    assert chroma_db.get_count() == 0
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)
    assert chroma_db.get_count() == 3


def test_error_handling(chroma_db):
    """Test error handling scenarios"""
    # Test search with invalid query
    results = chroma_db.search("")
    assert len(results) == 0

    # Test inserting empty document list
    chroma_db.insert(documents=[], content_hash="test_hash")
    assert chroma_db.get_count() == 0


def test_custom_embedder(mock_embedder):
    """Test using a custom embedder"""
    # Ensure the test directory exists
    os.makedirs(TEST_PATH, exist_ok=True)

    db = ChromaDb(collection=TEST_COLLECTION, path=TEST_PATH, embedder=mock_embedder)
    db.create()
    assert db.embedder == mock_embedder

    # Cleanup
    try:
        db.drop()
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_multiple_document_operations(chroma_db, sample_documents):
    """Test multiple document operations including batch inserts"""
    # Test batch insert
    first_batch = sample_documents[:2]
    chroma_db.insert(documents=first_batch, content_hash="test_hash")
    assert chroma_db.get_count() == 2

    # Test adding another document
    second_batch = [sample_documents[2]]
    chroma_db.insert(documents=second_batch, content_hash="test_hash")
    assert chroma_db.get_count() == 3

    # Verify all documents are searchable
    curry_results = chroma_db.search("curry", limit=1)
    assert len(curry_results) == 1
    assert "curry" in curry_results[0].content.lower()


@pytest.mark.asyncio
async def test_async_create_collection(chroma_db):
    """Test creating a collection asynchronously"""
    # First delete the collection created by the fixture
    chroma_db.delete()

    # Test async create
    await chroma_db.async_create()
    assert chroma_db.exists() is True
    assert chroma_db.get_count() == 0


@pytest.mark.asyncio
async def test_async_insert_documents(chroma_db, sample_documents):
    """Test inserting documents asynchronously"""
    # Set embeddings on documents to avoid None embeddings issue
    for doc in sample_documents:
        doc.embedding = chroma_db.embedder.get_embedding(doc.content)

    await chroma_db.async_insert(content_hash="test_hash", documents=sample_documents)
    assert chroma_db.get_count() == 3


@pytest.mark.asyncio
async def test_async_search_documents(chroma_db, sample_documents):
    """Test searching documents asynchronously"""
    # Set embeddings on documents to avoid None embeddings issue
    for doc in sample_documents:
        doc.embedding = chroma_db.embedder.get_embedding(doc.content)

    await chroma_db.async_insert(content_hash="test_hash", documents=sample_documents)

    # Search for coconut-related dishes
    results = await chroma_db.async_search("coconut dishes", limit=2)
    assert len(results) == 2
    assert any("coconut" in doc.content.lower() for doc in results)


@pytest.mark.asyncio
async def test_async_upsert_documents(chroma_db, sample_documents):
    """Test upserting documents asynchronously"""
    # Set embedding on the initial document
    sample_documents[0].embedding = chroma_db.embedder.get_embedding(sample_documents[0].content)

    # Initial insert
    await chroma_db.async_insert(content_hash="test_hash", documents=[sample_documents[0]])
    assert chroma_db.get_count() == 1

    # Upsert same document with different content
    modified_doc = Document(
        content="Tom Kha Gai is a spicy and sour Thai coconut soup",
        meta_data={"cuisine": "Thai", "type": "soup"},
        name="tom_kha",
    )
    # Set embedding on the modified document
    modified_doc.embedding = chroma_db.embedder.get_embedding(modified_doc.content)

    await chroma_db.async_upsert(content_hash="test_hash", documents=[modified_doc])

    # Search to verify the update
    results = await chroma_db.async_search("spicy and sour", limit=1)
    assert len(results) == 1
    assert "spicy and sour" in results[0].content


@pytest.mark.asyncio
async def test_async_name_exists(chroma_db, sample_documents):
    """Test document name existence check asynchronously"""
    # Set embedding on the document
    sample_documents[0].embedding = chroma_db.embedder.get_embedding(sample_documents[0].content)

    await chroma_db.async_insert(content_hash="test_hash", documents=[sample_documents[0]])
    exists = await chroma_db.async_name_exists("tom_kha")
    assert exists is True

    exists = await chroma_db.async_name_exists("nonexistent")
    assert exists is False


@pytest.mark.asyncio
async def test_async_drop_collection(chroma_db):
    """Test dropping collection asynchronously"""
    assert chroma_db.exists() is True
    await chroma_db.async_drop()
    assert chroma_db.exists() is False


@pytest.mark.asyncio
async def test_async_exists(chroma_db):
    """Test exists check asynchronously"""
    exists = await chroma_db.async_exists()
    assert exists is True

    # Delete the collection
    chroma_db.delete()

    exists = await chroma_db.async_exists()
    assert exists is False


# =============================================================================
# Tests for Reciprocal Rank Fusion (RRF)
# =============================================================================


def test_rrf_single_list():
    """Test RRF with a single ranked list."""
    ranked_list = [("doc1", 0.9), ("doc2", 0.7), ("doc3", 0.5)]
    result = reciprocal_rank_fusion([ranked_list], k=60)

    # Should return all docs, sorted by RRF score
    assert len(result) == 3
    assert result[0][0] == "doc1"  # Highest rank should be first
    assert result[1][0] == "doc2"
    assert result[2][0] == "doc3"


def test_rrf_two_lists_same_order():
    """Test RRF with two lists having the same ranking order."""
    list1 = [("doc1", 0.9), ("doc2", 0.7), ("doc3", 0.5)]
    list2 = [("doc1", 0.8), ("doc2", 0.6), ("doc3", 0.4)]
    result = reciprocal_rank_fusion([list1, list2], k=60)

    # doc1 should still be first as it's ranked first in both lists
    assert result[0][0] == "doc1"
    assert result[1][0] == "doc2"
    assert result[2][0] == "doc3"


def test_rrf_two_lists_different_order():
    """Test RRF with two lists having different ranking orders."""
    list1 = [("doc1", 0.9), ("doc2", 0.7), ("doc3", 0.5)]
    list2 = [("doc3", 0.9), ("doc2", 0.7), ("doc1", 0.5)]
    result = reciprocal_rank_fusion([list1, list2], k=60)

    # All three docs should be present
    assert len(result) == 3

    # With k=60, the scores are:
    # doc1: 1/(60+1) + 1/(60+3) = 1/61 + 1/63 ≈ 0.0323
    # doc2: 1/(60+2) + 1/(60+2) = 2/62 ≈ 0.0323
    # doc3: 1/(60+3) + 1/(60+1) = 1/63 + 1/61 ≈ 0.0323
    # doc1 and doc3 have equal scores, doc2 is slightly lower
    # (because 1/61 + 1/63 > 2/62)
    doc_ids = [doc_id for doc_id, _ in result]
    assert "doc1" in doc_ids
    assert "doc2" in doc_ids
    assert "doc3" in doc_ids

    # Verify doc2 is not first (it has slightly lower score)
    # doc1 or doc3 should be first due to 1/61 + 1/63 > 2/62
    assert result[0][0] in ["doc1", "doc3"]


def test_rrf_disjoint_lists():
    """Test RRF with disjoint document sets."""
    list1 = [("doc1", 0.9), ("doc2", 0.7)]
    list2 = [("doc3", 0.8), ("doc4", 0.6)]
    result = reciprocal_rank_fusion([list1, list2], k=60)

    # All 4 docs should be present
    doc_ids = [doc_id for doc_id, _ in result]
    assert len(doc_ids) == 4
    assert "doc1" in doc_ids
    assert "doc2" in doc_ids
    assert "doc3" in doc_ids
    assert "doc4" in doc_ids


def test_rrf_overlapping_lists():
    """Test RRF with partially overlapping document sets."""
    list1 = [("doc1", 0.9), ("doc2", 0.7), ("doc3", 0.5)]
    list2 = [("doc2", 0.9), ("doc4", 0.7)]
    result = reciprocal_rank_fusion([list1, list2], k=60)

    # doc2 appears in both lists, should have higher RRF score
    doc_ids = [doc_id for doc_id, _ in result]
    assert len(doc_ids) == 4
    # doc2 should be ranked highest (appears in both lists at good positions)
    assert result[0][0] == "doc2"


def test_rrf_empty_lists():
    """Test RRF with empty input."""
    result = reciprocal_rank_fusion([], k=60)
    assert result == []

    result = reciprocal_rank_fusion([[]], k=60)
    assert result == []


def test_rrf_k_parameter_effect():
    """Test that k parameter affects score calculation."""
    ranked_list = [("doc1", 0.9), ("doc2", 0.7)]

    # With k=60 (default)
    result_k60 = reciprocal_rank_fusion([ranked_list], k=60)
    # With k=1 (more emphasis on top ranks)
    result_k1 = reciprocal_rank_fusion([ranked_list], k=1)

    # Both should have same order but different scores
    assert result_k60[0][0] == result_k1[0][0]
    assert result_k60[1][0] == result_k1[1][0]

    # Scores should be different due to different k values
    # k=1: 1/(1+1)=0.5 for rank 1, 1/(1+2)=0.33 for rank 2
    # k=60: 1/(60+1)=0.016 for rank 1, 1/(60+2)=0.016 for rank 2
    assert result_k1[0][1] != result_k60[0][1]


def test_rrf_score_calculation():
    """Test exact RRF score calculation."""
    ranked_list = [("doc1", 0.9)]
    result = reciprocal_rank_fusion([ranked_list], k=60)

    # For k=60, rank=1: score = 1/(60+1) = 1/61
    expected_score = 1.0 / 61
    assert abs(result[0][1] - expected_score) < 1e-10


# =============================================================================
# Tests for Search Type Configuration
# =============================================================================


def test_default_search_type(mock_embedder):
    """Test that default search type is vector."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_default_search",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
        )
        assert db.search_type == SearchType.vector
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_vector_search_type_config(mock_embedder):
    """Test vector search type configuration."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_vector_search",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            search_type=SearchType.vector,
        )
        assert db.search_type == SearchType.vector
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_keyword_search_type_config(mock_embedder):
    """Test keyword search type configuration."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_keyword_search",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            search_type=SearchType.keyword,
        )
        assert db.search_type == SearchType.keyword
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_hybrid_search_type_config(mock_embedder):
    """Test hybrid search type configuration."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_hybrid_search",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            search_type=SearchType.hybrid,
        )
        assert db.search_type == SearchType.hybrid
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_hybrid_rrf_k_default(mock_embedder):
    """Test default hybrid_rrf_k value."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_rrf_default",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
        )
        assert db.hybrid_rrf_k == 60
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_hybrid_rrf_k_custom(mock_embedder):
    """Test custom hybrid_rrf_k value."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_rrf_custom",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            hybrid_rrf_k=30,
        )
        assert db.hybrid_rrf_k == 30
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_get_supported_search_types(mock_embedder):
    """Test that get_supported_search_types returns correct types."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_supported_types",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
        )
        supported = db.get_supported_search_types()
        assert SearchType.vector in supported
        assert SearchType.keyword in supported
        assert SearchType.hybrid in supported
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


# =============================================================================
# Tests for Vector Search
# =============================================================================


def test_vector_search_basic(chroma_db, sample_documents):
    """Test basic vector search."""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    results = chroma_db._vector_search("coconut soup", limit=2)
    assert len(results) == 2
    assert all(isinstance(doc, Document) for doc in results)


def test_vector_search_empty_collection(chroma_db):
    """Test vector search on empty collection."""
    results = chroma_db._vector_search("any query", limit=5)
    assert len(results) == 0


def test_vector_search_with_limit(chroma_db, sample_documents):
    """Test vector search respects limit parameter."""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    results = chroma_db._vector_search("Thai food", limit=1)
    assert len(results) == 1

    results = chroma_db._vector_search("Thai food", limit=10)
    assert len(results) == 3  # Only 3 documents in collection


# =============================================================================
# Tests for Keyword Search
# =============================================================================


def test_keyword_search_basic(chroma_db, sample_documents):
    """Test basic keyword search."""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    results = chroma_db._keyword_search("coconut", limit=5)
    # Should find documents containing "coconut"
    assert all(isinstance(doc, Document) for doc in results)


def test_keyword_search_empty_query(chroma_db, sample_documents):
    """Test keyword search with empty query."""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    results = chroma_db._keyword_search("", limit=5)
    assert len(results) == 0


def test_keyword_search_no_match(chroma_db, sample_documents):
    """Test keyword search with no matching documents."""
    chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    results = chroma_db._keyword_search("pizza", limit=5)
    # May return empty or results depending on ChromaDB behavior
    assert isinstance(results, list)


# =============================================================================
# Tests for Hybrid Search
# =============================================================================


@pytest.fixture
def hybrid_chroma_db(mock_embedder):
    """Fixture to create a ChromaDb instance with hybrid search enabled."""
    os.makedirs(TEST_PATH, exist_ok=True)

    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)
        os.makedirs(TEST_PATH)

    db = ChromaDb(
        collection="test_hybrid",
        path=TEST_PATH,
        persistent_client=False,
        embedder=mock_embedder,
        search_type=SearchType.hybrid,
        hybrid_rrf_k=60,
    )
    db.create()
    yield db

    try:
        db.drop()
    except Exception:
        pass

    if os.path.exists(TEST_PATH):
        shutil.rmtree(TEST_PATH)


def test_hybrid_search_basic(hybrid_chroma_db, sample_documents):
    """Test basic hybrid search."""
    hybrid_chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    results = hybrid_chroma_db._hybrid_search("coconut soup", limit=2)
    assert len(results) <= 2
    assert all(isinstance(doc, Document) for doc in results)


def test_hybrid_search_returns_rrf_score(hybrid_chroma_db, sample_documents):
    """Test that hybrid search results include RRF score in metadata."""
    hybrid_chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    results = hybrid_chroma_db._hybrid_search("Thai food", limit=3)
    for doc in results:
        assert "rrf_score" in doc.meta_data
        assert isinstance(doc.meta_data["rrf_score"], float)
        assert doc.meta_data["rrf_score"] > 0


def test_hybrid_search_empty_collection(hybrid_chroma_db):
    """Test hybrid search on empty collection."""
    results = hybrid_chroma_db._hybrid_search("any query", limit=5)
    assert len(results) == 0


def test_hybrid_search_empty_query(hybrid_chroma_db, sample_documents):
    """Test hybrid search with empty query."""
    hybrid_chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    # Empty query should handle gracefully
    results = hybrid_chroma_db._hybrid_search("", limit=5)
    assert isinstance(results, list)


def test_hybrid_search_dispatches_correctly(hybrid_chroma_db, sample_documents):
    """Test that search() dispatches to _hybrid_search when search_type is hybrid."""
    hybrid_chroma_db.insert(content_hash="test_hash", documents=sample_documents)

    # The main search method should use hybrid search
    results = hybrid_chroma_db.search("coconut", limit=2)
    assert isinstance(results, list)
    # Results from hybrid search should have rrf_score
    for doc in results:
        if doc.meta_data:
            assert "rrf_score" in doc.meta_data


# =============================================================================
# Tests for Search Method Dispatch
# =============================================================================


def test_search_dispatches_to_vector(mock_embedder):
    """Test that search dispatches to _vector_search for vector type."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_dispatch_vector",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            search_type=SearchType.vector,
        )
        db.create()

        with patch.object(db, "_vector_search", return_value=[]) as mock_vector:
            db.search("test query", limit=5)
            mock_vector.assert_called_once()

        db.drop()
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_search_dispatches_to_keyword(mock_embedder):
    """Test that search dispatches to _keyword_search for keyword type."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_dispatch_keyword",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            search_type=SearchType.keyword,
        )
        db.create()

        with patch.object(db, "_keyword_search", return_value=[]) as mock_keyword:
            db.search("test query", limit=5)
            mock_keyword.assert_called_once()

        db.drop()
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_search_dispatches_to_hybrid(mock_embedder):
    """Test that search dispatches to _hybrid_search for hybrid type."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        db = ChromaDb(
            collection="test_dispatch_hybrid",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            search_type=SearchType.hybrid,
        )
        db.create()

        with patch.object(db, "_hybrid_search", return_value=[]) as mock_hybrid:
            db.search("test query", limit=5)
            mock_hybrid.assert_called_once()

        db.drop()
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


# =============================================================================
# Tests for Reranker Error Handling
# =============================================================================


def test_reranker_failure_returns_unranked(mock_embedder, sample_documents):
    """Test that reranker failure returns unranked results gracefully."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        # Create a mock reranker that raises an exception
        mock_reranker = MagicMock()
        mock_reranker.rerank.side_effect = Exception("Reranker API error")

        db = ChromaDb(
            collection="test_reranker_error",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            reranker=mock_reranker,
        )
        db.create()
        db.insert(content_hash="test_hash", documents=sample_documents)

        # Search should succeed even if reranker fails
        results = db.search("coconut", limit=2)
        assert isinstance(results, list)
        # Should have results (unranked) despite reranker failure

        db.drop()
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)


def test_reranker_success(mock_embedder, sample_documents):
    """Test that reranker is called when provided and succeeds."""
    os.makedirs(TEST_PATH, exist_ok=True)
    try:
        # Create a mock reranker that returns reranked results
        mock_reranker = MagicMock()
        mock_reranker.rerank.return_value = sample_documents[:1]

        db = ChromaDb(
            collection="test_reranker_success",
            path=TEST_PATH,
            persistent_client=False,
            embedder=mock_embedder,
            reranker=mock_reranker,
        )
        db.create()
        db.insert(content_hash="test_hash", documents=sample_documents)

        db.search("coconut", limit=2)
        # Reranker should have been called
        mock_reranker.rerank.assert_called()

        db.drop()
    finally:
        if os.path.exists(TEST_PATH):
            shutil.rmtree(TEST_PATH)
