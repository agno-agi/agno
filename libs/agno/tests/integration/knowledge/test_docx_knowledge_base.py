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


def test_docx_knowledge_base_single_file(setup_vector_db):
    """Test loading a single DOCX file into the knowledge base."""
    docx_file = get_test_data_dir() / "sample.docx"

    kb = DocxKnowledgeBase(path=docx_file, vector_db=setup_vector_db)
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


@pytest.mark.asyncio
async def test_docx_knowledge_base_async_single_file(setup_vector_db):
    """Test asynchronously loading a single DOCX file into the knowledge base."""
    docx_file = get_test_data_dir() / "sample.docx"

    kb = DocxKnowledgeBase(path=docx_file, vector_db=setup_vector_db)
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

    assert (
        "entry" in response.content.lower()
        or "junior" in response.content.lower()
        or "Jordan" in response.content.lower()
    )
    assert "senior developer" not in response.content.lower()


@pytest.mark.asyncio
async def test_async_text_knowledge_base_with_metadata_path(setup_vector_db):
    """Test async loading of text files with metadata using the new path structure."""
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

    await kb.aload(recreate=True)

    agent = Agent(knowledge=kb)
    response = await agent.arun(
        "Tell me about Jordan Mitchell's experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    assert (
        "entry" in response.content.lower()
        or "junior" in response.content.lower()
        or "Jordan" in response.content.lower()
    )
    assert "senior developer" not in response.content.lower()


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

    clarification_phrases = [
        "specify which",
        "which candidate",
        "please clarify",
        "need more information",
        "be more specific",
        "provide the name",
    ]

    candidates_mentioned = any(name in response_content for name in ["jordan", "mitchell", "taylor", "brooks"])
    valid_response = any(phrase in response_content for phrase in clarification_phrases) or candidates_mentioned

    print(f"Response content: {response_content}")
    print(f"Contains clarification phrase: {any(phrase in response_content for phrase in clarification_phrases)}")
    print(f"Candidates mentioned: {candidates_mentioned}")

    assert valid_response

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


@pytest.mark.asyncio
async def test_async_docx_knowledge_base_with_metadata_path_invalid_filter(setup_vector_db):
    """Test async filtering docx knowledge base with invalid filters using the new path structure."""
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

    await kb.aload(recreate=True)

    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = await agent.arun("Tell me about the candidate's experience?", markdown=True)
    response_content = response.content.lower()

    assert len(response_content) > 50

    clarification_phrases = [
        "specify which",
        "which candidate",
        "please clarify",
        "need more information",
        "be more specific",
    ]
    candidates_mentioned = any(name in response_content for name in ["jordan", "mitchell", "taylor", "brooks"])
    valid_response = any(phrase in response_content for phrase in clarification_phrases) or candidates_mentioned

    print(f"Response content: {response_content}")
    print(f"Contains clarification phrase: {any(phrase in response_content for phrase in clarification_phrases)}")
    print(f"Candidates mentioned: {candidates_mentioned}")

    assert valid_response

    # Check the tool calls to verify the invalid filter was not used
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call
        for call in tool_calls
        if call.get("type") == "function" and call["function"]["name"] == "asearch_knowledge_base"
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


def test_knowledge_base_with_invalid_filter(setup_vector_db):
    """Test filtering knowledge base with invalid filters."""
    kb = prepare_knowledge_base(setup_vector_db)

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = agent.run("Tell me about the candidate's experience?", markdown=True)

    response_content = response.content.lower()

    assert len(response_content) > 50

    clarification_phrases = [
        "specify",
        "which candidate",
        "please clarify",
        "need more information",
        "be more specific",
    ]

    candidates_mentioned = any(name in response_content for name in ["jordan", "mitchell", "taylor", "brooks"])

    valid_response = any(phrase in response_content for phrase in clarification_phrases) or candidates_mentioned

    # Print response content for debugging
    print(f"Response content: {response_content}")
    print(f"Contains clarification phrase: {any(phrase in response_content for phrase in clarification_phrases)}")
    print(f"Candidates mentioned: {candidates_mentioned}")

    assert valid_response

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

    # Check if any of the search_knowledge_base calls had the invalid filter
    found_invalid_filters = False
    for call in function_calls:
        call_args = call["function"].get("arguments", "{}")
        if "nonexistent_filter" in call_args:
            found_invalid_filters = True

    # Assert that the invalid filter was not used in the actual calls
    assert not found_invalid_filters


