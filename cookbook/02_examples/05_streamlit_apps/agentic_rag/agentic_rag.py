"""🤖 Agentic RAG - Your AI Knowledge Agent!
This advanced example shows how to build a sophisticated RAG (Retrieval Augmented Generation) system that
leverages vector search and Language Models to provide deep insights from any knowledge base.

The Agent can:
- Process and understand documents from multiple sources (PDFs, websites, text files)
- Build a searchable knowledge base using vector embeddings
- Maintain conversation context and memory across sessions
- Provide relevant citations and sources for its responses
- Generate summaries and extract key insights
- Answer follow-up questions and clarifications

Example Queries to Try:
- "What are the key points from this document?"
- "Can you summarize the main arguments and supporting evidence?"
- "What are the important statistics and findings?"
- "How does this relate to [topic X]?"
- "What are the limitations or gaps in this analysis?"
- "Can you explain [concept X] in more detail?"
- "What other sources support or contradict these claims?"

The Agent uses:
- Vector similarity search for relevant document retrieval
- Conversation memory for contextual responses
- Citation tracking for source attribution
- Dynamic knowledge base updates

View the README for instructions on how to run the application.
"""

from textwrap import dedent
from typing import Optional

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.utils.streamlit import get_model_from_id
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def get_agentic_rag_agent(
    model_id: str = "openai:gpt-4o",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Agent:
    """Get an Agentic RAG Agent with Memory"""
    contents_db = PostgresDb(
        db_url=db_url,
        knowledge_table="agentic_rag_knowledge_contents",
        db_schema="ai",
    )

    knowledge_base = Knowledge(
        name="Agentic RAG Knowledge Base",
        description="Knowledge base for agentic RAG application",
        vector_db=PgVector(
            db_url=db_url,
            table_name="agentic_rag_documents",
            schema="ai",
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
        contents_db=contents_db,
        max_results=3,  # Only return top 3 most relevant documents
    )

    db = PostgresDb(
        db_url=db_url,
        session_table="sessions",
        db_schema="ai",
    )

    agent = Agent(
        name="Agentic RAG Agent",
        model=get_model_from_id(model_id),
        id="agentic-rag-agent",
        user_id=user_id,
        db=db,
        enable_user_memories=True,
        knowledge=knowledge_base,
        add_history_to_context=True,
        num_history_runs=5,
        session_id=session_id,
        tools=[DuckDuckGoTools()],
        instructions=dedent("""
            1. Knowledge Base Search:
               - ALWAYS start by searching the knowledge base using search_knowledge_base tool
               - Analyze ALL returned documents thoroughly before responding
               - If multiple documents are returned, synthesize the information coherently
            2. External Search:
               - If knowledge base search yields insufficient results, use duckduckgo_search
               - Focus on reputable sources and recent information
               - Cross-reference information from multiple sources when possible
            3. Context Management:
               - Use get_chat_history tool to maintain conversation continuity
               - Reference previous interactions when relevant
               - Keep track of user preferences and prior clarifications
            4. Response Quality:
               - Provide specific citations and sources for claims
               - Structure responses with clear sections and bullet points when appropriate
               - Include relevant quotes from source materials
               - Avoid hedging phrases like 'based on my knowledge' or 'depending on the information'
            5. User Interaction:
               - Ask for clarification if the query is ambiguous
               - Break down complex questions into manageable parts
               - Proactively suggest related topics or follow-up questions
            6. Error Handling:
               - If no relevant information is found, clearly state this
               - Suggest alternative approaches or questions
               - Be transparent about limitations in available information
        """),
        markdown=True,
        debug_mode=True,
    )

    return agent
