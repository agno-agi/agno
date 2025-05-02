"""Test for reasoning_content generation with KnowledgeTools.

This test verifies that reasoning_content is properly populated in the RunResponse
when using KnowledgeTools, in both streaming and non-streaming modes.
"""

from textwrap import dedent

import pytest

from agno.agent import Agent
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.url import UrlKnowledge
from agno.models.openai import OpenAIChat
from agno.tools.knowledge import KnowledgeTools
from agno.vectordb.lancedb import LanceDb, SearchType


@pytest.fixture(autouse=True)
def _show_output(capfd):
    """Force pytest to show print output for all tests in this module."""
    yield
    # Print captured output after test completes
    captured = capfd.readouterr()
    if captured.out:
        print(captured.out)
    if captured.err:
        print(captured.err)


@pytest.fixture
def knowledge_base():
    """Create a URL knowledge base for testing."""
    # Create a knowledge base containing information from a URL
    url_kb = UrlKnowledge(
        urls=["https://www.paulgraham.com/read.html"],
        # Use LanceDB as the vector database
        vector_db=LanceDb(
            uri="tmp/lancedb",
            table_name="test_knowledge_tools",
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )

    # Only load if it doesn't exist yet (saves time in repeat tests)
    try:
        url_kb.load(recreate=False)
    except Exception:
        url_kb.load(recreate=True)

    return url_kb


@pytest.mark.integration
def test_knowledge_tools_non_streaming(knowledge_base):
    """Test that reasoning_content is populated when using KnowledgeTools in non-streaming mode."""
    # Create an agent with KnowledgeTools
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[KnowledgeTools(knowledge=knowledge_base, think=True, search=True, analyze=True, add_instructions=True)],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            Make sure to use the knowledge tools to search for information.
            \
        """),
    )

    # Run the agent in non-streaming mode
    response = agent.run("What does Paul Graham explain about reading in his essay?", stream=False)

    # Print the reasoning_content when received
    if hasattr(response, "reasoning_content") and response.reasoning_content:
        print("\n=== KnowledgeTools (non-streaming) reasoning_content ===")
        print(response.reasoning_content)
        print("=========================================================\n")

    # Assert that reasoning_content exists and is populated
    assert hasattr(response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(response.reasoning_content) > 0, "reasoning_content should not be empty"


@pytest.mark.integration
def test_knowledge_tools_streaming(knowledge_base):
    """Test that reasoning_content is populated when using KnowledgeTools in streaming mode."""
    # Create an agent with KnowledgeTools
    agent = Agent(
        model=OpenAIChat(id="gpt-4o"),
        tools=[KnowledgeTools(knowledge=knowledge_base, think=True, search=True, analyze=True, add_instructions=True)],
        instructions=dedent("""\
            You are an expert problem-solving assistant with strong analytical skills! 🧠
            Use step-by-step reasoning to solve the problem.
            Make sure to use the knowledge tools to search for information.
            \
        """),
    )

    # Consume all streaming responses
    _ = list(
        agent.run("What are Paul Graham's suggestions on what to read?", stream=True, stream_intermediate_steps=True)
    )

    # Print the reasoning_content when received
    if (
        hasattr(agent, "run_response")
        and agent.run_response
        and hasattr(agent.run_response, "reasoning_content")
        and agent.run_response.reasoning_content
    ):
        print("\n=== KnowledgeTools (streaming) reasoning_content ===")
        print(agent.run_response.reasoning_content)
        print("====================================================\n")

    # Check the agent's run_response directly after streaming is complete
    assert hasattr(agent, "run_response"), "Agent should have run_response after streaming"
    assert agent.run_response is not None, "Agent's run_response should not be None"
    assert hasattr(agent.run_response, "reasoning_content"), "Response should have reasoning_content attribute"
    assert agent.run_response.reasoning_content is not None, "reasoning_content should not be None"
    assert len(agent.run_response.reasoning_content) > 0, "reasoning_content should not be empty"
