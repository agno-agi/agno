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


def _member_agent_with_knowledge(queries):
    from agno.models.openai import OpenAIChat

    def retriever(agent, query, num_documents=None, **kwargs):
        queries.append(query)
        return [{"content": "knowledge document"}]

    return Agent(
        model=OpenAIChat(id="gpt-4o", api_key="test"),
        knowledge_retriever=retriever,
        add_knowledge_to_context=True,
        search_knowledge=False,
    )


def _member_input_with_history():
    """The input a team passes to a member with add_history_to_context: its history, then the task."""
    from agno.models.message import Message
    from agno.utils.message import copy_history_message

    history = [
        copy_history_message(Message(role="user", content="What's the price of NVDA?")),
        copy_history_message(Message(role="assistant", content="NVDA is at 100.")),
    ]
    return history + [Message(role="user", content="What's the price of TSLA?")]


def _run_messages_kwargs(input):
    from agno.run.agent import RunOutput
    from agno.run.base import RunContext
    from agno.session import AgentSession

    return dict(
        run_response=RunOutput(run_id="run-1", session_id="session-1"),
        run_context=RunContext(run_id="run-1", session_id="session-1"),
        input=input,
        session=AgentSession(session_id="session-1"),
    )


def test_get_run_messages_adds_knowledge_to_team_member_task_after_history():
    """A team member with history still gets knowledge references for its task (#5723)."""
    from agno.agent._messages import get_run_messages

    queries = []
    agent = _member_agent_with_knowledge(queries)

    run_messages = get_run_messages(agent, **_run_messages_kwargs(_member_input_with_history()))

    assert queries == ["What's the price of TSLA?"]
    assert run_messages.user_message is not None
    assert run_messages.user_message.content.startswith("What's the price of TSLA?")
    assert "knowledge document" in run_messages.user_message.content
    assert [m.content for m in run_messages.messages[-3:-1]] == ["What's the price of NVDA?", "NVDA is at 100."]
    assert run_messages.messages[-1] is run_messages.user_message


@pytest.mark.asyncio
async def test_aget_run_messages_adds_knowledge_to_team_member_task_after_history():
    """Async twin: a team member with history still gets knowledge references for its task (#5723)."""
    from agno.agent._messages import aget_run_messages

    queries = []
    agent = _member_agent_with_knowledge(queries)

    run_messages = await aget_run_messages(agent, **_run_messages_kwargs(_member_input_with_history()))

    assert queries == ["What's the price of TSLA?"]
    assert run_messages.user_message is not None
    assert "knowledge document" in run_messages.user_message.content
    assert [m.content for m in run_messages.messages[-3:-1]] == ["What's the price of NVDA?", "NVDA is at 100."]
    assert run_messages.messages[-1] is run_messages.user_message


def test_get_run_messages_keeps_plain_message_list_input_as_is():
    """A list of messages that is not history followed by a task is still added unchanged."""
    from agno.agent._messages import get_run_messages
    from agno.models.message import Message

    queries = []
    agent = _member_agent_with_knowledge(queries)
    input_messages = [
        Message(role="user", content="What's the price of NVDA?"),
        Message(role="assistant", content="NVDA is at 100."),
        Message(role="user", content="What's the price of TSLA?"),
    ]

    run_messages = get_run_messages(agent, **_run_messages_kwargs(input_messages))

    assert queries == []
    assert run_messages.user_message is None
    assert run_messages.messages[-3:] == input_messages
