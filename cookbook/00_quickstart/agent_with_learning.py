"""
Agent with Learning - Research That Improves Across Users
=========================================================
This example gives an agent learned knowledge: reusable insights that become
available to future users and sessions.

Unlike memory, which stores facts about one user, learned knowledge captures
general lessons that can improve the agent's work for everyone.

Key concepts:
- LearningMachine: Coordinates what the agent learns and recalls
- LearnedKnowledgeConfig: Enables a shared store for reusable insights
- AGENTIC mode: The agent decides when to save and search for a learning

Example prompts to try:
- "Remember this research rule: separate cyclical demand from structural demand"
- "What should I watch when comparing NVDA and AMD?"
- "What have you learned about semiconductor research?"
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.google import GeminiEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.google import Gemini
from agno.tools.yfinance import YFinanceTools
from agno.vectordb.chroma import ChromaDb
from agno.vectordb.search import SearchType

# ---------------------------------------------------------------------------
# Learning Storage
# ---------------------------------------------------------------------------
learning_db = SqliteDb(
    id="quickstart-learning-db",
    db_file="tmp/quickstart/learning.db",
)

learned_knowledge = Knowledge(
    name="Quickstart Learnings",
    vector_db=ChromaDb(
        name="quickstart_learnings",
        collection="quickstart_learnings",
        path="tmp/quickstart/learning",
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=GeminiEmbedder(id="gemini-embedding-001"),
    ),
)

# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a market research partner that improves as people use you.

- Search learned knowledge before doing company or sector analysis.
- Save a learning when a user explicitly asks you to remember a reusable rule.
- A good learning is general, durable, and useful beyond one company or date.
- Never save transient prices, personal data, or unsupported claims.
- Use fresh Yahoo Finance data for facts that can change.\
"""

# ---------------------------------------------------------------------------
# Create the Agent
# ---------------------------------------------------------------------------
agent_with_learning = Agent(
    name="Agent with Learning",
    model=Gemini(id="gemini-3.6-flash"),
    instructions=instructions,
    tools=[
        YFinanceTools(
            enable_company_info=True,
            enable_stock_fundamentals=True,
        )
    ],
    db=learning_db,
    learning=LearningMachine(
        knowledge=learned_knowledge,
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run the Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # One user teaches the agent a durable research rule.
    agent_with_learning.print_response(
        "Remember this research rule: when comparing semiconductor companies, "
        "separate cyclical inventory changes from structural demand.",
        user_id="analyst@example.com",
        session_id="teaching-session",
        stream=True,
    )

    # Inspect the artifact the first run created.
    learning_machine = agent_with_learning.learning_machine
    learning_machine.learned_knowledge_store.print(query="semiconductor demand")

    # A different user benefits from the shared learning.
    agent_with_learning.print_response(
        "What should I watch when comparing NVDA and AMD?",
        user_id="founder@example.com",
        session_id="research-session",
        stream=True,
    )

# ---------------------------------------------------------------------------
# More Examples
# ---------------------------------------------------------------------------
"""
Memory vs learned knowledge:

- Memory: "This user prefers concise answers."
- Learned knowledge: "Separate cyclical demand from structural demand."

Use learned knowledge for:
- Research methods and reusable heuristics
- Lessons discovered while completing work
- Team-wide conventions
- Insights that should transfer across users

For user profiles, entity memory, decision logs, and custom learning stores,
continue with cookbook/08_learning.
"""
