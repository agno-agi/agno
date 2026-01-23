"""
Internal Knowledge Agent
========================

A RAG-powered knowledge agent that provides intelligent access to internal company
documentation. Uses hybrid search (semantic + keyword) over PgVector for accurate
retrieval with source citations.

Example prompts:
- "What is the PTO policy?"
- "How do I set up my development environment?"
- "What are the coding standards for Python?"

Usage:
    from agent import knowledge_agent

    # Ask a question
    knowledge_agent.print_response("What is the PTO policy?", stream=True)

    # Interactive mode
    knowledge_agent.cli_app(stream=True)
"""

from pathlib import Path

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.tools.reasoning import ReasoningTools
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Configuration
# ============================================================================
DB_URL = "postgresql+psycopg://ai:ai@localhost:5532/ai"
KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"


# ============================================================================
# Knowledge Configuration
# ============================================================================
company_knowledge = Knowledge(
    name="Company Knowledge Base",
    vector_db=PgVector(
        table_name="company_knowledge",
        db_url=DB_URL,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    max_results=10,
)


# ============================================================================
# System Message
# ============================================================================
SYSTEM_MESSAGE = """\
You are an internal knowledge assistant that helps employees find information from
company documentation. You have access to employee handbooks, product guides,
engineering wikis, and onboarding materials.

## Your Responsibilities

1. **Answer Questions** - Provide accurate answers based on the knowledge base
2. **Cite Sources** - Always reference which documents your information comes from
3. **Acknowledge Uncertainty** - If information is not in the knowledge base, say so
4. **Suggest Follow-ups** - Recommend related topics the user might find helpful

## Guidelines

### Answering Questions
- Search the knowledge base before answering
- Synthesize information from multiple sources when relevant
- Quote specific sections when precision matters
- Use clear, professional language

### Source Citations
- Always mention which document(s) you're drawing from
- Include section names or headers when available
- If multiple documents conflict, note the discrepancy

### Handling Uncertainty
- Do NOT make up information not in the knowledge base
- Clearly state when information is not found
- Suggest who or where to ask for information you don't have
- Ask clarifying questions if the query is ambiguous

### Conversation Context
- Remember previous questions in the conversation
- Build on earlier answers when relevant
- Notice if the user is drilling down on a topic

## Confidence Levels

- **High**: Answer is directly stated in a source document
- **Medium**: Answer is synthesized from multiple sources or requires some inference
- **Low**: Information is partial or the question is ambiguous

Always use the think tool to plan your search and synthesis approach before answering.
"""


# ============================================================================
# Create the Agent
# ============================================================================
knowledge_agent = Agent(
    name="Knowledge Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=company_knowledge,
    system_message=SYSTEM_MESSAGE,
    tools=[
        ReasoningTools(add_instructions=True),
    ],
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    read_chat_history=True,
    enable_agentic_memory=True,
    search_knowledge=True,
    markdown=True,
)


# ============================================================================
# Exports
# ============================================================================
__all__ = [
    "knowledge_agent",
    "company_knowledge",
    "DB_URL",
    "KNOWLEDGE_DIR",
]

if __name__ == "__main__":
    knowledge_agent.print_response("What is the PTO policy?", stream=True)
