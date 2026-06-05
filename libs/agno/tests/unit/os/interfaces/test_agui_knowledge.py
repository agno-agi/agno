"""Tests for AG-UI interface knowledge handling (Issue #5368)."""

from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent import Agent
from agno.knowledge.document import Document
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.session.agent import AgentSession


class MockKnowledge:
    """Mock knowledge base for testing that satisfies KnowledgeProtocol."""

    def __init__(self, documents: Optional[List[Document]] = None):
        self.documents = documents or [
            Document(
                id="doc1",
                content="SSH connection guide: Use ssh user@host to connect.",
                meta_data={"title": "SSH Guide", "url": "https://docs.example.com/ssh"},
            )
        ]
        self.max_results = 5

    def build_context(self, **kwargs) -> Optional[str]:
        """Return context for system prompt."""
        return None

    def get_tools(self, **kwargs) -> List:
        """Return tools to expose."""
        return []

    async def aget_tools(self, **kwargs) -> List:
        """Async version of get_tools."""
        return []

    def retrieve(self, query: str, max_results: int = 5, filters=None) -> List[Document]:
        """Sync retrieve method."""
        return self.documents[:max_results]

    async def aretrieve(self, query: str, max_results: int = 5, filters=None) -> List[Document]:
        """Async retrieve method."""
        return self.documents[:max_results]


