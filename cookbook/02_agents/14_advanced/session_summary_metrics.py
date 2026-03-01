"""
Session Summary Metrics
=============================

When an agent uses a SessionSummaryManager, the summary model's token
usage is tracked separately under the "session_summary_model" detail key.

This lets you see how many tokens are spent summarizing the session
versus the agent's own model calls.

The session summary runs after each interaction to maintain a concise
summary of the conversation so far.
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.session.summary import SessionSummaryManager
from rich.pretty import pprint

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    model=OpenAIChat(id="gpt-4o-mini"),
    session_summary_manager=SessionSummaryManager(
        model=OpenAIChat(id="gpt-4o-mini"),
    ),
    enable_session_summaries=True,
    db=db,
    session_id="session-summary-metrics-demo",
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # First run
    run_response_1 = agent.run("My name is Alice and I work at Google.")
    print("=" * 50)
    print("RUN 1 METRICS")
    print("=" * 50)
    pprint(run_response_1.metrics)

    # Second run - triggers session summary
    run_response_2 = agent.run("I also enjoy hiking on weekends.")
    print("=" * 50)
    print("RUN 2 METRICS")
    print("=" * 50)
    pprint(run_response_2.metrics)

    print("=" * 50)
    print("MODEL DETAILS (Run 2)")
    print("=" * 50)
    if run_response_2.metrics and run_response_2.metrics.details:
        for model_type, model_metrics_list in run_response_2.metrics.details.items():
            print(f"\n{model_type}:")
            for model_metric in model_metrics_list:
                pprint(model_metric)

    print("=" * 50)
    print("SESSION METRICS (accumulated)")
    print("=" * 50)
    session_metrics = agent.get_session_metrics()
    if session_metrics:
        pprint(session_metrics)
