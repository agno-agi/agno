import pytest

from agno.agent import Agent


# Create a mock knowledge object
class MockKnowledge:
    def __init__(self):
        self.max_results = 5
        self.vector_db = None

    def validate_filters(self, filters):
        return filters or {}, []

    async def avalidate_filters(self, filters):
        return filters or {}, []

    async def asearch(self, query, max_results, filters):
        # Verify that max_results is correctly set to default value
        assert max_results == 5
        return []


@pytest.mark.asyncio
async def test_agent_aget_relevant_docs_from_knowledge_with_none_num_documents():
    """Test that aget_relevant_docs_from_knowledge handles num_documents=None correctly with retriever."""

    # Create a mock retriever function
    def mock_retriever(agent, query, num_documents, **kwargs):
        # Verify that num_documents is correctly set to knowledge.num_documents
        assert num_documents == 5
        return [{"content": "test document"}]

    # Create Agent instance
    agent = Agent()
    agent.knowledge = MockKnowledge()  # type: ignore
    agent.knowledge_retriever = mock_retriever  # type: ignore

    # Call the function with num_documents=None
    result = await agent.aget_relevant_docs_from_knowledge(query="test query", num_documents=None)

    # Verify the result
    assert result == [{"content": "test document"}]


@pytest.mark.asyncio
async def test_agent_aget_relevant_docs_from_knowledge_with_specific_num_documents():
    """Test that aget_relevant_docs_from_knowledge handles specific num_documents correctly with retriever."""

    # Create a mock retriever function
    def mock_retriever(agent, query, num_documents, **kwargs):
        # Verify that num_documents is correctly set to knowledge.num_documents
        assert num_documents == 10
        return [{"content": "test document"}]

    # Create Agent instance
    agent = Agent()
    agent.knowledge = MockKnowledge()  # type: ignore
    agent.knowledge_retriever = mock_retriever  # type: ignore

    # Call the function with specific num_documents
    result = await agent.aget_relevant_docs_from_knowledge(query="test query", num_documents=10)

    # Verify the result
    assert result == [{"content": "test document"}]


@pytest.mark.asyncio
async def test_agent_aget_relevant_docs_from_knowledge_without_retriever():
    """Test that aget_relevant_docs_from_knowledge works correctly without retriever."""

    # Create Agent instance
    agent = Agent()
    agent.knowledge = MockKnowledge()  # type: ignore
    agent.knowledge_retriever = None  # type: ignore

    # Call the function with num_documents=None
    result = await agent.aget_relevant_docs_from_knowledge(query="test query", num_documents=None)

    # Verify the result
    assert result is None  # Because asearch returns empty list


def test_agent_get_relevant_docs_from_knowledge_with_none_num_documents():
    """Test that get_relevant_docs_from_knowledge handles num_documents=None correctly with retriever."""

    # Create a mock retriever function
    def mock_retriever(agent, query, num_documents, **kwargs):
        # Verify that num_documents is correctly set to knowledge.num_documents
        assert num_documents == 5
        return [{"content": "test document"}]

    # Create Agent instance
    agent = Agent()
    agent.knowledge = MockKnowledge()  # type: ignore
    agent.knowledge_retriever = mock_retriever  # type: ignore

    # Call the function with num_documents=None
    result = agent.get_relevant_docs_from_knowledge(query="test query", num_documents=None)

    # Verify the result
    assert result == [{"content": "test document"}]
