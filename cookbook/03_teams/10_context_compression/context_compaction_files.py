"""
Team Context Compaction with File Reading
=========================================
Demonstrates team context compaction triggered by reading source files.

A code review team with specialized agents reads multiple files to analyze
architecture. File contents quickly fill the context, triggering compaction.

The team summarizes findings while discarding raw file contents, keeping
the conversation within limits while preserving architectural insights.
"""

import asyncio
from pathlib import Path
from textwrap import dedent

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Create Members (different OpenAI models for variety)
# ---------------------------------------------------------------------------

architect = Agent(
    name="Architect",
    role="Software Architect",
    model=OpenAIResponses(id="o3-mini"),  # Reasoning model for architecture
    instructions=dedent("""
        You analyze software architecture and design patterns.
        - Identify architectural decisions and their rationale
        - Spot design patterns and anti-patterns
        - Keep analysis brief and actionable
    """).strip(),
)

reviewer = Agent(
    name="Reviewer",
    role="Code Reviewer",
    model=OpenAIResponses(id="gpt-5-mini"),  # Fast model for code review
    instructions=dedent("""
        You review code for quality and maintainability.
        - Focus on code organization and clarity
        - Identify potential issues or improvements
        - Keep feedback concise
    """).strip(),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

# Point FileTools at the agno source directory
cookbook_dir = Path(__file__).resolve().parent
agno_source = cookbook_dir.parents[2] / "libs" / "agno" / "agno"

db = SqliteDb(db_file="tmp/code_review_team.db")

review_team = Team(
    name="Code Review Team",
    mode="coordinate",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[architect, reviewer],
    tools=[FileTools(base_dir=agno_source, enable_save_file=False)],
    description="Code review team that analyzes architecture and code quality.",
    instructions=dedent("""
        You coordinate code reviews.

        Process:
        1. Read requested files to understand the code
        2. Delegate to Architect for design analysis
        3. Delegate to Reviewer for code quality feedback
        4. Synthesize findings

        Keep all responses brief - 2-3 paragraphs max.
    """).strip(),
    db=db,
    add_history_to_context=True,
    # Low token limit to trigger compaction with file reads
    compaction_manager=CompactionManager(
        compact_context=True,
        model=OpenAIResponses(id="gpt-5-mini"),
        compact_context_token_limit=25_000,  # Low limit - file reads trigger quickly
        compact_context_keep_recent=8,
    ),
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------


async def run_code_review():
    session_id = "knowledge-review"

    # Turn 1: Read knowledge base
    print("\n" + "=" * 60)
    print("TURN 1: Review knowledge/knowledge.py")
    print("=" * 60 + "\n")

    await review_team.aprint_response(
        "Read knowledge/knowledge.py and analyze the Knowledge class design.",
        session_id=session_id,
        stream=True,
    )

    # Turn 2: Read document module (should trigger compaction)
    print("\n" + "=" * 60)
    print("TURN 2: Review knowledge/document (should trigger compaction)")
    print("=" * 60 + "\n")

    await review_team.aprint_response(
        "Now list and read the files in knowledge/document/ to understand document handling.",
        session_id=session_id,
        stream=True,
    )

    # Turn 3: Synthesize
    print("\n" + "=" * 60)
    print("TURN 3: Explain how knowledge works in Agno")
    print("=" * 60 + "\n")

    response = await review_team.arun(
        "Explain how knowledge works in Agno - from document loading to agent retrieval.",
        session_id=session_id,
    )
    print(response.content)

    # Show compaction stats
    print("\n" + "-" * 40)
    print("Compaction Stats")
    print("-" * 40)
    if response.compaction_state:
        print(f"  Total compactions: {response.compaction_state.total_compactions}")
        print(f"  Messages compacted: {response.compaction_state.compacted_count}")
        print(f"  Tokens saved: {response.compaction_state.total_tokens_saved}")
    else:
        print("  No compaction triggered (history within limits)")


if __name__ == "__main__":
    asyncio.run(run_code_review())
