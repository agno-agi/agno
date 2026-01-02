"""
Self-Learning Research Agent
=============================
A research agent that learns and improves over time.

This agent demonstrates:
- User preferences remembered across sessions
- Session context for research continuity
- PROPOSE mode for learnings (agent proposes, user confirms)
- Web search and financial data tools
- Prior learnings recalled via semantic search

Run this example:
    python cookbook/learning/02_research_agent.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearningsConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.pgvector import PgVector, SearchType

# =============================================================================
# Configuration
# =============================================================================

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

# Knowledge base for learned research patterns
research_kb = Knowledge(
    name="Research Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="research_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

model = OpenAIChat(id="gpt-4o")

# =============================================================================
# Agent Instructions
# =============================================================================

INSTRUCTIONS = """\
You are a Self-Learning Research Agent that improves over time.

## Your Capabilities

1. **Web Search**: Find current information on any topic
2. **Financial Data**: Stock prices, company financials, analyst recommendations
3. **Memory**: Remember user preferences across sessions
4. **Learning**: Save and apply reusable research patterns

## Research Process

For each query:

1. **Check Prior Knowledge**
   - Call `search_learnings` for relevant patterns
   - Apply insights that worked before

2. **Gather Information**
   - Use web search for current events and general info
   - Use financial tools for market data
   - Cross-reference multiple sources

3. **Synthesize Answer**
   - Combine learnings with fresh research
   - Be specific and cite your reasoning

4. **Reflect**
   - Did this reveal a reusable pattern?
   - If so, propose saving it (see below)

## What Makes a Good Learning

Save insights that are:
- **Specific**: "For SaaS comparisons, check: ARR growth, NRR, CAC payback"
- **Actionable**: Can be applied to similar future queries
- **Validated**: Based on what actually worked

Don't save: Raw facts, one-off answers, speculation.

## Proposing Learnings (PROPOSE Mode)

When you discover something worth saving, format it like this:

---
**💡 Proposed Learning**

**Title**: [concise name]
**Learning**: [the specific insight]
**Context**: [when to apply this]
**Tags**: [relevant tags]

Would you like me to save this? Reply **yes** to confirm.

---

