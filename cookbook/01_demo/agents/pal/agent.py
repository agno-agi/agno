"""
Pal - Personal Agent that Learns
=================================

Your AI-powered second brain.

Pal researches, captures, organizes, connects, and retrieves your personal
knowledge - so nothing useful is ever lost.

Test:
    python -m agents.pal.agent
"""

from os import getenv
from pathlib import Path

from agno.agent import Agent
from agno.learn import (
    LearnedKnowledgeConfig,
    LearningMachine,
    LearningMode,
    UserMemoryConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIResponses
from agno.tools.duckdb import DuckDbTools
from agno.tools.mcp import MCPTools
from db import create_knowledge, get_postgres_db

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
agent_db = get_postgres_db(contents_table="pal_contents")
data_dir = Path(getenv("DATA_DIR", str(Path(__file__).parent / "data")))
data_dir.mkdir(parents=True, exist_ok=True)

duckdb_path = str(data_dir / "pal.db")

# Exa MCP for research
EXA_API_KEY = getenv("EXA_API_KEY", "")
EXA_MCP_URL = (
    f"https://mcp.exa.ai/mcp?exaApiKey={EXA_API_KEY}&tools="
    "web_search_exa,"
    "get_code_context_exa,"
    "company_research_exa,"
    "crawling_exa,"
    "people_search_exa"
)

# Knowledge base for semantic search and learnings
pal_knowledge = create_knowledge("Pal Knowledge", "pal_knowledge")

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are Pal, a personal agent that learns.

## Your Purpose

You are the user's AI-powered second brain. You research, capture, organize,
connect, and retrieve their personal knowledge - so nothing useful is ever lost.

## Two Storage Systems

**DuckDB** - User's actual data:
- notes, bookmarks, people, meetings, projects
- This is where user content goes

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
2. If no schema found: CREATE TABLE then `save_learning` with schema
3. INSERT the note into DuckDB
4. Confirm: "Saved your note"

Do NOT call save_learning with the note content. The note goes in DuckDB.

## Research Tools

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

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
pal = Agent(
    id="pal",
    name="Pal",
    model=OpenAIResponses(id="gpt-5.2"),
    db=agent_db,
    instructions=instructions,
    # Learning
    learning=LearningMachine(
        knowledge=pal_knowledge,
        user_profile=UserProfileConfig(mode=LearningMode.AGENTIC),
        user_memory=UserMemoryConfig(mode=LearningMode.AGENTIC),
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    # Tools
    tools=[
        MCPTools(url=EXA_MCP_URL),
        DuckDbTools(db_path=duckdb_path),
    ],
    # Context
    add_datetime_to_context=True,
    add_history_to_context=True,
    read_chat_history=True,
    num_history_runs=5,
    markdown=True,
)

if __name__ == "__main__":
    test_cases = [
        "Tell me about yourself",
        "Note: We decided to use PostgreSQL for the new analytics service",
    ]
    for idx, prompt in enumerate(test_cases, start=1):
        print(f"\n--- Pal test case {idx}/{len(test_cases)} ---")
        print(f"Prompt: {prompt}")
        pal.print_response(prompt, stream=True)
