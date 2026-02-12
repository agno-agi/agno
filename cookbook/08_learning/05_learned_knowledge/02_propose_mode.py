"""
Learned Knowledge: Propose Mode (Deep Dive)
===========================================
Agent proposes learnings, user confirms before saving.

PROPOSE mode adds human quality control:
1. Agent identifies valuable insights
2. Agent proposes them to the user
3. User confirms before saving

Use when quality matters more than speed.

Compare with: 01_agentic_mode.py for automatic saving.
See also: 01_basics/4_learned_knowledge.py for the basics.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearnedKnowledgeConfig, LearningMachine, LearningMode
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)

knowledge = Knowledge(
    vector_db=PgVector(
        db_url=db_url,
        table_name="propose_learnings",
        search_type=SearchType.hybrid,
        embedder=OpenAIEmbedder(id="text-embedding-3-small"),
    ),
)

agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    db=db,
    instructions=(
        "When you discover a valuable insight, propose saving it. "
        "Wait for user confirmation before using save_learning."
    ),
    learning=LearningMachine(
        knowledge=knowledge,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.PROPOSE,
        ),
    ),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "propose@example.com"
    session_id = "propose_session"

    # User shares experience
    print("\n" + "=" * 60)
    print("MESSAGE 1: User shares experience")
    print("=" * 60 + "\n")

    agent.print_response(
        "I just spent 2 hours debugging why my Docker container couldn't "
        "connect to localhost. Turns out you need to use host.docker.internal "
        "on Mac to access the host machine from inside a container.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    # Agent should propose saving this

    # User confirms
    print("\n" + "=" * 60)
    print("MESSAGE 2: User confirms")
    print("=" * 60 + "\n")

    agent.print_response(
        "Yes, please save that. It would be helpful.",
        user_id=user_id,
        session_id=session_id,
        stream=True,
    )
    agent.learning_machine.learned_knowledge_store.print(query="docker localhost")

    # Rejection example
    print("\n" + "=" * 60)
    print("MESSAGE 3: User shares, then rejects")
    print("=" * 60 + "\n")

    agent.print_response(
        "I fixed my bug by restarting my computer.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )

    agent.print_response(
        "No, don't save that. It's not generally useful.",
        user_id=user_id,
        session_id="session_2",
        stream=True,
    )
    agent.learning_machine.learned_knowledge_store.print(query="restart")
