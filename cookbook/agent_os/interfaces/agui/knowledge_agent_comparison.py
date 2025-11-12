"""Example: Knowledge-Based Agent - Standard API vs AGUI Comparison (Issue #5368)

This cookbook reproduces Issue #5368 to investigate why AGUI produces different responses
than the standard Agent API when using knowledge bases.

ISSUE #5368:
- Same agent with temperature=0
- Standard API: Good responses, follows instructions
- AGUI: More hallucinations, ignores instructions

INVESTIGATION:
This script sets up the same agent with both interfaces so we can compare
the messages sent to the LLM in both cases.

USAGE:
1. Run: python cookbook/agent_os/interfaces/agui/knowledge_agent_comparison.py
2. Test standard API: POST http://localhost:9003/agents/docs-agent/runs
3. Test AGUI: POST http://localhost:9003/agui
4. Compare logs to see message differences
"""

from pathlib import Path

from agno.agent.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.interfaces.agui import AGUI
from agno.os.settings import AgnoAPISettings
from agno.vectordb.lancedb import LanceDb, SearchType

# =============================================================================
# MOCK KNOWLEDGE BASE (Simulating HPC Documentation)
# =============================================================================

# In production, this would load from actual documents
# For testing, we'll use a simple in-memory knowledge base


def setup_knowledge():
    """Set up knowledge base using pre-existing database.
    
    Run tmp/issues/issue_5368/setup_knowledge.py first to create the database.
    This function just connects to it without loading (no asyncio conflict).
    """
    knowledge = Knowledge(
        vector_db=LanceDb(
            uri="tmp/issue_5368_kb",
            table_name="test_docs",
            search_type=SearchType.vector,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )
    return knowledge


# =============================================================================
# AGENT CONFIGURATION (Matching Issue #5368)
# =============================================================================


def get_docs_agent() -> Agent:
    """Create docs assistant agent matching Issue #5368 configuration.
    
    NOW WITH KNOWLEDGE to test the actual bug.
    Matches user's setup: add_knowledge_to_context=True, search_knowledge=False
    """
    
    return Agent(
        name="docs-agent",
        model=OpenAIChat(id="gpt-4o", temperature=0),  # temperature=0 for consistency
        introduction="You are an expert on HPC cluster documentation.",
        role="Helpful HPC Documentation Assistant",
        expected_output=" ".join(
            [
                "Provide accurate answers based on the knowledge available from the website in the <references> section.",
                "If you cannot determine an adequate answer, include 'Contact Support for help' as part of your response.",
                "After providing an answer, include citations at the end of the response.",
            ]
        ),
        additional_context=" ".join(
            [
                "<citations>You can find the title and url in the metadata of each reference.",
                "For example, if a reference has metadata: {'url': 'https://docs.example.com/ssh', 'title': 'SSH Guide'}",
                "You would cite it as: [SSH Guide](https://docs.example.com/ssh).",
                "If multiple references are used, list them all at the end.</citations>",
            ]
        ),
        knowledge=setup_knowledge(),  # Use pre-built knowledge base
        add_knowledge_to_context=True,  # Same as Issue #5368
        search_knowledge=False,  # Same as Issue #5368
        markdown=True,
    )


# =============================================================================
# AGENTOS SETUP - BOTH INTERFACES
# =============================================================================

docs_agent = get_docs_agent()

agent_os = AgentOS(
    agents=[docs_agent],
    interfaces=[
        AGUI(agent=docs_agent)  # AGUI interface at /agui
    ],
    settings=AgnoAPISettings(os_security_key=None),  # Disable security for testing
)

app = agent_os.get_app()


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    """Run the agent with both Standard API and AGUI interfaces.
    
    ENDPOINTS:
        Standard API:
        - POST http://localhost:9003/agents/docs-agent/runs
          Body: {"message": "How do I connect using SSH?", "stream": false}
        
        AGUI:
        - POST http://localhost:9003/agui
          Body: {
            "threadId": "test-123",
            "runId": "run-123",
            "messages": [{"id": "1", "role": "user", "content": "How do I connect using SSH?"}],
            "state": {},
            "tools": [],
            "context": []
          }
    
    INVESTIGATION STEPS:
    1. Start this server
    2. Send same query to both endpoints
    3. Compare server logs
    4. Look for differences in:
       - System message content
       - Knowledge refs positioning
       - Message count and order
       
    Expected to find:
    - Standard API: Clean message structure
    - AGUI: Potentially different structure causing worse responses
    """
    print("=" * 80)
    print("Knowledge Agent Comparison - Issue #5368 Investigation")
    print("=" * 80)
    print("\nStarting AgentOS with both Standard API and AGUI...")
    print("\nEndpoints:")
    print("  - Standard API: http://localhost:9003/agents/docs-agent/runs")
    print("  - AGUI: http://localhost:9003/agui")
    print("\nTest Query:")
    print('  "How do I connect using SSH?"')
    print("\nWhat to Compare:")
    print("  - System message content")
    print("  - Knowledge refs in context")
    print("  - Message order and count")
    print("  - Final LLM input")
    print("=" * 80)
    print()

    agent_os.serve(
        app="knowledge_agent_comparison:app",
        reload=True,
        port=9003,  # Changed from 9001
    )
