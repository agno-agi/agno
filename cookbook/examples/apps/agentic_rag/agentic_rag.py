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
from agno.embedder.openai import OpenAIEmbedder
from agno.knowledge import AgentKnowledge
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.models.groq import Groq
from agno.models.openai import OpenAIChat
from agno.storage.agent.postgres import PostgresAgentStorage
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.vectordb.pgvector import PgVector

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"


def get_agentic_rag_agent(
    model_id: str = "openai:gpt-4o",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    debug_mode: bool = True,
) -> Agent:
    """Get an Agentic RAG Agent with Memory."""
    # Parse model provider and name
    provider, model_name = model_id.split(":")

    # Select appropriate model class based on provider
    if provider == "openai":
        model = OpenAIChat(id=model_name)
    elif provider == "google":
        model = Gemini(id=model_name)
    elif provider == "anthropic":
        model = Claude(id=model_name)
    elif provider == "groq":
        model = Groq(id=model_name)
    else:
        raise ValueError(f"Unsupported model provider: {provider}")
    # Define persistent memory for chat history

    # Define the knowledge base
    knowledge_base = AgentKnowledge(
        vector_db=PgVector(
            db_url=db_url,
            table_name="agentic_rag_documents",
            schema="ai",
            # Use OpenAI embeddings
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
        num_documents=3,  # Retrieve 3 most relevant documents
    )

    # Create the Agent
    return Agent(
        name="agentic_rag_agent",
        session_id=session_id,  # Track session ID for persistent conversations
        user_id=user_id,
        model=model,
        storage=PostgresAgentStorage(
            table_name="agentic_rag_agent_sessions", db_url=db_url
        ),  # Persist session data
        knowledge=knowledge_base,  # Add knowledge base
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
        search_knowledge=True,  # This setting gives the model a tool to search the knowledge base for information
        read_chat_history=True,  # This setting gives the model a tool to get chat history
        tools=[DuckDuckGoTools()],
        markdown=True,  # This setting tellss the model to format messages in markdown
        # add_chat_history_to_messages=True,
        show_tool_calls=True,
        add_history_to_messages=True,  # Adds chat history to messages
        add_datetime_to_instructions=True,
        debug_mode=debug_mode,
        read_tool_call_history=True,
        num_history_responses=3,
    )
