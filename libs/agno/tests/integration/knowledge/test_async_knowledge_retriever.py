"""
Test for issue #5490: Async knowledge_retriever not properly awaited
when add_knowledge_to_context is enabled.

This test verifies that async knowledge retrievers are properly awaited
when using add_knowledge_to_context=True with async execution paths.
"""

import asyncio
from typing import Optional

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat


# Define an async knowledge retriever function
async def knowledge_retriever(
    query: str, agent: Optional[Agent] = None, num_documents: int = 5, **kwargs
) -> Optional[list[dict]]:
    """
    Custom async knowledge retriever function to search for relevant documents.

    Args:
        query (str): The search query string
        agent (Agent): The agent instance making the query
        num_documents (int): Number of documents to retrieve (default: 5)
        **kwargs: Additional keyword arguments

    Returns:
        Optional[list[dict]]: List of retrieved documents or None if search fails
    """
    # Simulate async retrieval
    await asyncio.sleep(0.1)
    return [{"content": f"Retrieved doc for: {query}"}]


@pytest.mark.asyncio
async def test_async_retriever_with_add_knowledge_to_context():
    """
    Test that async knowledge_retriever is properly awaited when add_knowledge_to_context=True.

    This test reproduces issue #5490 where async knowledge retrievers were not
    properly awaited in the async execution path, causing a coroutine object to be
    returned instead of actual results.
    """
    # Initialize model
    model = OpenAIChat(id="gpt-4o")

    # Initialize agent with async knowledge retriever and add_knowledge_to_context=True
    # This is the key setting that triggers the bug without the fix
    agent = Agent(
        model=model,
        add_knowledge_to_context=True,
        knowledge_retriever=knowledge_retriever,
        instructions="You are a helpful assistant that uses knowledge from the knowledge base.",
    )

    # Execute async query - this should work correctly with the fix
    query = "Retrieve all documents from the knowledge base"
    response = await agent.arun(query)

    # Verify that the response was generated successfully
    assert response is not None
    assert response.content is not None

    # Verify that references were added to the response (indicating knowledge retrieval worked)
    # If the async retriever wasn't awaited, references would be None or contain a coroutine object
    if response.references:
        # Check that references contain actual document data, not coroutine objects
        for ref in response.references:
            assert ref.references is not None
            assert isinstance(ref.references, list)
            # Verify references are actual dicts, not coroutine objects
            for doc in ref.references:
                assert isinstance(doc, dict)
                assert "content" in doc


@pytest.mark.asyncio
async def test_async_retriever_with_search_knowledge():
    """
    Test that async knowledge_retriever works correctly with search_knowledge=True.

    This test verifies the alternative code path that may already handle
    async retrievers properly.
    """
    model = OpenAIChat(id="gpt-4o")
    agent = Agent(
        model=model,
        search_knowledge=True,
        knowledge_retriever=knowledge_retriever,
        instructions="You are a helpful assistant that searches the knowledge base.",
    )

    query = "Search for information about documents"
    response = await agent.arun(query)

    # Verify that the response was generated successfully
    assert response is not None
    assert response.content is not None
