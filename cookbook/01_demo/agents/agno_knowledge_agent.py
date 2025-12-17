from textwrap import dedent

from agno.agent import Agent
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.models.anthropic import Claude
from agno.vectordb.pgvector import PgVector, SearchType
from db import db_url, demo_db

# ============================================================================
# Setup knowledge base for storing Agno documentation
# ============================================================================
knowledge = Knowledge(
    name="Agno Documentation",
    vector_db=PgVector(
        db_url=db_url,
        table_name="agno_docs",
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
    You are AgnoAssist — an AI Agent built to help developers learn and master the Agno framework.
    Your goal is to provide clear explanations and complete, working code examples to help users understand and effectively use Agno and AgentOS.\
    """
)

instructions = dedent(
    """\
    Your mission is to provide comprehensive, developer-focused support for the Agno ecosystem.

    Follow this structured process to ensure accurate and actionable responses:

    1. **Analyze the request**
        - Determine whether the query requires a knowledge lookup, code generation, or both.
        - All concepts are within the context of Agno - you don't need to clarify this.

    After analysis, immediately begin the search process (no need to ask for confirmation).

    2. **Search Process**
        - Use the `search_knowledge` tool to retrieve relevant concepts, code examples, and implementation details.
        - Perform iterative searches until you've gathered enough information or exhausted relevant terms.

    Once your research is complete, decide whether code creation is required.
    If it is, ask the user if they'd like you to generate an Agent for them.

    3. **Code Creation**
        - Provide fully working code examples that can be run as-is.
        - Always use `agent.run()` (not `agent.print_response()`).
        - Include all imports, setup, and dependencies.
        - Add clear comments, type hints, and docstrings.
        - Demonstrate usage with example queries.

        Example:
        ```python
        from agno.agent import Agent
        from agno.tools.duckduckgo import DuckDuckGoTools

        agent = Agent(tools=[DuckDuckGoTools()])

        response = agent.run("What's happening in France?")
        print(response)
        ```
    """
)

# ============================================================================
# Create the Agent
# ============================================================================
agno_knowledge_agent = Agent(
    name="Agno Knowledge Agent",
    model=Claude(id="claude-sonnet-4-5"),
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

if __name__ == "__main__":
    knowledge.add_content(
        name="Agno Documentation", url="https://docs.agno.com/llms-full.txt"
    )
