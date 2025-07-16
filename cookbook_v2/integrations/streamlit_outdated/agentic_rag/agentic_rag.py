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
- "What are the important statistics and findings?"
- "How does this relate to [topic X]?"
- "What are the limitations or gaps in this analysis?"
- "Can you explain [concept X] in more detail?"
- "What other sources support or contradict these claims?"

The agent uses:
- Vector similarity search for relevant document retrieval
- Conversation memory for contextual responses
- Citation tracking for source attribution
- Dynamic knowledge base updates
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
        model=get_model_from_id(model_id),
        agent_id="agentic-rag-agent",
        user_id=user_id,
        memory=memory,
        knowledge=knowledge_base,
        search_knowledge=True,
        read_tool_call_history=True,
        add_history_to_messages=True,
        num_history_runs=10,
        enable_session_summaries=True,
        add_session_summary_references=True,
        session_id=session_id,
        description="You are a helpful Agent called 'Agentic RAG' and your goal is to assist the user in the best way possible.",
        expected_output="Comprehensive, well-structured responses with proper citations, sources, and evidence-based conclusions. Include relevant quotes and reference specific documents when available.",
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
