"""
Basic Support Agent
===================

A simplified customer support agent demonstrating core concepts:
- Knowledge base integration with PgVector
- ZendeskTools for ticket operations
- ReasoningTools for step-by-step thinking

This agent is ideal for learning the fundamentals before moving to
the advanced agent with HITL, memory, and escalation workflows.

Usage:
    from agent import agent
    agent.print_response("How do I set up hybrid search?", stream=True)
"""

from pathlib import Path

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.tools.reasoning import ReasoningTools
from agno.tools.zendesk import ZendeskTools
from agno.vectordb.pgvector import PgVector, SearchType

DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
KNOWLEDGE_DIR = Path(__file__).parent.parent / "knowledge"

knowledge = Knowledge(
    name="Support Knowledge Base",
    vector_db=PgVector(
        table_name="support_knowledge",
        db_url=DB_URL,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=10,
)

agent = Agent(
    name="Support Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    tools=[
        ReasoningTools(add_instructions=True),
        # Read-only Zendesk ticket operations (FAQ handled by Agno knowledge base)
        ZendeskTools(
            enable_get_tickets=True,
            enable_get_ticket=True,
            enable_get_ticket_comments=True,
        ),
    ],
    search_knowledge=True,
    markdown=True,
)

if __name__ == "__main__":
    agent.print_response(
        "What are the SLA response times for different priority tickets?",
        stream=True,
    )