def test_knowledge_base_filter_override(setup_vector_db):
    """Test that run-level filters override agent-level filters."""
    kb = prepare_knowledge_base(setup_vector_db)

    # Initialize agent with jordan_mitchell filter
    agent = Agent(knowledge=kb, knowledge_filters={"user_id": "taylor_brooks"})

    # Run a query with taylor_brooks filter - should override the agent filter
    response = agent.run(
        "Tell me about Jordan Mitchell's experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Should  mention Jordan Mitchell's experience
    assert any(term in response_content for term in ["jordan mitchell", "entry-level", "intern", "junior"])

    # Taylor Brooks' CV should not be used instead of Jordan Mitchell's
    assert not any(term in response_content for term in ["taylor", "brooks", "senior", "developer", "mid level"])


@pytest.mark.asyncio
async def test_async_knowledge_base_with_valid_filter(setup_vector_db):
    """Test asynchronously filtering knowledge base with valid filters."""
    kb = await aprepare_knowledge_base(setup_vector_db)

    # Initialize agent with filters for Jordan Mitchell
    agent = Agent(knowledge=kb, knowledge_filters={"user_id": "jordan_mitchell"})

    # Run a query that should only return results from Jordan Mitchell's CV
    response = await agent.arun("Tell me about the Jordan Mitchell's experience?", markdown=True)

    # Check response content to verify filtering worked
    response_content = response.content

    # Jordan Mitchell's CV should mention entry-level positions
    assert (
        "entry-level" in response_content.lower()
        or "junior" in response_content.lower()
        or "jordan mitchell" in response_content.lower()
    )

    # Should not mention Taylor Brooks' experience as "senior developer"
    assert "senior developer" not in response_content.lower()


@pytest.mark.asyncio
async def test_async_knowledge_base_with_run_level_filter(setup_vector_db):
    """Test asynchronously filtering knowledge base with filters passed at run time."""
    kb = await aprepare_knowledge_base(setup_vector_db)

    # Initialize agent without filters
    agent = Agent(knowledge=kb)

    # Run a query with filters provided at run time
    response = await agent.arun(
        "Tell me about Jordan Mitchell experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Should mention Jordan Mitchell's experience
    assert any(term in response_content for term in ["jordan mitchell", "entry-level", "junior"])

    # Should not mention Taylor Brooks' experience
    assert not any(term in response_content for term in ["taylor brooks", "senior developer", "mid level"])


@pytest.mark.asyncio
async def test_async_knowledge_base_with_invalid_filter(setup_vector_db):
    """Test asynchronously filtering knowledge base with invalid filters."""
    kb = await aprepare_knowledge_base(setup_vector_db)

    # Initialize agent with invalid filters
    agent = Agent(knowledge=kb, knowledge_filters={"nonexistent_filter": "value"})

    response = await agent.arun("Tell me about the candidate's experience?", markdown=True)

    response_content = response.content.lower()

    assert len(response_content) > 50

    clarification_phrases = [
        "specify which",
        "which candidate",
        "please clarify",
        "need more information",
        "be more specific",
    ]

    candidates_mentioned = any(name in response_content for name in ["jordan", "mitchell", "taylor", "brooks"])

    valid_response = any(phrase in response_content for phrase in clarification_phrases) or candidates_mentioned
    assert valid_response

    # Check the tool calls to verify the invalid filter was not used
    tool_calls = []
    for msg in response.messages:
        if msg.tool_calls:
            tool_calls.extend(msg.tool_calls)

    function_calls = [
        call
        for call in tool_calls
        if call.get("type") == "function" and call["function"]["name"] == "asearch_knowledge_base"
    ]

    # Check if any of the search_knowledge_base calls had the invalid filter
    found_invalid_filters = False
    for call in function_calls:
        call_args = call["function"].get("arguments", "{}")
        if "nonexistent_filter" in call_args:
            found_invalid_filters = True

    # Assert that the invalid filter was not used in the actual calls
    assert not found_invalid_filters


@pytest.mark.asyncio
async def test_async_knowledge_base_filter_override(setup_vector_db):
    """Test that run-level filters override agent-level filters in async mode."""
    kb = await aprepare_knowledge_base(setup_vector_db)

    # Initialize agent with taylor_brooks filter
    agent = Agent(knowledge=kb, knowledge_filters={"user_id": "taylor_brooks"})

    # Run a query with jordan_mitchell filter - should override the agent filter
    response = await agent.arun(
        "Tell me about Jordan Mitchell's experience?", knowledge_filters={"user_id": "jordan_mitchell"}, markdown=True
    )

    # Check response content to verify filtering worked
    response_content = response.content.lower()

    # Check that we have a response with actual content
    assert len(response_content) > 50

    # Should mention Jordan Mitchell's experience
    assert any(term in response_content for term in ["jordan mitchell", "entry-level", "intern", "junior"])

    # Taylor Brooks' CV should not be used instead of Jordan Mitchell's
    assert not any(term in response_content for term in ["taylor", "brooks", "senior", "developer", "mid level"])
