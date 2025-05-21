import os
from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.docx import DocxKnowledgeBase
from agno.vectordb.lancedb import LanceDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    table_name = f"docx_test_{os.urandom(4).hex()}"
    vector_db = LanceDb(table_name=table_name, uri="tmp/lancedb")
    yield vector_db
    # Clean up after test
    vector_db.drop()


def get_test_data_dir():
    """Get the path to the test data directory."""
    return Path(__file__).parent / "data"


def get_filtered_data_dir():
    """Get the path to the filtered test data directory."""
    return Path(__file__).parent / "data" / "filters"


def prepare_knowledge_base(setup_vector_db):
    """Prepare a knowledge base with filtered data."""
    # Create knowledge base
    kb = DocxKnowledgeBase(vector_db=setup_vector_db)

    # Load documents with different user IDs and metadata
    kb.load_document(
        path=get_filtered_data_dir() / "cv_1.docx",
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
        recreate=True,
    )

    kb.load_document(
        path=get_filtered_data_dir() / "cv_2.docx",
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    return kb


async def aprepare_knowledge_base(setup_vector_db):
    """Prepare a knowledge base with filtered data asynchronously."""
    # Create knowledge base
    kb = DocxKnowledgeBase(vector_db=setup_vector_db)

    # Load documents with different user IDs and metadata
    await kb.aload_document(
        path=get_filtered_data_dir() / "cv_1.docx",
        metadata={"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
        recreate=True,
    )

    await kb.aload_document(
        path=get_filtered_data_dir() / "cv_2.docx",
        metadata={"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
    )

    return kb


def test_docx_knowledge_base_directory(setup_vector_db):
    """Test loading a directory of DOCX files into the knowledge base."""
    docx_dir = get_test_data_dir()

    kb = DocxKnowledgeBase(path=docx_dir, vector_db=setup_vector_db)
    kb.load(recreate=True)

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    # Enable search on the agent
    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What is the story of little prince about?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_docx_knowledge_base_async_directory(setup_vector_db):
    """Test asynchronously loading a directory of DOCX files into the knowledge base."""
    docx_dir = get_test_data_dir()

    kb = DocxKnowledgeBase(path=docx_dir, vector_db=setup_vector_db)
    await kb.aload(recreate=True)

    assert await setup_vector_db.async_exists()
    assert await setup_vector_db.async_get_count() > 0

    # Enable search on the agent
    agent = Agent(knowledge=kb, search_knowledge=True)
    response = await agent.arun("What is the story of little prince about?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    # For async operations, we use asearch_knowledge_base
    assert any(call["function"]["name"] == "asearch_knowledge_base" for call in function_calls)


# for the one with new knowledge filter DX- filters at initialization
def test_text_knowledge_base_with_metadata_path(setup_vector_db):
    """Test loading text files with metadata using the new path structure."""
    kb = DocxKnowledgeBase(
        path=[
            {
                "path": str(get_filtered_data_dir() / "cv_1.docx"),
                "metadata": {"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
            },
            {
                "path": str(get_filtered_data_dir() / "cv_2.docx"),
                "metadata": {"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
            },
        ],
        vector_db=setup_vector_db,
    )

    kb.load(recreate=True)

    # Verify documents were loaded with metadata
    agent = Agent(knowledge=kb)
    response = agent.run(
        "Tell me about Jordan Mitchell's experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    assert "jordan" in response.content.lower()


def test_docx_knowledge_base_with_metadata_path_invalid_filter(setup_vector_db):
    """Test filtering docx knowledge base with invalid filters using the new path structure."""
    kb = DocxKnowledgeBase(
        path=[
            {
                "path": str(get_filtered_data_dir() / "cv_1.docx"),
                "metadata": {"user_id": "jordan_mitchell", "document_type": "cv", "experience_level": "entry"},
            },
            {
                "path": str(get_filtered_data_dir() / "cv_2.docx"),
                "metadata": {"user_id": "taylor_brooks", "document_type": "cv", "experience_level": "mid"},
            },
        ],
        vector_db=setup_vector_db,
    )

    kb.load(recreate=True)

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
