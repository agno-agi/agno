"""
Knowledge Agent - A general-purpose RAG agent with knowledge base search.

This agent demonstrates how to build a RAG-powered assistant that:
- Searches a knowledge base for relevant information
- Provides accurate, context-aware responses
- Generates working code examples

The knowledge base uses docs.agno.com/llms-full.txt as an example,
but can be configured to use any URL or documents.

Example queries:
- "What is Agno and what can it do?"
- "How do I create an agent with tools?"
- "Show me how to use knowledge bases in Agno"
"""

import sys
from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType
from db import db_url, demo_db

# ============================================================================
# Setup knowledge base
# ============================================================================
knowledge = Knowledge(
    name="Knowledge Base",
    vector_db=PgVector(
        db_url=db_url,
        table_name="knowledge_agent_docs",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    # 10 results returned on query
    max_results=10,
    contents_db=demo_db,
)

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent(
    """\
    You are a Knowledge Agent - an AI assistant that searches a knowledge base
    to provide accurate, well-sourced answers and working code examples.\
    """
)

instructions = dedent(
    """\
    Your mission is to provide accurate, helpful responses by searching your knowledge base.

    Follow this process:

    1. **Analyze the request**
        - Determine what information is needed
        - Identify key terms to search for

    2. **Search Process**
        - Use the `search_knowledge` tool to find relevant information
        - Perform multiple searches with different terms if needed
        - Continue until you have comprehensive information

    3. **Response Guidelines**
        - Always cite information from the knowledge base
        - If asked for code, provide complete, working examples
        - Include all necessary imports and setup
        - Be specific and actionable

    4. **Code Examples**
        - Provide fully working code that can be run as-is
        - Always use `agent.run()` for execution
        - Include comments explaining key parts
        - Show example usage

        Example:
        ```python
        from agno.agent import Agent
        from agno.tools.websearch import WebSearchTools

        agent = Agent(tools=[WebSearchTools()])

        response = agent.run("What's happening in France?")
        print(response)
        ```

    5. **Handling Uncertainty**
        - If information is not in the knowledge base, say so clearly
        - Don't make up information that isn't supported by sources
        - Suggest what additional information might help
    """
)

# ============================================================================
# Create the Agent
# ============================================================================
knowledge_agent = Agent(
    name="Knowledge Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    knowledge=knowledge,
    description=description,
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    enable_agentic_memory=True,
    num_history_runs=5,
    markdown=True,
    db=demo_db,
)


# ============================================================================
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("Knowledge Agent")
    print("   RAG-powered assistant with knowledge base search")
    print("=" * 60)

    # Load knowledge base
    print("\n--- Loading knowledge base from docs.agno.com ---")
    knowledge.insert(
        name="Knowledge Base Documentation",
        url="https://docs.agno.com/llms-full.txt",
        skip_if_exists=True,
    )
    print("Knowledge base loaded!")

    if len(sys.argv) > 1:
        # Run with command line argument
        message = " ".join(sys.argv[1:])
        knowledge_agent.print_response(message, stream=True)
    else:
        # Run demo tests
        print("\n--- Demo 1: General Question ---")
        knowledge_agent.print_response(
            "What is Agno and what are its main features?",
            stream=True,
        )

        print("\n--- Demo 2: Code Request ---")
        knowledge_agent.print_response(
            "Show me how to create an agent with web search capabilities",
            stream=True,
        )

        print("\n--- Demo 3: Advanced Topic ---")
        knowledge_agent.print_response(
            "How do I create a team of agents that work together?",
            stream=True,
        )
