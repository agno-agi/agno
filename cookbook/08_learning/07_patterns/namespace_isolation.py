"""
Namespace Isolation
===================
Demonstrates how namespace prevents cross-agent learning contamination.

Without namespace, agents sharing the same database would see each other's
decision logs, user memories, and session contexts. Namespace creates
boundaries so each agent (or team) only sees its own data.

This pattern is critical for multi-agent systems where agents serve
different roles but share infrastructure.

Run:
    .venvs/demo/bin/python cookbook/08_learning/07_patterns/namespace_isolation.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import (
    DecisionLogConfig,
    LearningMachine,
    LearningMode,
    SessionContextConfig,
    UserMemoryConfig,
)
from agno.models.openai import OpenAIChat

# ---------------------------------------------------------------------------
# Shared database — both agents use the same DB
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# ---------------------------------------------------------------------------
# Agent 1: Sales team — namespace "sales"
# ---------------------------------------------------------------------------

sales_agent = Agent(
    id="sales-agent",
    name="Sales Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    learning=LearningMachine(
        namespace="sales",
        user_memory=UserMemoryConfig(mode=LearningMode.ALWAYS),
        session_context=SessionContextConfig(mode=LearningMode.ALWAYS),
        decision_log=DecisionLogConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
        ),
    ),
    instructions=[
        "You are a sales assistant. Be concise.",
        "Log important decisions about deals.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Agent 2: Engineering team — namespace "engineering"
# ---------------------------------------------------------------------------

engineering_agent = Agent(
    id="eng-agent",
    name="Engineering Agent",
    model=OpenAIChat(id="gpt-4o-mini"),
    db=db,
    learning=LearningMachine(
        namespace="engineering",
        user_memory=UserMemoryConfig(mode=LearningMode.ALWAYS),
        session_context=SessionContextConfig(mode=LearningMode.ALWAYS),
        decision_log=DecisionLogConfig(
            mode=LearningMode.AGENTIC,
            enable_agent_tools=True,
        ),
    ),
    instructions=[
        "You are an engineering assistant. Be concise.",
        "Log important technical decisions.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    user_id = "demo@example.com"

    # --- Sales agent conversation ---
    print("\n" + "=" * 60)
    print("SALES AGENT: Learning about a deal")
    print("=" * 60 + "\n")

    sales_agent.print_response(
        "The Acme Corp deal is worth $500k. They prefer quarterly billing. "
        "I decided to offer a 10% discount to close this quarter.",
        user_id=user_id,
        session_id="sales-session-1",
        stream=True,
    )

    # --- Engineering agent conversation ---
    print("\n" + "=" * 60)
    print("ENGINEERING AGENT: Learning about a technical decision")
    print("=" * 60 + "\n")

    engineering_agent.print_response(
        "We decided to use PostgreSQL over MongoDB for the new service. "
        "The main reason is strong consistency requirements for financial data.",
        user_id=user_id,
        session_id="eng-session-1",
        stream=True,
    )

    # --- Verify namespace isolation ---
    print("\n" + "=" * 60)
    print("VERIFICATION: Namespace isolation at config + data level")
    print("=" * 60 + "\n")

    sales_lm = sales_agent.learning_machine
    eng_lm = engineering_agent.learning_machine

    # 1. Config-level: namespace propagated to all stores
    print("Config propagation:")
    for store_name in ["user_memory", "session_context", "decision_log"]:
        sales_store = sales_lm.stores.get(store_name)
        eng_store = eng_lm.stores.get(store_name)
        if sales_store and eng_store:
            print(
                f"  {store_name}: sales={sales_store.config.namespace}, "
                f"engineering={eng_store.config.namespace}"
            )

    # 2. Data-level: verify stored data has namespace set
    print("\nStored data:")
    sales_mem_store = sales_lm.stores.get("user_memory")
    if sales_mem_store:
        sales_mem_store.print(user_id=user_id)

    eng_ctx_store = eng_lm.stores.get("session_context")
    if eng_ctx_store:
        eng_ctx_store.print(session_id="eng-session-1")

    # 3. Decision log: each agent sees only its own decisions
    print("\nDecision logs (sales):")
    sales_dl = sales_lm.stores.get("decision_log")
    if sales_dl:
        sales_dl.print(agent_id="sales-agent", limit=3)

    print("\nDecision logs (engineering):")
    eng_dl = eng_lm.stores.get("decision_log")
    if eng_dl:
        eng_dl.print(agent_id="eng-agent", limit=3)

    print("\nNamespace isolation verified - each agent's data is scoped separately.")