Only call `save_learning` after user confirms with "yes".
This ensures we only save high-quality, validated insights.
"""

# =============================================================================
# Create the Agent
# =============================================================================

research_agent = Agent(
    name="Self-Learning Research Agent",
    model=model,
    instructions=INSTRUCTIONS,
    db=db,
    # Research tools
    tools=[
        DuckDuckGoTools(),
        YFinanceTools(
            stock_price=True,
            company_info=True,
            analyst_recommendations=True,
            stock_fundamentals=True,
        ),
    ],
    # Full learning configuration
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=research_kb,
        # User Profile: Remember preferences, BACKGROUND extraction
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_tool=True,  # Agent can also save via tool
        ),
        # Session Context: Track research state (summary only, no planning)
        session_context=SessionContextConfig(
            enable_planning=False,
        ),
        # Learnings: PROPOSE mode — agent proposes, user confirms
        learnings=LearningsConfig(
            mode=LearningMode.PROPOSE,
            enable_tool=True,
            enable_search=True,
        ),
    ),
    # Context settings
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)


# =============================================================================
# Demo Functions
# =============================================================================


def demo_research_with_learning():
    """Demonstrate research that produces learnings."""
    print("=" * 60)
    print("Demo: Research with Learning")
    print("=" * 60)

    user_id = "researcher@example.com"

    # Query that should produce a learning
    print("\n--- Research Query ---")
    research_agent.print_response(
        "Compare NVIDIA and AMD as AI chip investments. "
        "What metrics should I focus on?",
        user_id=user_id,
        stream=True,
    )

    # User confirms saving
    print("\n--- User confirms (simulated) ---")
    research_agent.print_response(
        "yes",
        user_id=user_id,
        stream=True,
    )


def demo_recall_learning():
    """Show how prior learnings are recalled."""
    print("\n" + "=" * 60)
    print("Demo: Recall Prior Learning")
    print("=" * 60)

    user_id = "researcher@example.com"

    # Related query — should recall the chip investment learning
    print("\n--- Related Query (should recall) ---")
    research_agent.print_response(
        "I'm also looking at Intel. How should I evaluate it as an AI play?",
        user_id=user_id,
        stream=True,
    )


def demo_user_preferences():
    """Show how user preferences are remembered."""
    print("\n" + "=" * 60)
    print("Demo: User Preferences")
    print("=" * 60)

    user_id = "investor@example.com"

    # First interaction — establish preferences
    print("\n--- First Interaction ---")
    research_agent.print_response(
        "Hi! I'm a value investor focused on dividend stocks. "
        "I prefer detailed analysis with specific numbers.",
        user_id=user_id,
        stream=True,
    )

    # Second interaction — agent should adapt to preferences
    print("\n--- Second Interaction (personalized) ---")
    research_agent.print_response(
        "What do you think about Johnson & Johnson?",
        user_id=user_id,
        stream=True,
    )


def demo_financial_research():
    """Show financial tools in action."""
    print("\n" + "=" * 60)
    print("Demo: Financial Research")
    print("=" * 60)

    user_id = "trader@example.com"

    print("\n--- Financial Query ---")
    research_agent.print_response(
        "Give me a quick analysis of Apple stock. "
        "Include current price, recent performance, and analyst sentiment.",
        user_id=user_id,
        stream=True,
    )


def demo_web_research():
    """Show web search for current events."""
    print("\n" + "=" * 60)
    print("Demo: Web Research")
    print("=" * 60)

    user_id = "analyst@example.com"

    print("\n--- Current Events Query ---")
    research_agent.print_response(
        "What are the latest developments in AI regulation? Focus on the US and EU.",
        user_id=user_id,
        stream=True,
    )


# =============================================================================
# Interactive CLI
# =============================================================================


def interactive():
    """Run the interactive research agent."""
    print("=" * 60)
    print("🔬 Self-Learning Research Agent")
    print("=" * 60)
    print("\nI learn from our conversations and apply insights to future queries.")
    print("When I discover a valuable pattern, I'll propose saving it.")
    print("Reply 'yes' to confirm saving a learning.\n")
    print("Commands:")
    print("  'quit'  — Exit")
    print("  'debug' — Show learning state")
    print("  'clear' — Start new session\n")

    user_id = "researcher"
    session_id = "research_session_001"

    while True:
        try:
            user_input = input("You: ").strip()

            if user_input.lower() in ("quit", "exit", "q"):
                print("\n👋 Goodbye! I'll remember our research.")
                break

            if user_input.lower() == "debug":
                learning = research_agent.learning
                print(f"\n📊 Learning state: {learning}")
                for name, store in learning.stores.items():
                    print(f"   {name}: {store}")
                print()
                continue

            if user_input.lower() == "clear":
                session_id = f"research_session_{hash(user_input) % 10000:04d}"
                print(f"\n🔄 Started new session: {session_id}\n")
                continue

            if not user_input:
                continue

            print()
            research_agent.print_response(
                user_input,
                user_id=user_id,
                session_id=session_id,
                stream=True,
            )
            print()

        except KeyboardInterrupt:
            print("\n\n👋 Goodbye!")
            break


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    import sys

    demos = {
        "research": demo_research_with_learning,
        "recall": demo_recall_learning,
        "preferences": demo_user_preferences,
        "financial": demo_financial_research,
        "web": demo_web_research,
        "interactive": interactive,
    }

    if len(sys.argv) > 1:
        demo_name = sys.argv[1]
        if demo_name == "all":
            for name in ["research", "recall", "preferences", "financial", "web"]:
                demos[name]()
        elif demo_name in demos:
            demos[demo_name]()
        else:
            print(f"Unknown demo: {demo_name}")
            print(f"Available: {', '.join(demos.keys())}, all")
    else:
        print("=" * 60)
        print("🔬 Self-Learning Research Agent")
        print("=" * 60)
        print("\nAvailable demos:")
        print("  research    - Research query that produces a learning")
        print("  recall      - Query that recalls prior learning")
        print("  preferences - User preferences remembered")
        print("  financial   - Financial data tools")
        print("  web         - Web search for current events")
        print("  interactive - Chat with the agent")
        print("  all         - Run all demos (except interactive)")
        print("\nUsage: python 02_research_agent.py <demo>")
        print("\nRunning 'interactive' mode by default...\n")
        interactive()
