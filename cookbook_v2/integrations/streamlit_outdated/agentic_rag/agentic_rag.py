"""🤖 Agentic RAG Agent - Your AI Knowledge Assistant!

This example shows how to build a RAG (Retrieval Augmented Generation) system that
leverages vector search and LLMs to provide insights from any knowledge base.

The agent can:
- Process and understand documents from multiple sources (PDFs, websites, text files)
- Build a searchable knowledge base using vector embeddings
- Maintain conversation context and memory across sessions
- Provide relevant citations and sources for its responses

View the README for instructions on how to run the application.
"""

from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.memory import Memory
from agno.utils.streamlit import get_model_from_id
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def get_agentic_rag_agent(
    model_id: str = "openai:gpt-4o",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    debug_mode: bool = True,
) -> Agent:
    """Get an Agentic RAG Agent with knowledge"""

    # Create the Knowledge system with vector store
    knowledge_base = Knowledge(
        name="Agentic RAG Knowledge Base",
        description="Knowledge base for agentic RAG application",
        vector_store=PgVector(
            db_url=db_url,
            table_name="agentic_rag_documents",
            schema="ai",
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
        max_results=10,
    )

    memory = Memory(
        db=PostgresDb(
            db_url=db_url,
            session_table="sessions",
            db_schema="ai",
        )
    )

    agent = Agent(
        name="Agentic RAG Agent",
        model=get_model_from_id(model_id),
        agent_id="agentic-rag-agent",
        user_id=user_id,
        memory=memory,
        knowledge=knowledge_base,
        search_knowledge=True,
        read_tool_call_history=True,
        add_history_to_messages=True,
        num_history_runs=10,
        session_id=session_id,
        description="You are a helpful Agent called 'Agentic RAG' and your goal is to assist the user in the best way possible.",
        instructions=[
            "Search your knowledge base before answering questions.",
            "Include sources and citations in your responses.",
            "If the knowledge base doesn't have sufficient information, use web search.",
            "Structure responses clearly with relevant quotes and references.",
        ],
        show_tool_calls=True,
        markdown=True,
        add_datetime_to_instructions=True,
        debug_mode=debug_mode,
    )

    return agent
