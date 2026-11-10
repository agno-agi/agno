"""Let a regular user run the manager within their existing permissions.

Set JWT_VERIFICATION_KEY and OPENAI_API_KEY, then serve this example. Authenticate
with a JWT whose sub is "alice" and aud is "manager-access-demo". Alice can ask the
manager to run math-helper or diagnostics and reopen her own sessions, but cannot
publish components or create schedules. Grants come from the managed role, not the JWT scopes claim.

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_user_access.py
"""

from os import environ

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization, OSManager

model = OpenAIResponses(id="gpt-5.6-luna")
math_helper = Agent(
    id="math-helper",
    name="Math Helper",
    model=model,
    instructions="Help with arithmetic.",
)

authorization = Authorization(
    verification_keys=[environ["JWT_VERIFICATION_KEY"]],
    algorithm="HS256",
    audience="manager-access-demo",
    verify_audience=True,
)
authorization.define_role(
    "manager-user",
    [
        "teams:os-manager-internal:run",
        "teams:os-manager-internal:read",
        "agents:math-helper:run",
        "agents:math-helper:read",
        "config:read",
        "sessions:read",
    ],
)
authorization.assign("alice", "manager-user")

agent_os = AgentOS(
    id="manager-access-demo",
    db=SqliteDb(db_file="tmp/manager-access.db"),
    agents=[math_helper],
    authorization=authorization,
    user_isolation=True,
    manager=OSManager(model=model),
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="manager_user_access:app", reload=True)
