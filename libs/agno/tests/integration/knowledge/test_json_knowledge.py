from pathlib import Path

import pytest

from agno.agent import Agent
from agno.db.json.json_db import JsonDb
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    vector_db = ChromaDb(collection="vectors", path="tmp/chromadb", persistent_client=True)
    yield vector_db
    # Clean up after test
    vector_db.drop()


def get_filtered_data_dir():
    """Get the path to the filtered test data directory."""
    return Path(__file__).parent / "data" / "filters"


def prepare_knowledge_base(setup_vector_db):
    """Prepare a knowledge base with filtered data."""
    # Create knowledge base
    kb = Knowledge(vector_db=setup_vector_db)

    # Load documents with different user IDs and metadata
    kb.insert(
        path=get_filtered_data_dir() / "cv_1.json",
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
    )

    kb.insert(
        path=get_filtered_data_dir() / "cv_2.json",
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    return kb


def test_json_knowledge_base():
    contents_db = JsonDb(db_path="tmp/json_db")
    vector_db = ChromaDb(collection="vectors_1", path="tmp/chromadb", persistent_client=True)

    knowledge_base = Knowledge(
        vector_db=vector_db,
        contents_db=contents_db,
    )

    knowledge_base.insert(
        path=str(Path(__file__).parent / "data/json"),
    )

    assert vector_db.exists()

    # We have 2 JSON files with 3 and 2 documents respectively
    expected_docs = 5
    assert vector_db.get_count() == expected_docs

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = agent.run("Tell me about Thai curry recipes", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] == "search_knowledge_base"

    # Clean up
    vector_db.drop()


def test_json_knowledge_base_single_file():
    vector_db = ChromaDb(collection="vectors", path="tmp/chromadb", persistent_client=True)

    # Create a knowledge base with a single JSON file
    knowledge_base = Knowledge(
        vector_db=vector_db,
    )
    knowledge_base.insert(
        path=str(Path(__file__).parent / "data/json/recipes.json"),
    )

    assert vector_db.exists()

    # The recipes.json file contains 3 documents
    expected_docs = 3
    assert vector_db.get_count() == expected_docs

    # Clean up
    vector_db.drop()


@pytest.mark.asyncio
async def test_json_knowledge_base_async():
    vector_db = ChromaDb(collection="vectors", path="tmp/chromadb", persistent_client=True)

    # Create knowledge base
    knowledge_base = Knowledge(
        vector_db=vector_db,
    )

    await knowledge_base.ainsert(
        path=str(Path(__file__).parent / "data/json"),
    )

    assert await vector_db.async_exists()

    # We have 2 JSON files with 3 and 2 documents respectively
    expected_docs = 5
    assert vector_db.get_count() == expected_docs

    # Create and use the agent
    agent = Agent(knowledge=knowledge_base)
    response = await agent.arun("What ingredients do I need for Tom Kha Gai?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)
    for call in tool_calls:
        if call.get("type", "") == "function":
            assert call["function"]["name"] == "search_knowledge_base"

    assert any(ingredient in response.content.lower() for ingredient in ["coconut", "chicken", "galangal"])

    # Clean up
    await vector_db.async_drop()


# for the one with new knowledge filter DX- filters at initialization
def test_text_knowledge_base_with_metadata_path(setup_vector_db):
    """Test loading text files with metadata using the new path structure."""
    kb = Knowledge(
        vector_db=setup_vector_db,
    )
    kb.insert(
        path=str(get_filtered_data_dir() / "cv_1.json"),
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
    )

    kb.insert(
        path=str(get_filtered_data_dir() / "cv_2.json"),
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    # Verify documents were loaded with metadata
    agent = Agent(knowledge=kb)
    response = agent.run(
        "Tell me about Jordan Mitchell's experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    assert (
        "entry" in response.content.lower()
        or "junior" in response.content.lower()
        or "jordan" in response.content.lower()
    )
    assert "senior developer" not in response.content.lower()


def test_knowledge_base_with_metadata_path_invalid_filter(setup_vector_db):
    """Test filtering docx knowledge base with invalid filters using the new path structure."""
    kb = Knowledge(
        vector_db=setup_vector_db,
    )
    kb.insert(
        path=str(get_filtered_data_dir() / "cv_1.json"),
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
    )
    kb.insert(
        path=str(get_filtered_data_dir() / "cv_2.json"),
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = agent.run("Tell me about the candidate's experience?", markdown=True)
    response_content = response.content.lower()

    assert len(response_content) > 50

    # Check the tool calls to verify the invalid filter was not used
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call
        for call in tool_calls
        if call.get("type") == "function" and call["function"]["name"] == "search_knowledge_base"
    ]

    found_invalid_filters = False
    for call in function_calls:
        call_args = call["function"].get("arguments", "{}")
        if "nonexistent_filter" in call_args:
            found_invalid_filters = True

    assert not found_invalid_filters


# for the one with new knowledge filter DX- filters at load
def test_knowledge_base_with_valid_filter(setup_vector_db):
    """Test filtering knowledge base with valid filters."""
    kb = prepare_knowledge_base(setup_vector_db)

    # Initialize agent with filters for Jordan Mitchell
    agent = Agent(knowledge=kb, knowledge_filters={"user_id": "jordan_mitchell"})

    # Run a query that should only return results from Jordan Mitchell's CV
    response = agent.run("Tell me about the Jordan Mitchell's experience?", markdown=True)

    # Check response content to verify filtering worked
    response_content = response.content

    # Jordan Mitchell's CV should mention "software engineering intern"
    assert (
        "entry-level" in response_content.lower()
        or "junior" in response_content.lower()
        or "jordan mitchell" in response_content.lower()
    )

    # Should not mention Taylor Brooks' experience as "senior developer"
    assert "senior developer" not in response_content.lower()


def test_knowledge_base_with_run_level_filter(setup_vector_db):
    """Test filtering knowledge base with filters passed at run time."""
    kb = prepare_knowledge_base(setup_vector_db)

    # Initialize agent without filters
    agent = Agent(knowledge=kb)

    # Run a query with filters provided at run time
    response = agent.run(
        "Tell me about Jordan Mitchell experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Should not mention Jordan Mitchell's experience
    assert any(term in response_content for term in ["jordan mitchell", "entry-level", "junior"])
