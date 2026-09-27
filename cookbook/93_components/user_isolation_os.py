"""
Per-User Component Isolation
============================

Demonstrates serving components with per-user isolation, so each caller only
sees and manages the agents, teams, and workflows they created.

Components created over POST /components are stamped with the caller's JWT
subject, and the component, list, and run routes are scoped to that owner.
Admins (agent_os:admin scope) keep seeing everything.

Generate a token for a user with:

    python -c "import jwt, datetime as d; print(jwt.encode({'sub': 'alice', \
'scopes': ['components:read', 'components:write', 'components:delete', \
'agents:read', 'agents:run'], 'exp': d.datetime.now(d.UTC) + \
d.timedelta(hours=1)}, 'my-jwt-secret', algorithm='HS256'))"

Then create a component as that user:

    curl -X POST http://localhost:7777/components \
        -H "Authorization: Bearer $ALICE_TOKEN" -H "Content-Type: application/json" \
        -d '{"name": "Alice Agent", "component_type": "agent", "stage": "published",
             "config": {"name": "Alice Agent", "instructions": "You are Alice private agent."}}'

A token for a different user sees none of it:

    curl http://localhost:7777/components -H "Authorization: Bearer $BOB_TOKEN"
    curl http://localhost:7777/agents -H "Authorization: Bearer $BOB_TOKEN"
"""

from agno.db.postgres import PostgresDb
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", id="postgres_db")

# ---------------------------------------------------------------------------
# Create AgentOS App
# ---------------------------------------------------------------------------
# No agents are registered in code: only components created over the API live in
# the database and can be owned. Components passed to AgentOS(agents=[...]) are shared.
agent_os = AgentOS(
    id="user-isolation-os",
    db=db,
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=["my-jwt-secret"],
        algorithm="HS256",
        user_isolation=True,
    ),
)

app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run AgentOS App
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="user_isolation_os:app", reload=True)
