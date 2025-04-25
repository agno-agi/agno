"""Test semantic search functionality in memory databases."""

from datetime import datetime  # Import datetime
from unittest.mock import Mock

import pytest

from agno.embedder.base import Embedder
from agno.memory.v2.db.postgres import PostgresMemoryDb
from agno.memory.v2.db.schema import MemoryRow
from agno.memory.v2.db.sqlite import SqliteMemoryDb
from agno.memory.v2.memory import Memory, UserMemory


class MockEmbedder(Embedder):
    """Mock embedder for testing purposes."""

    # Predefined embeddings for specific keywords
    _keyword_embeddings = {
        "python": [0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
        "programming": [0.8, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
        "pizza": [0.1, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
        "food": [0.1, 0.8, 0.2, 0.1, 0.1, 0.1, 0.1, 0.1],
        "hiking": [0.1, 0.1, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1],
        "outdoors": [0.1, 0.1, 0.8, 0.2, 0.1, 0.1, 0.1, 0.1],
        "outdoor": [0.1, 0.1, 0.8, 0.2, 0.1, 0.1, 0.1, 0.1],  # Added outdoor keyword
        "weather": [0.1, 0.1, 0.1, 0.9, 0.1, 0.1, 0.1, 0.1],
        # Default/fallback embedding
        "default": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
    }

    def get_embedding(self, text: str) -> list[float]:
        """Return a mock embedding based on keywords in the text."""
        text_lower = text.lower()
        for keyword, embedding in self._keyword_embeddings.items():
            if keyword != "default" and keyword in text_lower:
                # Return a copy to avoid modification issues
                return embedding[:]
        # Return default if no keyword matches
        return self._keyword_embeddings["default"][:]

    def batch_get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Return mock embeddings for a batch of texts."""
        return [self.get_embedding(text) for text in texts]


@pytest.fixture
def mock_embedder():
    """Create a mock embedder instance."""
    return MockEmbedder()


@pytest.fixture
def sqlite_memory_db(tmp_path):
    """Create a temporary SQLite memory database for testing."""
    db_path = tmp_path / "test_memory.db"
    # Pass table_name explicitly if needed, assuming default 'memory' is okay
    db = SqliteMemoryDb(db_file=str(db_path))
    db.create()
    return db


@pytest.fixture
def memory_with_sqlite_db(sqlite_memory_db, mock_embedder):
    """Create a Memory instance with SQLite database and mock embedder."""
    return Memory(db=sqlite_memory_db, embedder=mock_embedder)


@pytest.fixture
def sample_memories():
    """Create sample memories with distinct semantic content."""
    now = datetime.now()
    return [
        UserMemory(
            memory="I love programming in Python",
            topics=["programming", "python"],
            last_updated=now,
        ),
        UserMemory(
            memory="My favorite food is pizza",
            topics=["food", "preferences"],
            last_updated=now,
        ),
        UserMemory(
            memory="I enjoy hiking in the mountains",
            topics=["outdoors", "hiking"],
            last_updated=now,
        ),
        UserMemory(
            memory="Python is my preferred coding language",
            topics=["programming", "python"],
            last_updated=now,
        ),
        UserMemory(
            memory="The weather is nice today", topics=["weather"], last_updated=now
        ),
    ]


def test_sqlite_semantic_search(memory_with_sqlite_db, sample_memories, mock_embedder):
    """Test semantic search functionality with SQLite backend."""
    memory = memory_with_sqlite_db
    user_id = "test_user"

    # Add sample memories with embeddings
    for mem in sample_memories:
        memory.add_user_memory(
            memory=mem, user_id=user_id
        )  # Pass UserMemory object directly

    # Search for memories semantically similar to a Python-related query
    query = "What programming languages do I like?"
    results = memory.search_user_memories(
        query, user_id=user_id, retrieval_method="semantic"
    )

    # Check that we got results
    assert len(results) > 0, "Expected search results, but got none."

    # Verify that Python-related memories are ranked higher
    python_related = [m for m in results if "python" in m.memory.lower()]
    non_python_related = [m for m in results if "python" not in m.memory.lower()]

    if python_related and non_python_related:
        # Find the lowest rank (highest index) of a Python-related memory
        max_python_idx = max([results.index(m) for m in python_related])
        # Find the highest rank (lowest index) of a non-Python-related memory
        min_non_python_idx = min([results.index(m) for m in non_python_related])

        # Python memories should be ranked higher (lower index)
        assert (
            max_python_idx < min_non_python_idx
        ), f"Python memories should be ranked higher. Max Python index: {max_python_idx}, Min Non-Python index: {min_non_python_idx}. Results: {[r.memory for r in results]}"


def test_postgres_semantic_search_mock():
    """Test PostgreSQL semantic search functionality using mocks."""
    # Create mock PostgreSQL DB
    mock_db = Mock(spec=PostgresMemoryDb)
    mock_embedder = MockEmbedder()

    # Create mock results (ensure they have the 'embedding' field)
    mock_row1 = MemoryRow(
        id="1",
        user_id="test_user",
        memory={  # Use a dictionary directly
            "memory": "I love programming in Python",
            "topics": ["programming", "python"],
            "last_updated": datetime.now().isoformat(),  # Use ISO format string
            "memory_id": "1",  # Ensure memory_id is in the dict
        },
        embedding=[0.9, 0.1, 0.2, 0.3],  # Add embedding
        last_updated=datetime.now(),  # Add last_updated
    )

    mock_row2 = MemoryRow(
        id="2",
        user_id="test_user",
        memory={  # Use a dictionary directly
            "memory": "My favorite food is pizza",
            "topics": ["food", "preferences"],
            "last_updated": datetime.now().isoformat(),  # Use ISO format string
            "memory_id": "2",  # Ensure memory_id is in the dict
        },
        embedding=[0.1, 0.9, 0.2, 0.3],  # Add embedding
        last_updated=datetime.now(),  # Add last_updated
    )

    # Configure the mock to return our predefined results
    mock_db.search_memories_semantic.return_value = [mock_row1, mock_row2]

    # Create Memory instance with our mocks
    memory = Memory(db=mock_db, embedder=mock_embedder)

    # Test search
    query = "Tell me about programming"
    results = memory.search_user_memories(
        query, user_id="test_user", retrieval_method="semantic"
    )

    # Verify the mock was called correctly
    mock_db.search_memories_semantic.assert_called_once()
    args, kwargs = mock_db.search_memories_semantic.call_args

    # Check that the embedding was passed via keyword arguments
    assert "query_embedding" in kwargs, "query_embedding should be a keyword argument"
    assert (
        len(kwargs["query_embedding"]) > 0
    ), "Embedding should be passed to search_memories_semantic"
    assert "user_id" in kwargs, "user_id should be a keyword argument"
    assert "limit" in kwargs, "limit should be a keyword argument"

    # Verify we got the expected results
    assert len(results) == 2
    assert "Python" in results[0].memory
    assert "pizza" in results[1].memory


@pytest.mark.parametrize(
    "query, expected_topical_match",
    [
        ("Tell me about programming languages", "Python"),
        ("What foods do I like?", "pizza"),
        ("What outdoor activities do I enjoy?", "hiking"),
        ("How is the weather?", "weather"),
    ],
)
def test_semantic_search_topical_relevance(
    memory_with_sqlite_db, sample_memories, query, expected_topical_match
):
    """Test that semantic search returns topically relevant results."""
    memory = memory_with_sqlite_db
    user_id = "test_user"

    # Add sample memories with embeddings
    for mem in sample_memories:
        memory.add_user_memory(memory=mem, user_id=user_id)  # Pass UserMemory object

    # Search using the parameterized query
    results = memory.search_user_memories(
        query, user_id=user_id, retrieval_method="semantic"
    )

    # Check that we got results
    assert len(results) > 0, f"Expected results for query '{query}', but got none."

    # Check that the top result contains the expected topical match
    # (Semantic search might not always put the *exact* best match first,
    # but it should be highly ranked. Checking the top result is a reasonable heuristic.)
    assert (
        expected_topical_match.lower() in results[0].memory.lower()
    ), f"Expected top result for query '{query}' to contain '{expected_topical_match}', but got '{results[0].memory}'. All results: {[r.memory for r in results]}"


def test_no_embedder_fallback(sqlite_memory_db, sample_memories):
    """Test that searching without an embedder falls back to latest retrieval."""
    # Initialize Memory without embedder
    memory = Memory(db=sqlite_memory_db)
    user_id = "test_user"

    # Add sample memories (embeddings won't be generated/stored)
    for mem in sample_memories:
        memory.add_user_memory(memory=mem, user_id=user_id)

    # Semantic retrieval should fallback to latest ordering
    # Use a query that would trigger semantic search if embedder existed
    semantic_results = memory.search_user_memories(
        query="any query", user_id=user_id, retrieval_method="semantic", limit=5
    )
    latest_results = memory.search_user_memories(
        query="any query", user_id=user_id, retrieval_method="latest", limit=5
    )

    # Check that the fallback occurred (should return latest)
    assert len(semantic_results) > 0, "Fallback search should return results."
    assert (
        semantic_results == latest_results
    ), "Fallback semantic search should match latest results"

    # Verify the order is indeed latest (most recent first)
    assert all(
        semantic_results[i].last_updated >= semantic_results[i + 1].last_updated
        for i in range(len(semantic_results) - 1)
    ), "Fallback results should be sorted by time descending"


def test_empty_db_semantic_search(memory_with_sqlite_db):
    """Test semantic search on an empty database."""
    memory = memory_with_sqlite_db
    user_id = "test_user"

    query = "Search for something"
    results = memory.search_user_memories(
        query, user_id=user_id, retrieval_method="semantic"
    )

    assert results == [], "Semantic search on empty DB should return empty list"


# Add more tests as needed, e.g., for limit parameter, edge cases, etc.
