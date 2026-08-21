"""
Context Compaction
==================
Automatic history compression for long-running agents.

When conversation history exceeds limits, older messages are summarized into a
checkpoint while recent messages stay intact. The agent sees a compressed view
but full history is preserved in the database.

Use case: A research agent that does many web searches. Each search returns
large results. After a few questions, history exceeds context limits. Compaction
summarizes findings while discarding raw search results no longer needed.

See also: context_compaction_custom.py for custom summarization prompts.
"""

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    name="Research Assistant",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=[
        "You help users research topics.",
        "Search the web when asked, synthesize findings.",
        "Be concise but thorough.",
    ],
    tools=[DuckDuckGoTools()],
    db=SqliteDb(db_file="tmp/research_assistant.db"),
    add_history_to_context=True,
    # Context compaction with minimal config
    compaction_manager=CompactionManager(
        model=OpenAIResponses(id="gpt-5-mini"),
        compact_context=True,
        compact_context_token_limit=50_000,
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    session_id = "ai-research"

    # Turn 1: Initial research
    print("\n" + "=" * 60)
    print("TURN 1: Initial research")
    print("=" * 60 + "\n")

    agent.print_response(
        "Search for the latest developments in AI agents and agentic frameworks.",
        session_id=session_id,
        stream=True,
    )

    # Turn 2: Follow-up
    print("\n" + "=" * 60)
    print("TURN 2: Deeper dive")
    print("=" * 60 + "\n")

    agent.print_response(
        "Now search for pricing and licensing of the top AI agent frameworks.",
        session_id=session_id,
        stream=True,
    )

    # Turn 3: Synthesize
    print("\n" + "=" * 60)
    print("TURN 3: Synthesis (may trigger compaction)")
    print("=" * 60 + "\n")

    response = agent.run(
        "Based on your research, write a brief comparison of the top 3 frameworks.",
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