class TestAGUIKnowledgeRetrieval:
    """Test that knowledge is properly retrieved when using AG-UI interface."""

    @pytest.mark.asyncio
    async def test_knowledge_in_user_message_traditional_rag(self):
        """Test that traditional RAG adds knowledge references to user message.

        This reproduces the issue from #5368 where AG-UI responses hallucinate
        because knowledge is not being retrieved.
        """
        from agno.agent._messages import aget_user_message

        mock_knowledge = MockKnowledge()

        agent = Agent(
            id="test-agent",
            name="Test Agent",
            knowledge=mock_knowledge,
            add_knowledge_to_context=True,
            search_knowledge=False,  # Traditional RAG, not agentic
        )

        run_response = RunOutput(run_id="test-run")
        run_context = RunContext(run_id="test-run", session_id="test-session")
        run_context.knowledge = mock_knowledge  # Simulate resolved knowledge

        # Call the async user message builder
        user_message = await aget_user_message(
            agent,
            run_response=run_response,
            run_context=run_context,
            input="How do I connect using SSH?",
        )

        assert user_message is not None
        assert user_message.content is not None

        # The message should contain knowledge references
        assert "<references>" in user_message.content, (
            "Knowledge references should be added to user message when add_knowledge_to_context=True"
        )
        assert "SSH connection guide" in user_message.content or "SSH Guide" in user_message.content

    @pytest.mark.asyncio
    async def test_knowledge_callable_factory_resolution(self):
        """Test that callable knowledge factory is resolved and used."""
        from agno.agent._tools import aget_tools

        mock_knowledge = MockKnowledge()

        # Create a callable factory that returns the knowledge
        def get_knowledge():
            return mock_knowledge

        agent = Agent(
            id="test-agent",
            name="Test Agent",
            model="openai:gpt-4o-mini",  # Use valid model string
            knowledge=get_knowledge,  # Callable factory
            add_knowledge_to_context=True,
            search_knowledge=False,
        )

        run_response = RunOutput(run_id="test-run")
        run_context = RunContext(run_id="test-run", session_id="test-session")
        session = AgentSession(session_id="test-session")

        # Call aget_tools which should resolve the callable knowledge
        await aget_tools(
            agent,
            run_response=run_response,
            run_context=run_context,
            session=session,
        )

        # After aget_tools, run_context.knowledge should be populated
        assert run_context.knowledge is not None, (
            "Callable knowledge factory should be resolved and placed in run_context.knowledge"
        )
        assert run_context.knowledge is mock_knowledge

    @pytest.mark.asyncio
    async def test_agui_router_passes_knowledge_to_agent(self):
        """Test that AG-UI router properly triggers knowledge retrieval.

        This is an integration-style test that verifies the full path from
        AG-UI router to knowledge retrieval.
        """
        from ag_ui.core import RunAgentInput
        from ag_ui.core.types import UserMessage

        from agno.os.interfaces.agui.router import run_agent

        mock_knowledge = MockKnowledge()

        agent = Agent(
            id="test-agent",
            name="Test Agent",
            model="openai:gpt-4o-mini",
            knowledge=mock_knowledge,
            add_knowledge_to_context=True,
            search_knowledge=False,
        )

        # Mock the agent.arun to capture what's sent to it
        captured_inputs = []

        async def mock_arun(*args, **kwargs):
            captured_inputs.append(kwargs)
            # Return a minimal response
            from agno.run.agent import RunCompletedEvent

            yield RunCompletedEvent()

        agent.arun = mock_arun

        run_input = RunAgentInput(
            thread_id="test-thread",
            run_id="test-run",
            messages=[UserMessage(id="msg1", role="user", content="How do I connect using SSH?")],
            state=None,
            tools=[],
            context=[],
            forwardedProps=None,
        )

        # Run the AG-UI router
        events = []
        async for event in run_agent(agent, run_input):
            events.append(event)

        # Verify the router called agent.arun with the right input
        assert len(captured_inputs) > 0, "agent.arun should have been called"

        # The input should be the extracted user message
        assert captured_inputs[0].get("input") == "How do I connect using SSH?"

    @pytest.mark.asyncio
    async def test_agui_vs_standard_api_knowledge_parity(self):
        """Test that AG-UI and standard API both retrieve knowledge.

        This is the core test for issue #5368 - knowledge should be retrieved
        identically whether calling via AG-UI or standard agent API.
        """
        from agno.agent._messages import aget_run_messages
        from agno.agent._tools import aget_tools

        mock_knowledge = MockKnowledge()
        retrieve_calls = []

        # Patch retrieve to track calls
        original_retrieve = mock_knowledge.retrieve
        original_aretrieve = mock_knowledge.aretrieve

        def tracked_retrieve(*args, **kwargs):
            retrieve_calls.append(("sync", args, kwargs))
            return original_retrieve(*args, **kwargs)

        async def tracked_aretrieve(*args, **kwargs):
            retrieve_calls.append(("async", args, kwargs))
            return await original_aretrieve(*args, **kwargs)

        mock_knowledge.retrieve = tracked_retrieve
        mock_knowledge.aretrieve = tracked_aretrieve

        # Create agent with static knowledge (NOT a callable factory)
        agent = Agent(
            id="test-agent",
            name="Test Agent",
            model="openai:gpt-4o-mini",
            knowledge=mock_knowledge,  # Static knowledge, not callable
            add_knowledge_to_context=True,
            search_knowledge=False,  # Traditional RAG
        )

        run_response = RunOutput(run_id="test-run")
        run_context = RunContext(run_id="test-run", session_id="test-session")
        session = AgentSession(session_id="test-session")

        # Simulate what agent.arun() does internally:
        # 1. Call aget_tools (resolves callable knowledge if any)
        await aget_tools(
            agent,
            run_response=run_response,
            run_context=run_context,
            session=session,
        )

        # 2. Call aget_run_messages (retrieves knowledge for traditional RAG)
        run_messages = await aget_run_messages(
            agent,
            run_response=run_response,
            run_context=run_context,
            input="How do I connect using SSH?",
            session=session,
        )

        # Verify knowledge was retrieved
        assert len(retrieve_calls) > 0, "Knowledge retrieval should have been called when add_knowledge_to_context=True"

        # Verify the user message contains knowledge references
        user_msg = run_messages.user_message
        assert user_msg is not None
        assert "<references>" in (user_msg.content or ""), (
            f"User message should contain knowledge references. Got: {user_msg.content[:200] if user_msg.content else 'None'}..."
        )

    def test_agentos_initializes_interface_agents(self):
        """Test that AgentOS initializes agents passed to interfaces.

        This is the core fix for issue #5368 - agents passed to AGUI interface
        should receive the same initialization as agents in the agents list.
        """
        from agno.os.app import AgentOS
        from agno.os.interfaces.agui import AGUI

        mock_knowledge = MockKnowledge()

        # Create agent WITHOUT calling initialize_agent
        agent = Agent(
            id="test-agent",
            name="Test Agent",
            model="openai:gpt-4o-mini",
            knowledge=mock_knowledge,
            add_knowledge_to_context=True,
        )

        # Verify agent hasn't been initialized yet
        assert agent._formatter is None, "Agent should not be initialized before AgentOS"

        # Create a second agent for the agents list (different instance)
        agent_in_list = Agent(
            id="other-agent",
            name="Other Agent",
            model="openai:gpt-4o-mini",
        )

        # Create AgentOS with interface agent SEPARATE from agents list
        agent_os = AgentOS(
            id="test-os",
            agents=[agent_in_list],  # Different agent in the list
            interfaces=[AGUI(agent)],  # Our test agent only in interface
        )

        # After AgentOS creation, the interface agent should be initialized
        assert agent._formatter is not None, "Agent passed to AGUI interface should be initialized by AgentOS"
        assert agent.store_events is True, "Agent passed to AGUI interface should have store_events=True"
