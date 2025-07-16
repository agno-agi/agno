"""🤖 Agentic RAG Agent - Your AI Knowledge Assistant!

This advanced example shows how to build a sophisticated RAG (Retrieval Augmented Generation) system that
leverages vector search and LLMs to provide deep insights from any knowledge base.

The agent can:
- Process and understand documents from multiple sources (PDFs, websites, text files)
- Build a searchable knowledge base using vector embeddings
- Maintain conversation context and memory across sessions
- Provide relevant citations and sources for its responses
- Generate summaries and extract key insights
- Answer follow-up questions and clarifications

Example queries to try:
- "What are the key points from this document?"
- "Can you summarize the main arguments and supporting evidence?"
- "Compare and contrast different viewpoints on [topic]"

Features:
- 🔍 Advanced vector search with semantic understanding
- 💾 Persistent memory across conversations
- 📚 Support for multiple document formats
- 🧠 Intelligent context retrieval
- 💬 Natural conversation flow
- 🔗 Source attribution and citations
"""

from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.memory import Memory
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def get_agentic_rag_agent(
    model_id: str = "openai:gpt-4o",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    debug_mode: bool = True,
) -> Agent:
    """Get an Agentic RAG Agent with knowledge base and persistent memory."""
    
    # Create the new Knowledge system with vector store
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
        model=_get_model(model_id),
        agent_id="agentic-rag-agent",
        user_id=user_id,
        memory=memory,
        knowledge=knowledge_base,
        search_knowledge=True,
        add_history_to_messages=True,
        num_history_runs=10,
        session_id=session_id,
        description="You are a helpful Agent called 'Agentic RAG' and your goal is to assist the user in the best way possible.",
        instructions=[
            "1. Knowledge Base Search:",
            "   - ALWAYS start by searching the knowledge base using search_knowledge_base tool",
            "   - Analyze ALL returned documents thoroughly before responding",
            "   - If multiple documents are returned, synthesize the information coherently",
            "2. External Search:",
            "   - If knowledge base search yields insufficient results, use duckduckgo_search",
            "   - Focus on reputable sources and recent information",
            "   - Cross-reference information from multiple sources when possible",
            "3. Context Management:",
            "   - Use get_chat_history tool to maintain conversation continuity",
            "   - Reference previous interactions when relevant",
            "   - Keep track of user preferences and prior clarifications",
            "4. Response Quality:",
            "   - Provide specific citations and sources for claims",
            "   - Structure responses with clear sections and bullet points when appropriate",
            "   - Include relevant quotes from source materials",
            "   - Avoid hedging phrases like 'based on my knowledge' or 'depending on the information'",
            "5. User Interaction:",
            "   - Ask for clarification if the query is ambiguous",
            "   - Break down complex questions into manageable parts",
            "   - Proactively suggest related topics or follow-up questions",
            "6. Error Handling:",
            "   - If no relevant information is found, clearly state this",
            "   - Suggest alternative approaches or questions",
            "   - Be transparent about limitations in available information",
        ],
        show_tool_calls=True,
        markdown=True,
        add_datetime_to_instructions=True,
        debug_mode=debug_mode,
    )

    return agent


def _get_model(model_id: str):
    """Get the model based on the model ID.

    Args:
        model_id: Model ID in the format "provider:model_name"

    Returns:
        Model instance
    """
    if model_id.startswith("openai:"):
        model_name = model_id.split("openai:")[1]
        return OpenAIChat(id=model_name)
    elif model_id.startswith("anthropic:"):
        model_name = model_id.split("anthropic:")[1]
        return Claude(id=model_name)
    elif model_id.startswith("google:"):
        model_name = model_id.split("google:")[1]
        return Gemini(id=model_name)
    elif model_id.startswith("groq:"):
        model_name = model_id.split("groq:")[1]
        return Groq(id=model_name)
    else:
        return OpenAIChat(id="gpt-4o")
