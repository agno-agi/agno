"""
Directory without auth - the user directory is just a roster, no login required

02_managed_users.py showed the directory with a real kill switch, backed by verified
tokens. This shows the OTHER end - NO auth at all. The whole config is:

    AgentOS(db=db, user_isolation=True, user_directory=True)

That is it. No JWT, no keys, no identity provider. A run comes in with a user_id and
that person just shows up in the directory, and their data is scoped to them. This is
the "just let me see it work" path for local dev and demos.

The idea: a user directory is data (who exists), not a login. So if a run comes in as
"chegizkhan", chegizkhan should just appear. user_isolation is the same - it scopes a
run's own data by its user_id.

What you get without auth:
- A roster. Every run's user_id lands in the directory (user_directory=True turns on
  auto-provision), so you can SEE everyone who has shown up.
- Per-user data. user_isolation=True scopes each run's data by its user_id.

What you do NOT get without auth (read this):
- Enforcement. With no verified identity the user_id is whatever the caller types, so
  both the `disabled` flag AND isolation are ADVISORY here, not a boundary - a caller
  could dodge them by sending a different id. They become real the moment you add
  AgentOS(authorization=True) with a verification key. See 02_managed_users.py.

Run it:
    pip install "agno[roles]"
    export OPENAI_API_KEY=...   # this file makes a real (tiny) run per user
    python 03_directory_without_auth.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS

os.makedirs("tmp", exist_ok=True)

db = SqliteDb(db_file="tmp/directory_no_auth_agentos.db")
scout_agent = Agent(
    id="scout-agent",
    name="Scout Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

# The whole thing. No authentication, no authorization - just a db, isolation, and a
# directory. user_directory=True builds the store from the OS db with auto-provision on, so
# an unauthenticated run's user_id registers the person. AgentOS logs one line at boot noting
# the disabled kill switch and isolation are advisory here (no verified identity).
agent_os = AgentOS(
    id="directory-no-auth-os",
    description="A user directory with no auth at all",
    agents=[scout_agent],
    db=db,
    user_isolation=True,
    user_directory=True,
)
app = agent_os.get_app()

# user_directory=True built the store for us; grab the handle to read the roster and to
# demonstrate the (advisory) disabled flag below.
users = agent_os.user_directory.user_store


if __name__ == "__main__":
    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)  # quiet framework logs for a clean transcript
    client = TestClient(app)

    def run_as(user_id: str) -> int:
        # A plain run with NO Authorization header. The user_id is a form field the caller
        # asserts - exactly how a local app that hasn't wired up auth yet would call the OS.
        r = client.post(
            "/agents/scout-agent/runs",
            data={
                "message": "Say hi in one word.",
                "stream": "false",
                "user_id": user_id,
            },
        )
        return r.status_code

    def show_directory() -> None:
        people = users.list()
        if not people:
            print("    (empty)")
            return
        for u in people:
            print(f"    - {u['id']:12s} disabled={u['disabled']}")

    print("\n" + "=" * 80)
    print("A USER DIRECTORY WITH NO AUTH - just a roster")
    print("=" * 80)

    print("\n  the directory before anyone runs:")
    show_directory()

    print("\n  >> chegizkhan makes a run (no token, just a user_id on the request)...")
    print(
        f"    chegizkhan in the directory beforehand?  {users.get('chegizkhan') is not None}"
    )
    run_as("chegizkhan")
    print(
        f"    chegizkhan in the directory now?         {users.get('chegizkhan') is not None}"
    )

    print("\n  >> subotai runs too...")
    run_as("subotai")

    print("\n  the directory now - a roster of everyone who has shown up:")
    show_directory()

    print("\n  >> now the caveat. an admin DISABLES chegizkhan...")
    users.set_disabled("chegizkhan", True)
    status = run_as("chegizkhan")
    verdict = "BLOCKED" if status in (401, 403) else "ALLOWED"
    print(f"    chegizkhan's next run (still no auth):   {verdict} ({status})")
    print(
        "    -> WITHOUT auth the disabled flag is ADVISORY: the id is self-asserted, so it is"
    )
    print(
        "       not enforced here. Add AgentOS(authorization=True) with a key to make disable"
    )
    print("       (and isolation) real - see 02_managed_users.py.")

    print("=" * 80)
    print(
        "the point: a user directory is data, not a login. with no auth it is a roster that"
    )
    print(
        "fills in from run user_ids, and isolation scopes each run by its user_id - enough to"
    )
    print("demo the features. enforcement is what authorization adds on top.")
    print("=" * 80)
