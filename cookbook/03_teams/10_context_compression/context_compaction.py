"""
Team Context Compaction
=======================
Automatic history compression for long-running teams.

Teams with web search or research tools accumulate large results quickly.
Context compaction summarizes older exchanges while keeping recent findings
intact, enabling multi-hour research sessions without hitting context limits.

This differs from tool_call_compression.py which compresses individual tool
results. Context compaction compresses the entire conversation history.

See also: context_compaction_custom.py (in agents) for custom instructions.
"""

import asyncio
from textwrap import dedent

from agno.agent import Agent
from agno.compression import CompactionManager
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.team import Team
from agno.tools.duckduckgo import DuckDuckGoTools

# ---------------------------------------------------------------------------
# Create Members
# ---------------------------------------------------------------------------

researcher = Agent(
    name="Researcher",
    role="Technology Researcher",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=dedent("""
        You specialize in technology and AI research.
        - Focus on latest developments, trends, and breakthroughs
        - Provide concise, data-driven insights
        - Cite your sources
    """).strip(),
)

analyst = Agent(
    name="Analyst",
    role="Business Analyst",
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=dedent("""
        You specialize in business and market analysis.
        - Focus on companies, markets, and economic trends
        - Provide actionable business insights
        - Include relevant data and statistics
    """).strip(),
)

# ---------------------------------------------------------------------------
# Create Team
# ---------------------------------------------------------------------------

db = SqliteDb(db_file="tmp/research_team_compaction.db")

research_team = Team(
    name="Research Team",
    model=OpenAIResponses(id="gpt-5.5"),
    members=[researcher, analyst],
    tools=[DuckDuckGoTools()],
    description="Research team that investigates topics comprehensively.",
    instructions=dedent("""
        You are a research coordinator.

        Process:
        1. Search for information on the topic
        2. Delegate analysis to the appropriate specialist
        3. Synthesize findings into a comprehensive response

        Guidelines:
        - Start with web research
        - Choose the right specialist (tech vs business)
        - Provide well-sourced responses
    """).strip(),
    db=db,
    add_history_to_context=True,
    # Context compaction with minimal config
    compaction_manager=CompactionManager(
        compact_context=True,
        model=OpenAIResponses(id="gpt-5-mini"),
        compact_context_token_limit=60_000,
    ),
    markdown=True,
    show_members_responses=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------


async def run_research_session():
    session_id = "market-research"

    # Turn 1: Initial research
    print("\n" + "=" * 60)
    print("TURN 1: Initial landscape")
    print("=" * 60 + "\n")

    await research_team.aprint_response(
        "Map the agentic AI framework landscape. Who are the main players?",
        session_id=session_id,
        stream=True,
    )

    # Turn 2: Deep dive
    print("\n" + "=" * 60)
    print("TURN 2: Pricing analysis")
    print("=" * 60 + "\n")

    await research_team.aprint_response(
        "Compare pricing and licensing for the top three frameworks.",
        session_id=session_id,
        stream=True,
    )

    # Turn 3: Final synthesis (may trigger compaction)
    print("\n" + "=" * 60)
    print("TURN 3: Final brief (may trigger compaction)")
    print("=" * 60 + "\n")

    response = await research_team.arun(
        "Write a final comparison brief with your recommendations.",
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
    asyncio.run(run_research_session())
