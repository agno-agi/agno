"""
Session Summary with Limits
============================

Demonstrates how to limit the conversation history sent to the summary model
using `last_n_runs` and `conversation_limit` on SessionSummaryManager.

This is useful for long-running sessions where the full conversation would
exceed the summary model's context window.
"""

from agno.agent.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db_url = "postgresql+psycopg://ai:ai@localhost:5532/ai"
db = PostgresDb(db_url=db_url, session_table="sessions")

# ---------------------------------------------------------------------------
# Option 1: Limit by number of recent runs
# Only the last 5 runs are included when generating the summary.
# ---------------------------------------------------------------------------
summary_manager_by_runs = SessionSummaryManager(
    model=OpenAIChat(id="gpt-4o-mini"),
    last_n_runs=5,
)

agent_by_runs = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    session_id="summary_limit_runs",
    session_summary_manager=summary_manager_by_runs,
    add_session_summary_to_context=True,
)

# ---------------------------------------------------------------------------
# Option 2: Limit by total number of messages
# At most 20 messages are included when generating the summary.
# ---------------------------------------------------------------------------
summary_manager_by_messages = SessionSummaryManager(
    model=OpenAIChat(id="gpt-4o-mini"),
    conversation_limit=20,
)

agent_by_messages = Agent(
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    session_id="summary_limit_messages",
    session_summary_manager=summary_manager_by_messages,
    add_session_summary_to_context=True,
)

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # --- Option 1: Limit by runs ---
    print("=== Limiting by last_n_runs ===")
    agent_by_runs.print_response("Hi, my name is John and I work at Acme Corp")
    agent_by_runs.print_response("We are building a new product for data analytics")
    agent_by_runs.print_response("The stack is Python, FastAPI, and PostgreSQL")
    agent_by_runs.print_response("Our deadline is end of Q2")
    agent_by_runs.print_response(
        "Can you summarize what you know about me and my project?"
    )

    summary = agent_by_runs.get_session_summary(session_id="summary_limit_runs")
    print("Session summary (by runs):", summary)

    # --- Option 2: Limit by message count ---
    print("\n=== Limiting by conversation_limit ===")
    agent_by_messages.print_response("Hi, my name is Jane and I work at Globex")
    agent_by_messages.print_response(
        "We are migrating our infrastructure to Kubernetes"
    )
    agent_by_messages.print_response("The main challenge is stateful services")
    agent_by_messages.print_response(
        "Can you summarize what you know about me and my project?"
    )

    summary = agent_by_messages.get_session_summary(session_id="summary_limit_messages")
    print("Session summary (by messages):", summary)
