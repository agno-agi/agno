"""
Context Compaction with File Reading
====================================
Demonstrates context compaction triggered by reading source files.

Reading multiple files quickly fills the context window. This example reads
Agno source files to explore the codebase, triggering compaction when the
token limit is exceeded.

The agent summarizes findings while discarding raw file contents, keeping
the conversation within limits while preserving key insights.
"""

from pathlib import Path

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.file import FileTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

# Point FileTools at the agno source directory (relative to cookbook location)
# cookbook/02_agents/14_advanced/ -> libs/agno/agno requires going up 4 levels
cookbook_dir = Path(__file__).resolve().parent
agno_source = cookbook_dir.parents[2] / "libs" / "agno" / "agno"

agent = Agent(
    name="Codebase Explorer",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You help developers understand the Agno codebase.",
        "Read files when asked, explain architecture and patterns.",
        "Keep explanations brief - 2-3 paragraphs max.",
    ],
    tools=[FileTools(base_dir=agno_source, enable_save_file=False)],
    db=SqliteDb(db_file="tmp/codebase_explorer.db"),
    add_history_to_context=True,
    # Low token limit to trigger compaction quickly with file reads
    compaction_manager=CompactionManager(
        compact_history=True,
        model=OpenAIResponses(id="gpt-5-mini"),
        token_limit=20_000,  # Low limit - 2-3 file reads will trigger
        keep_recent=6,
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    session_id = "agno-exploration"

    # Turn 1: Read a file
    print("\n" + "=" * 60)
    print("TURN 1: Read compression/context.py")
    print("=" * 60 + "\n")

    agent.print_response(
        "Read compression/context.py and explain what CompactionManager does.",
        session_id=session_id,
        stream=True,
    )

    # Turn 2: Read another file
    print("\n" + "=" * 60)
    print("TURN 2: Read agent/agent.py (should trigger compaction)")
    print("=" * 60 + "\n")

    agent.print_response(
        "Now read agent/agent.py and find where compaction_manager is wired up.",
        session_id=session_id,
        stream=True,
    )

    # Turn 3: Synthesize (compaction already happened)
    print("\n" + "=" * 60)
    print("TURN 3: Synthesize findings")
    print("=" * 60 + "\n")

    response = agent.run(
        "Based on what you learned, explain how context compaction flows through the agent.",
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
