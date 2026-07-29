"""
Decision Logs: Recording Outcomes
=================================
The feedback half of the decision log: log_decision records the choice with
its reasoning, and record_outcome closes the loop later with what actually
happened. Decision logging is AGENTIC-only - the agent logs deliberately;
there is no automatic extraction pass.

Run:
    .venvs/demo/bin/python cookbook/08_learning/09_decision_logs/02_record_outcomes.py
"""

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.learn import DecisionLogConfig, LearningMachine
from agno.models.openai import OpenAIResponses

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

agent = Agent(
    id="outcome-logger",
    name="Outcome Logger",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    learning=LearningMachine(
        decision_log=DecisionLogConfig(),
    ),
    instructions=[
        "You are an engineering advisor.",
        "When you make a recommendation, log it as a decision with your reasoning.",
        "When told how a past recommendation worked out: first call "
        "search_decisions to find that decision and its id, then call "
        "record_outcome with that id. Never ask the user for a decision id.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Should we use Postgres or DynamoDB for the new billing service? "
        "We need transactions and our team knows SQL.",
        session_id="s1",
        stream=True,
    )

    agent.print_response(
        "Update: we went with your Postgres recommendation and the migration "
        "went smoothly. Record that outcome.",
        session_id="s2",
        stream=True,
    )

    print("\n--- the decision log, with its outcome ---")
    agent.learning_machine.decision_log_store.print(agent_id="outcome-logger")
