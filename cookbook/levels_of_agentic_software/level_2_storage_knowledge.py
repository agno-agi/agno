"""
Level 2: Agent with storage and knowledge
======================================
Add persistent storage and a searchable knowledge base.
The agent can recall conversations and use domain knowledge.

This builds on Level 1 by adding:
- Storage: SqliteDb for conversation history across sessions
- Knowledge: ChromaDb with hybrid search for domain knowledge

Run standalone:
    python cookbook/levels_of_agentic_software/level_2_storage_knowledge.py

Run via Agent OS:
    python cookbook/levels_of_agentic_software/run.py
    Then visit https://os.agno.com and select "L2 Coding Agent"

Example prompt:
    "Write a CSV parser following our coding conventions"
"""

from pathlib import Path

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.models.openai import OpenAIResponses
from agno.tools.coding import CodingTools
from agno.vectordb.chroma import ChromaDb, SearchType

# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("workspace")
WORKSPACE.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Storage and Knowledge
# ---------------------------------------------------------------------------
db = SqliteDb(db_file=str(WORKSPACE / "agents.db"))

knowledge = Knowledge(
    vector_db=ChromaDb(
        collection="coding-standards",
        path=str(WORKSPACE / "chromadb"),
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=db,
)

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a coding agent with access to domain knowledge.

## Workflow

1. Search your knowledge base for relevant domain knowledge
2. Understand the task
3. Write code that follows the domain knowledge
4. Save the code to a file and run it to verify
5. If there are errors, fix them and re-run

## Rules

- Always search knowledge before writing code
- Follow domain knowledge found in the knowledge base
- Save code to files before running
- Include type hints and docstrings
- No emojis\
"""

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
l2_coding_agent = Agent(
    name="L2 Coding Agent",
    model=OpenAIResponses(id="gpt-5.2"),
    instructions=instructions,
    tools=[CodingTools(base_dir=WORKSPACE, all=True)],
    knowledge=knowledge,
    search_knowledge=True,
    db=db,
    add_history_to_context=True,
    num_history_runs=3,
    markdown=True,
    add_datetime_to_context=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Step 1: Load project conventions into the knowledge base
    print("Loading domain knowledge into knowledge base...")
    knowledge.insert(
        text_content="""\
## Domain Knowledge

### Style
- Use snake_case for all function and variable names
- Use type hints on all function signatures
- Write docstrings in Google style format
- Prefer list comprehensions over map/filter
- Maximum line length: 88 characters (Black formatter default)

### Error Handling
- Use specific exception types, never bare except
- Always include a meaningful error message
- Use logging instead of print for non-output messages

### File I/O
- Use pathlib.Path instead of os.path
- Use context managers (with statements) for file operations
- Default encoding: utf-8

### Testing
- Include example usage in a __main__ block
- Test edge cases: empty input, single element, large input
""",
    )

    # Step 2: Ask the agent to write code following conventions
    print("\n--- Session 1: Write code following conventions ---\n")
    l2_coding_agent.print_response(
        "Write a CSV parser that reads a CSV file and returns a list of "
        "dictionaries. Follow our project conventions. Save it to csv_parser.py "
        "and test it with sample data.",
        user_id="dev@example.com",
        session_id="session_1",
        stream=True,
    )

    # Step 3: Follow-up in the same session (agent has context)
    print("\n--- Session 1: Follow-up question ---\n")
    l2_coding_agent.print_response(
        "Add a function to write dictionaries back to CSV format.",
        user_id="dev@example.com",
        session_id="session_1",
        stream=True,
    )
