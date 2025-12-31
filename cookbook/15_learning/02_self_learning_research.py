"""
Self-Learning Research Agent
============================
A research agent that learns and improves over time using LearningMachine.

This agent:
1. Remembers user preferences across sessions
2. Tracks research context within sessions
3. Saves reusable insights for future queries

Run:
    python cookbook/learning/02_self_learning_research.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.knowledge.knowledge import Knowledge
from agno.learn import (
    KnowledgeConfig,
    LearningMachine,
    LearningMode,
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
research_learnings = Knowledge(
    name="Research Learnings",
    vector_db=PgVector(
        db_url=db_url,
        table_name="research_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
    contents_db=db,
)

# =============================================================================
# Agent Instructions
# =============================================================================

INSTRUCTIONS = """\
You are a Self-Learning Research Agent that improves over time.

## Your Capabilities

1. **Web Search**: Find current information on any topic
2. **Financial Data**: Get stock prices, company financials, market data
3. **Memory**: Remember user preferences and context
4. **Learning**: Save and apply reusable research patterns

## Research Process

For each query:

1. **Check Prior Knowledge**
   - Search your knowledge base for relevant learnings
   - Apply patterns that worked before

2. **Gather Information**
   - Use web search for current events and general info
   - Use financial tools for market data
   - Cross-reference multiple sources

3. **Synthesize Answer**
   - Combine learnings with fresh research
   - Be specific and cite your reasoning

4. **Reflect**
   - Did this reveal a reusable pattern?
   - If so, propose saving it

## What Makes a Good Learning

Save insights that are:
- **Specific**: "For SaaS comparisons, check: ARR growth, NRR, CAC payback"
- **Actionable**: Can be applied to similar future queries
- **Validated**: Based on what actually worked

Don't save: Raw facts, one-off answers, speculation.

## Proposing Learnings

When you discover something worth saving:

---
**Proposed Learning**

Title: [concise name]
Learning: [the specific insight]
Context: [when to apply this]
Tags: [relevant tags]

Save this? (yes/no)
---

Only save after user confirms.
"""

# =============================================================================
# Create the Agent
# =============================================================================

research_agent = Agent(
    name="Self-Learning Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=INSTRUCTIONS,
    db=db,
    # Tools for research
    tools=[
        DuckDuckGoTools(),
        YFinanceTools(
            stock_price=True,
            company_info=True,
            analyst_recommendations=True,
            stock_fundamentals=True,
        ),
    ],
    # Enable unified learning
    learning=LearningMachine(
        db=db,
        knowledge=research_learnings,
        # Remember user preferences
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            enable_tool=True,
        ),
        # Track research context in session
        session_context=SessionContextConfig(
            enable_planning=False,  # Just summaries for research
        ),
        # Save research patterns with user approval
        learned_knowledge=KnowledgeConfig(
            mode=LearningMode.PROPOSE,
            enable_tool=True,
        ),
    ),
    # Context settings
    add_datetime_to_context=True,
    add_history_to_context=True,
    num_history_runs=5,
    markdown=True,
)


# =============================================================================
# Interactive CLI
# =============================================================================


def main():
    """Run the interactive research agent."""
    print("=" * 60)
    print("🔬 Self-Learning Research Agent")
    print("   Powered by LearningMachine")
    print("=" * 60)
    print("\nI learn from our conversations and apply insights to future queries.")
    print("Type 'quit' to exit.\n")

    session_id = None
    user_id = "researcher"

    while True:
        try:
            user_input = input("You: ").strip()

            if user_input.lower() in ("quit", "exit", "q"):
                print("\n👋 Goodbye! I'll remember our conversation.")
                break

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


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Single query mode
        query = " ".join(sys.argv[1:])
        research_agent.print_response(query, user_id="cli_user", stream=True)
    else:
        # Interactive mode
        main()
