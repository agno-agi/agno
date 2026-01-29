"""
Pal - Personal Agent that Learns
================================

Your AI-powered second brain.

Pal researches, captures, organizes, connects, and retrieves your personal
knowledge - so nothing useful is ever lost.

Uses callable tools for per-user DuckDB isolation - each user gets their own
database file automatically.

Example queries:
- "Note: decided to use Postgres for the new project"
- "Bookmark https://docs.agno.com - Agno documentation"
- "Research event sourcing best practices and save the findings"

Test:
    python cookbook/demo/agents/pal_agent.py
    python cookbook/demo/agents/pal_agent.py "Your query here"
"""

from os import getenv
from pathlib import Path
from typing import List, Union

from agno.agent import Agent
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.run import RunContext
from agno.tools.duckdb import DuckDbTools
from agno.tools.function import Function
from agno.tools.mcp import MCPTools
from agno.tools.toolkit import Toolkit
from agno.vectordb.pgvector import PgVector, SearchType

from db import db_url, demo_db

# ============================================================================
# Setup
# ============================================================================
DATA_DIR = Path(getenv("DATA_DIR", "workspace/pal"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Exa MCP for research
EXA_API_KEY = getenv("EXA_API_KEY", "")
EXA_MCP_URL = (
    (
        f"https://mcp.exa.ai/mcp?exaApiKey={EXA_API_KEY}&tools="
        "web_search_exa,"
        "get_code_context_exa,"
        "company_research_exa,"
        "crawling_exa,"
        "people_search_exa"
    )
    if EXA_API_KEY
    else None
)

# Knowledge base for semantic search and learnings
pal_knowledge = Knowledge(
    name="Pal Knowledge",
    vector_db=PgVector(
        db_url=db_url,
        table_name="pal_knowledge",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=demo_db,
)


# ============================================================================
# Callable Tools - Per-User DuckDB
# ============================================================================
def get_user_tools(run_context: RunContext) -> List[Union[Toolkit, Function]]:
    """
    Create user-specific tools at runtime.

    Each user gets their own DuckDB database file for complete data isolation.
    This is called when agent.run() is invoked with a user_id.

    Args:
        run_context: Runtime context with user_id, session_id, etc.

    Returns:
        List of tools configured for this specific user.
    """
    user_id = run_context.user_id or "default"

    # Sanitize user_id for use in file names
    safe_user_id = user_id.replace("@", "_").replace(".", "_").replace("/", "_")

    # Create user-specific data directory
    user_dir = DATA_DIR / "users" / safe_user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    # Each user gets their own DuckDB database
    db_path = str(user_dir / "pal_data.db")

    print(f"Initializing Pal tools for user: {user_id}")
    print(f"Database: {db_path}")

    tools: List[Union[Toolkit, Function]] = [
        DuckDbTools(db_path=db_path, read_only=False),
    ]

    # Add MCP tools if API key is available
    if EXA_MCP_URL:
        tools.append(MCPTools(url=EXA_MCP_URL))

    return tools


# ============================================================================
# Instructions
# ============================================================================
instructions = """\
You are Pal, a personal agent that learns.

## Your Purpose

You are the user's AI-powered second brain. You research, capture, organize,
connect, and retrieve their personal knowledge - so nothing useful is ever lost.

## Two Storage Systems

**DuckDB** - User's actual data:
- notes, bookmarks, people, meetings, projects
- This is where user content goes
- Each user has their own isolated database

**Learning System** - System knowledge (schemas, research, errors):
- Table schemas so you remember what tables exist
- Research findings when user asks to save them
- Error patterns and fixes so you don't repeat mistakes
- NOT for user's notes/bookmarks/etc - those go in DuckDB

## CRITICAL: What goes where

| User says | Store in | NOT in |
|-----------|----------|--------|
| "Note: decided to use Postgres" | DuckDB `notes` table | save_learning |
| "Bookmark https://..." | DuckDB `bookmarks` table | save_learning |
| "Met Sarah from Anthropic" | DuckDB `people` table | save_learning |
| (after CREATE TABLE) | save_learning (schema only) | - |
| "Research X and save findings" | save_learning | - |
| (after fixing a DuckDB error) | save_learning (error + fix) | - |

## When to call save_learning

1. **After CREATE TABLE** - Save the schema (not the data!)
```
save_learning(
  title="notes table schema",
  learning="CREATE TABLE notes (id INTEGER PRIMARY KEY, content TEXT, tags TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)",
  context="Schema for user's notes",
  tags=["schema"]
)
```

2. **When user explicitly asks to save research findings**
```
save_learning(
  title="Event sourcing best practices",
  learning="Key patterns: 1) Start simple 2) Events are immutable",
  context="From web research",
  tags=["research"]
)
```

3. **When you discover a new pattern, insight or knowledge**
```
save_learning(
  title="User prefers concise SQL queries",
  learning="Use CTEs instead of nested subqueries for readability",
  context="Discovered while helping with data queries",
  tags=["insight"]
)
```

4. **After fixing an error** - Save what went wrong and the fix
```
save_learning(
  title="DuckDB: avoid PRIMARY KEY constraint errors",
  learning="Use INTEGER PRIMARY KEY AUTOINCREMENT or generate IDs with (SELECT COALESCE(MAX(id), 0) + 1 FROM table)",
  context="Got constraint violation when inserting without explicit ID",
  tags=["error", "duckdb"]
)
```

## Workflow: Capturing a note

1. `search_learnings("notes schema")` - Check if table exists
2. If no schema found -> CREATE TABLE -> `save_learning` with schema
3. INSERT the note into DuckDB
4. Confirm: "Saved your note"

Do NOT call save_learning with the note content. The note goes in DuckDB.

## Research Tools (when available)

- `web_search_exa` - General web search
- `company_research_exa` - Company info
- `people_search_exa` - Find people online
- `get_code_context_exa` - Code examples, docs
- `crawling_exa` - Read a specific URL

## Personality

- Warm but efficient
- Quick to capture
- Confirms what was saved and where
- Learns from mistakes and doesn't repeat them\
"""

# ============================================================================
# Create Agent
# ============================================================================
pal_agent = Agent(
    id="pal-agent",
    name="Pal",
    model=OpenAIResponses(id="gpt-5.2"),
    db=demo_db,
    instructions=instructions,
    # Knowledge base for learnings
    knowledge=pal_knowledge,
    search_knowledge=True,
    # Learning system
    learning=LearningMachine(
        knowledge=pal_knowledge,
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    # Callable tools - per-user DuckDB isolation
    tools=get_user_tools,
    # Context
    add_datetime_to_context=True,
    add_history_to_context=True,
    read_chat_history=True,
    num_history_runs=5,
    markdown=True,
)


# ============================================================================
# Demo Tests
# ============================================================================
if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("Pal - Personal Agent that Learns")
    print("   Your AI-powered second brain")
    print("=" * 60)

    if len(sys.argv) > 1:
        # Run with command line argument
        message = " ".join(sys.argv[1:])
        pal_agent.print_response(message, user_id="demo_user", stream=True)
    else:
        # Run demo tests
        print("\n--- Demo 1: Introduction ---")
        pal_agent.print_response(
            "Tell me about yourself",
            user_id="demo_user",
            stream=True,
        )

        print("\n--- Demo 2: Create a note ---")
        pal_agent.print_response(
            "Note: Today I decided to use PostgreSQL instead of MySQL for the new project",
            user_id="demo_user",
            stream=True,
        )

        print("\n--- Demo 3: Query notes ---")
        pal_agent.print_response(
            "What notes do I have?",
            user_id="demo_user",
            stream=True,
        )
