"""
Research Agent
===========================================
A research assistant that learns research patterns over time.

Key Features:
- Web search for current information
- Financial data tools for market research
- PROPOSE mode for learnings (quality over quantity)
- User preferences for personalized research style

The agent learns patterns like:
- "For SaaS comparisons, check ARR growth, NRR, and CAC payback"
- "When researching AI companies, look at compute costs and model efficiency"
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge.agent import AgentKnowledge
from agno.learn import (
    LearningMachine,
    LearningMode,
    LearnedKnowledgeConfig,
    SessionContextConfig,
    UserProfileConfig,
)
from agno.models.openai import OpenAIChat
from agno.tools.duckduckgo import DuckDuckGoTools
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.pgvector import PgVector

# =============================================================================
# Setup
# =============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = AgentKnowledge(
    vector_db=PgVector(db_url=db_url, table_name="research_learnings"),
)

# =============================================================================
# Research Agent Instructions
# =============================================================================
INSTRUCTIONS = """\
You are a Research Agent that learns and improves over time.

## Research Process

1. **Check Prior Knowledge**
   - Call `search_learnings` for relevant research patterns
   - Apply insights that worked before

2. **Gather Information**
   - Use web search for current events and general info
   - Use financial tools for market data
   - Cross-reference multiple sources

3. **Synthesize**
   - Combine learnings with fresh research
   - Be specific and cite your reasoning

4. **Reflect**
   - Did this reveal a reusable research pattern?
   - If so, propose saving it (PROPOSE mode)

## Proposing Learnings

When you discover a valuable research pattern, propose it:

---
**💡 Proposed Learning**

**Title:** [e.g., "SaaS Company Evaluation Framework"]
**Learning:** [The specific pattern or methodology]
**Context:** [When to apply this]

Save this learning? (yes/no)
---

Only call `save_learning` after user confirms with "yes".
"""

# =============================================================================
# Create Research Agent
# =============================================================================
research_agent = Agent(
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    instructions=INSTRUCTIONS,
    db=db,
    tools=[
        DuckDuckGoTools(),
        YFinanceTools(
            stock_price=True,
            company_info=True,
            analyst_recommendations=True,
            stock_fundamentals=True,
        ),
    ],
    learning=LearningMachine(
        db=db,
        model=OpenAIChat(id="gpt-4o"),
        knowledge=knowledge,
        user_profile=UserProfileConfig(
            mode=LearningMode.BACKGROUND,
            instructions="Focus on: investment style, sectors of interest, risk tolerance",
        ),
        session_context=SessionContextConfig(
            enable_planning=False,
        ),
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,  # Human validates research patterns
        ),
    ),
    markdown=True,
)


# =============================================================================
# Demo
# =============================================================================
if __name__ == "__main__":
    user_id = "researcher@example.com"

    # --- Research Query 1: Discover a pattern ---
    print("=" * 60)
    print("Research Query 1: Compare AI chip companies")
    print("=" * 60)
    research_agent.print_response(
        "Compare NVIDIA and AMD as AI chip investments. "
        "What metrics should I focus on?",
        user_id=user_id,
        session_id="research_1",
        stream=True,
    )

    # --- User confirms the learning ---
    print("\n--- User confirms ---\n")
    research_agent.print_response(
        "yes",
        user_id=user_id,
        session_id="research_1",
        stream=True,
    )

    # --- Research Query 2: Apply the learning ---
    print("\n" + "=" * 60)
    print("Research Query 2: Related query uses prior learning")
    print("=" * 60)
    research_agent.print_response(
        "What about Intel as an AI play? How does it compare?",
        user_id=user_id,
        session_id="research_2",
        stream=True,
    )

    # --- Different User: Benefits from learnings ---
    print("\n" + "=" * 60)
    print("Different User: Benefits from accumulated learnings")
    print("=" * 60)
    research_agent.print_response(
        "I'm new to semiconductor investing. How should I evaluate "
        "companies in the AI chip space?",
        user_id="newbie@example.com",
        session_id="research_3",
        stream=True,
    )

    # --- Show accumulated learnings ---
    print("\n" + "=" * 60)
    print("Accumulated Research Learnings")
    print("=" * 60)
    results = research_agent.learning.stores["learned_knowledge"].search(
        query="investment evaluation methodology",
        limit=5,
    )
    if results:
        print("\n📚 Research patterns learned:")
        for r in results:
            title = getattr(r, 'title', 'Untitled')
            learning = getattr(r, 'learning', str(r))[:80]
            print(f"   > {title}")
            print(f"     {learning}...")
    else:
        print("\n📚 No research patterns learned yet")
