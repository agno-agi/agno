"""Serve an AgentOS with sample sessions to search with nested filters.

The server seeds sessions for two agents, a team, and two users so the filter
examples in ``search_sessions.py`` have something to match. No model calls are made.

Run: .venvs/demo/bin/python cookbook/05_agent_os/31_session_filters/server.py
Try: open http://localhost:7779/docs and call POST /sessions/search.
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.session import AgentSession, TeamSession
from agno.team import Team

# ---------------------------------------------------------------------------
# Create the AgentOS
# ---------------------------------------------------------------------------

# SQLite keeps this demo self-contained. Use PostgreSQL in production.
db = SqliteDb(db_file="tmp/session_filters.db")

support_agent = Agent(
    id="support", name="Support", model=OpenAIResponses(id="gpt-5.6-luna")
)
sales_agent = Agent(id="sales", name="Sales", model=OpenAIResponses(id="gpt-5.6-luna"))
support_team = Team(
    id="support-team",
    name="Support Team",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    members=[support_agent],
)

agent_os = AgentOS(
    id="session-filters-demo",
    name="Session Filters Demo",
    db=db,
    agents=[support_agent, sales_agent],
    teams=[support_team],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Seed Sample Sessions
# ---------------------------------------------------------------------------

DAY = 86_400
START = 1_767_225_600  # 2026-01-01T00:00:00Z

samples = [
    ("billing-question", "support", "alice", "Billing question", 0),
    ("refund-request", "support", "alice", "Refund request", 1),
    ("pricing-plans", "sales", "alice", "Pricing plans", 2),
    ("billing-dispute", "support", "bob", "Billing dispute", 3),
    ("upgrade-quote", "sales", "bob", "Upgrade quote", 4),
]
for session_id, agent_id, user_id, name, day in samples:
    db.upsert_session(
        AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            user_id=user_id,
            session_data={"session_name": name},
            created_at=START + day * DAY,
        )
    )
db.upsert_session(
    TeamSession(
        session_id="billing-escalation",
        team_id="support-team",
        user_id="alice",
        session_data={"session_name": "Billing escalation"},
        created_at=START + 5 * DAY,
    )
)

# ---------------------------------------------------------------------------
# Run the Server
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app, port=7779)
