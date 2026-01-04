"""
Learned Knowledge: Namespace Scoping
====================================
Controlling who can see learnings.

Namespace determines the sharing boundary for learnings:

- "global" (default): Shared with everyone
  - Good for: Company-wide best practices

- "user": Private per user
  - Good for: Personal notes, individual learnings

- Custom string: Team or project isolation
  - Good for: Department-specific knowledge

Run:
    python cookbook/15_learning/learned_knowledge/05_namespace_scoping.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.knowledge import Knowledge
from agno.knowledge.embedder.openai import OpenAIEmbedder
from agno.learn import LearningMachine, LearnedKnowledgeConfig, LearningMode
from agno.models.openai import OpenAIResponses
from agno.vectordb.pgvector import PgVector, SearchType

# ============================================================================
# Setup
# ============================================================================
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url)
model = OpenAIResponses(id="gpt-5.2")


# ============================================================================
# Helper: Create Knowledge Base
# ============================================================================
def create_knowledge(table_name: str) -> Knowledge:
    return Knowledge(
        vector_db=PgVector(
            db_url=db_url,
            table_name=table_name,
            search_type=SearchType.hybrid,
            embedder=OpenAIEmbedder(id="text-embedding-3-small"),
        ),
    )


# ============================================================================
# Global Agent (Default)
# ============================================================================
global_knowledge = create_knowledge("global_learnings")

global_agent = Agent(
    name="Global Learning Agent",
    model=model,
    db=db,
    instructions="You help the entire company. Learnings are shared globally.",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=global_knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="global",  # Default: shared with everyone
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Private Agent (Per User)
# ============================================================================
private_knowledge = create_knowledge("private_learnings")

private_agent = Agent(
    name="Private Learning Agent",
    model=model,
    db=db,
    instructions="You help individual users. Learnings are private to each user.",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=private_knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="user",  # Private per user
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Team Agents (Custom Namespaces)
# ============================================================================
team_knowledge = create_knowledge("team_learnings")

engineering_agent = Agent(
    name="Engineering Agent",
    model=model,
    db=db,
    instructions="You help the engineering team. Learnings are shared within engineering.",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=team_knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="engineering",  # Engineering team only
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)

sales_agent = Agent(
    name="Sales Agent",
    model=model,
    db=db,
    instructions="You help the sales team. Learnings are shared within sales.",
    learning=LearningMachine(
        db=db,
        model=model,
        knowledge=team_knowledge,
        user_profile=False,
        learned_knowledge=LearnedKnowledgeConfig(
            mode=LearningMode.AGENTIC,
            namespace="sales",  # Sales team only
            enable_agent_tools=True,
        ),
    ),
    markdown=True,
)


# ============================================================================
# Demo: Global Sharing
# ============================================================================
def demo_global():
    """Show global namespace - visible to everyone."""
    print("=" * 60)
    print("Demo: Global Namespace")
    print("=" * 60)

    # User A saves a learning
    print("\n--- User A saves a learning ---\n")
    global_agent.print_response(
        "Save this: Always validate input at API boundaries, not deep in business logic.",
        user_id="user_a@company.com",
        session_id="global_a",
        stream=True,
    )

    # User B can access it
    print("\n--- User B searches learnings ---\n")
    global_agent.print_response(
        "What do we know about input validation?",
        user_id="user_b@company.com",
        session_id="global_b",
        stream=True,
    )

    print("\n💡 Global namespace: All users share the same learnings")


# ============================================================================
# Demo: Private Namespace
# ============================================================================
def demo_private():
    """Show user namespace - private to each user."""
    print("\n" + "=" * 60)
    print("Demo: User Namespace (Private)")
    print("=" * 60)

    # Alice saves private learning
    print("\n--- Alice saves private learning ---\n")
    private_agent.print_response(
        "Save this for me: My personal debugging technique - always check "
        "the logs first, then network, then database.",
        user_id="alice@company.com",
        session_id="private_alice",
        stream=True,
    )

    # Bob cannot see Alice's learning
    print("\n--- Bob searches (can't see Alice's) ---\n")
    private_agent.print_response(
        "What debugging techniques do we know?",
        user_id="bob@company.com",
        session_id="private_bob",
        stream=True,
    )

    # Alice can see her own
    print("\n--- Alice searches (sees her own) ---\n")
    private_agent.print_response(
        "What debugging techniques do I have saved?",
        user_id="alice@company.com",
        session_id="private_alice_2",
        stream=True,
    )

    print("\n💡 User namespace: Each user has private learnings")


# ============================================================================
# Demo: Team Namespaces
# ============================================================================
def demo_teams():
    """Show team namespaces - isolated by department."""
    print("\n" + "=" * 60)
    print("Demo: Team Namespaces")
    print("=" * 60)

    # Engineering saves a learning
    print("\n--- Engineering saves a learning ---\n")
    engineering_agent.print_response(
        "Save this: For microservices, use Kubernetes readiness probes with "
        "actual dependency checks, not just HTTP 200.",
        user_id="eng1@company.com",
        session_id="eng_1",
        stream=True,
    )

    # Sales saves a learning
    print("\n--- Sales saves a learning ---\n")
    sales_agent.print_response(
        "Save this: When demoing to enterprise clients, always start with "
        "the security and compliance features.",
        user_id="sales1@company.com",
        session_id="sales_1",
        stream=True,
    )

    # Engineering can see engineering learnings
    print("\n--- Engineering searches (sees their learnings) ---\n")
    engineering_agent.print_response(
        "What Kubernetes best practices do we have?",
        user_id="eng2@company.com",
        session_id="eng_2",
        stream=True,
    )

    # Sales cannot see engineering learnings
    print("\n--- Sales searches engineering topic (sees nothing) ---\n")
    sales_agent.print_response(
        "What Kubernetes best practices do we have?",
        user_id="sales2@company.com",
        session_id="sales_2",
        stream=True,
    )

    # Sales can see sales learnings
    print("\n--- Sales searches demo techniques (sees their learnings) ---\n")
    sales_agent.print_response(
        "What demo best practices do we have?",
        user_id="sales2@company.com",
        session_id="sales_3",
        stream=True,
    )

    print("\n💡 Team namespaces: Data isolated by department")


# ============================================================================
# Main
# ============================================================================
if __name__ == "__main__":
    demo_global()
    demo_private()
    demo_teams()

    print("\n" + "=" * 60)
    print("✅ Namespace scoping controls visibility")
    print('   "global" = shared with everyone')
    print('   "user" = private per user')
    print('   custom = team/department isolation')
    print("=" * 60)
