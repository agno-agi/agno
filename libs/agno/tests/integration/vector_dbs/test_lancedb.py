import asyncio
import logging

import pytest

from agno.document.base import Document
from agno.utils.log import logger
from agno.vectordb.lancedb.lance_db import LanceDb

# Set logging level to DEBUG
logger.setLevel(logging.DEBUG)


def test_lance_db_sync_operations():
    # Initialize LanceDB
    vector_db = LanceDb(
        table_name="test_sync_ops",
        uri="tmp/lancedb",
    )

    # Create table
    vector_db.create()
    assert vector_db.exists()

    test_docs = [
        Document(
            name="test1",
            content="This is a test document about machine learning",
            meta_data={"type": "test", "category": "ml"},
        ),
        Document(
            name="test2",
            content="This is another test document about artificial intelligence",
            meta_data={"type": "test", "category": "ai"},
        ),
    ]

    # Test insertion
    vector_db.insert(test_docs)
    assert vector_db.get_count() == 2

    # Test search with different methods
    vector_results = vector_db.search("machine learning document", limit=2)
    assert len(vector_results) > 0
    assert all(isinstance(doc, Document) for doc in vector_results)

    # Test document existence
    assert vector_db.doc_exists(test_docs[0])

    # Test name existence
    assert vector_db.name_exists("test1")
    assert not vector_db.name_exists("nonexistent")

    # Clean up
    vector_db.drop()
    assert not vector_db.exists()


def test_lance_db_sync_search_types():
    vector_db = LanceDb(
        table_name="test_search_types",
        uri="tmp/lancedb",
    )

    vector_db.create()

    test_docs = [
        Document(
            name="python", content="Python is a popular programming language", meta_data={"category": "programming"}
        ),
        Document(
            name="fastapi", content="FastAPI is a modern web framework for Python", meta_data={"category": "framework"}
        ),
    ]

    vector_db.insert(test_docs)

    # Test vector search
    vector_results = vector_db.vector_search("python programming", limit=2)
    assert len(vector_results) > 0

    # Test keyword search
    keyword_results = vector_db.keyword_search("web framework", limit=2)
    assert len(keyword_results) > 0

    # Test hybrid search
    hybrid_results = vector_db.hybrid_search("python framework", limit=2)
    assert len(hybrid_results) > 0

    vector_db.drop()


@pytest.mark.asyncio
async def test_lance_db_basic_async_operations():
    # Initialize LanceDB
    vector_db = LanceDb(
        table_name="test_basic_ops",
        uri="tmp/lancedb",
    )
    await vector_db.async_drop()

    # Create table
    await vector_db.async_create()
    assert await vector_db.async_exists()

    test_docs = [
        Document(
            name="test1",
            content="This is a test document about machine learning",
            meta_data={"type": "test", "category": "ml"},
        ),
        Document(
            name="test2",
            content="This is another test document about artificial intelligence",
            meta_data={"type": "test", "category": "ai"},
        ),
    ]

    # Test insertion
    await vector_db.async_insert(test_docs)
    assert await vector_db.async_get_count() == 2

    # Test search with different methods
    vector_results = await vector_db.async_search("machine learning document", limit=2)
    assert len(vector_results) > 0
    assert all(isinstance(doc, Document) for doc in vector_results)

    # Test document existence
    assert await vector_db.async_doc_exists(test_docs[0])

    # Test name existence
    assert vector_db.name_exists("test1")
    assert not vector_db.name_exists("nonexistent")

    # Clean up
    await vector_db.async_drop()
    assert not await vector_db.async_exists()


@pytest.mark.asyncio
async def test_lance_db_async_operations():
    vector_db = LanceDb(
        table_name="test_concurrent",
        uri="tmp/lancedb",
    )
    await vector_db.async_drop()

    await vector_db.async_create()

    # Create multiple document batches
    doc_batches = [
        [
            Document(
                name=f"doc{i}_{j}",
                content=f"This is test document {i}_{j} about concurrent operations",
                meta_data={"batch": i, "index": j},
            )
            for j in range(2)
        ]
        for i in range(3)
    ]

    # Insert document batches concurrently
    await asyncio.gather(*[vector_db.async_insert(batch) for batch in doc_batches])

    assert await vector_db.async_get_count() == 6  # 3 batches * 2 docs

    # Test concurrent searches
    search_queries = ["concurrent operations", "test document", "operations test"]

    search_results = await asyncio.gather(*[vector_db.async_search(query, limit=2) for query in search_queries])

    # Verify all searches returned results
    assert all(len(results) > 0 for results in search_results)

    # Clean up
    await vector_db.async_drop()
    assert not await vector_db.async_exists()
