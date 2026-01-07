from pathlib import Path

import pytest

from agno.agent import Agent
from agno.knowledge.knowledge import Knowledge
from agno.vectordb.chroma import ChromaDb


@pytest.fixture
def setup_vector_db():
    """Setup a temporary vector DB for testing."""
    vector_db = ChromaDb(collection="vectors", path="tmp/chromadb", persistent_client=True)
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
    kb = Knowledge(vector_db=setup_vector_db)

    # Load documents with different user IDs and metadata
    kb.insert(
        path=get_filtered_data_dir() / "presentation_1.pptx",
        metadata={"user_id": "alice_smith", "document_type": "presentation", "topic": "introduction"},
    )

    kb.insert(
        path=get_filtered_data_dir() / "presentation_2.pptx",
        metadata={"user_id": "bob_jones", "document_type": "presentation", "topic": "advanced"},
    )

    return kb


async def aprepare_knowledge_base(setup_vector_db):
    """Prepare a knowledge base with filtered data asynchronously."""
    # Create knowledge base
    kb = Knowledge(vector_db=setup_vector_db)

    # Load contents with different user IDs and metadata
    await kb.ainsert(
        path=get_filtered_data_dir() / "presentation_1.pptx",
        metadata={"user_id": "alice_smith", "document_type": "presentation", "topic": "introduction"},
    )

    await kb.ainsert(
        path=get_filtered_data_dir() / "presentation_2.pptx",
        metadata={"user_id": "bob_jones", "document_type": "presentation", "topic": "advanced"},
    )

    return kb


def test_pptx_knowledge_base_directory(setup_vector_db):
    """Test loading a directory of PPTX files into the knowledge base."""
    pptx_dir = get_test_data_dir()

    kb = Knowledge(vector_db=setup_vector_db)
    kb.insert(
        path=pptx_dir,
    )

    assert setup_vector_db.exists()
    assert setup_vector_db.get_count() > 0

    # Enable search on the agent
    agent = Agent(knowledge=kb, search_knowledge=True)
    response = agent.run("What is the presentation about?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


@pytest.mark.asyncio
async def test_pptx_knowledge_base_async_directory(setup_vector_db):
    """Test asynchronously loading a directory of PPTX files into the knowledge base."""
    pptx_dir = get_test_data_dir()

    kb = Knowledge(vector_db=setup_vector_db)
    await kb.ainsert(
        path=pptx_dir,
    )

    assert await setup_vector_db.async_exists()
    assert setup_vector_db.get_count() > 0

    # Enable search on the agent
    agent = Agent(knowledge=kb, search_knowledge=True)
    response = await agent.arun("What is the presentation about?", markdown=True)

    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [call for call in tool_calls if call.get("type") == "function"]
    # For async operations, we use search_knowledge_base
    assert any(call["function"]["name"] == "search_knowledge_base" for call in function_calls)


# for the one with new knowledge filter DX- filters at initialization
def test_text_knowledge_base_with_metadata_path(setup_vector_db):
    """Test loading PPTX files with metadata using the new path structure."""
    kb = Knowledge(
        vector_db=setup_vector_db,
    )

    kb.insert(
        path=str(get_filtered_data_dir() / "presentation_1.pptx"),
        metadata={"user_id": "alice_smith", "document_type": "presentation", "topic": "introduction"},
    )
    kb.insert(
        path=str(get_filtered_data_dir() / "presentation_2.pptx"),
        metadata={"user_id": "bob_jones", "document_type": "presentation", "topic": "advanced"},
    )

    # Verify documents were loaded with metadata
    agent = Agent(knowledge=kb)
    response = agent.run(
        "Tell me about Alice Smith's presentation?", knowledge_filters={"user_id": "alice_smith"}, markdown=True
    )

    assert "alice" in response.content.lower()


def test_pptx_knowledge_base_with_metadata_path_invalid_filter(setup_vector_db):
    """Test filtering pptx knowledge base with invalid filters using the new path structure."""
    kb = Knowledge(
        vector_db=setup_vector_db,
    )

    kb.insert(
        path=str(get_filtered_data_dir() / "presentation_1.pptx"),
        metadata={"user_id": "alice_smith", "document_type": "presentation", "topic": "introduction"},
    )
    kb.insert(
        path=str(get_filtered_data_dir() / "presentation_2.pptx"),
        metadata={"user_id": "bob_jones", "document_type": "presentation", "topic": "advanced"},
    )

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = agent.run("Tell me about the presentation?", markdown=True)
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

    # Initialize agent with filters for Alice Smith
    agent = Agent(knowledge=kb, knowledge_filters={"user_id": "alice_smith"})

    # Run a query that should only return results from Alice Smith's presentation
    response = agent.run("Tell me about Alice Smith's presentation?", markdown=True)

    # Check response content to verify filtering worked
    response_content = response.content

    # Alice Smith's presentation should mention "introduction"
    assert "introduction" in response_content.lower() or "alice smith" in response_content.lower()

    # Should not mention Bob Jones' "advanced" topic
    assert "advanced" not in response_content.lower()


def test_knowledge_base_with_run_level_filter(setup_vector_db):
    """Test filtering knowledge base with filters passed at run time."""
    kb = prepare_knowledge_base(setup_vector_db)

    # Initialize agent without filters
    agent = Agent(knowledge=kb)

    # Run a query with filters provided at run time
    response = agent.run(
        "Tell me about Alice Smith's presentation?", knowledge_filters={"user_id": "alice_smith"}, markdown=True
    )

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Should mention Alice Smith's presentation
    assert any(term in response_content for term in ["alice smith", "introduction"])
