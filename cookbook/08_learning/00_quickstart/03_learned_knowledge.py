"""
Learning Machines: Learned Knowledge
====================================
Learned Knowledge stores insights that transfer across users.
One person teaches the agent something. Another person benefits.

In AGENTIC mode, the agent receives tools to:
- search_learnings: Find relevant past knowledge
- save_learning: Store a new insight

The agent decides when to save and apply learnings.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses
from agno.vectordb.chroma import ChromaDb, SearchType

# ---------------------------------------------------------------------------
# Create Knowledge and Agent
# ---------------------------------------------------------------------------
db = SqliteDb(db_file="tmp/agents.db")

knowledge = Knowledge(
    name="Agent Learnings",
    vector_db=ChromaDb(
        name="learnings",
        path="tmp/chromadb",
        persistent_client=True,
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    learning=LearningMachine(
        knowledge=knowledge,
        learned_knowledge=LearnedKnowledgeConfig(mode=LearningMode.AGENTIC),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Session 1: User 1 teaches the agent
    print("\n--- Session 1: User 1 saves a learning ---\n")
    agent.print_response(
        "We're trying to reduce our cloud egress costs. Remember this.",
        user_id="engineer_1@example.com",
        session_id="session_1",
        stream=True,
    )
    lm = agent.learning_machine
    lm.learned_knowledge_store.print(query="cloud")

    # Session 2: User 2 benefits from the learning
    print("\n--- Session 2: User 2 asks a related question ---\n")
    agent.print_response(
        "I'm picking a cloud provider for a data pipeline. Give me 2 key considerations.",
        user_id="engineer_2@example.com",
        session_id="session_2",
        stream=True,
    )
