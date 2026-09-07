"""
Directory without auth - the user directory is just a roster, no login required

managed_users.py showed the directory with authentication: a verified token, a real
kill switch. This shows the OTHER end - NO auth at all. The directory is simply a
list of people, and a run's user_id registers whoever it names. No JWT, no keys, no
identity provider. This is the "just let me see it work" path for local dev and demos.

The point Ashpreet made: a user directory is data, not a security boundary. So if a
run comes in with user_id "chegizkhan", that person should just show up in the
directory - even with no auth configured.

What you get without auth:
- A roster. Every run's user_id lands in the directory (auto_provision), so you can
  SEE everyone who has shown up, with their metadata.

What you do NOT get without auth (read this):
- Enforcement. With no verified identity the user_id is whatever the caller types,
  so the `disabled` flag is ADVISORY here, not a kill switch - a caller could dodge
  it by sending a different id. Disable becomes a real revocation only once you add
  AgentOS(authentication=True) (verify who) or authorization=True (verify + enforce).
  See managed_users.py for the enforced version.

Run it:
    pip install "agno[roles]"
    export OPENAI_API_KEY=...   # this file makes a real (tiny) run per user
    python directory_without_auth.py
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.authz.user_store import ManagedUserStore
from agno.os.config import UserDirectoryConfig

os.makedirs("tmp", exist_ok=True)

# The directory: just people, no passwords, no roles required. auto_provision=True means a
# user we have never seen is created from the run's user_id on their first request.
users = ManagedUserStore(db_url="sqlite:///tmp/directory_no_auth.db")

db = SqliteDb(db_file="tmp/directory_no_auth_agentos.db")
scout_agent = Agent(
    id="scout-agent",
    name="Scout Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

# No authentication, no authorization. Just a db and a directory. The directory is seeded and
# an unauthenticated run's user_id registers the person - a working roster with zero auth setup.
# (AgentOS logs a one-line warning at boot that the disabled kill switch is advisory here.)
agent_os = AgentOS(
    id="directory-no-auth-os",
    description="A user directory with no auth at all",
    agents=[scout_agent],
    user_directory=UserDirectoryConfig(store=users, auto_provision=True),
)
app = agent_os.get_app()


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
        "       not enforced here. Add AgentOS(authentication=True) to make disable a real"
    )
    print("       revocation - see managed_users.py.")

    print("=" * 80)
    print(
        "the point: a user directory is data, not a login. with no auth it is a roster that"
    )
    print(
        "fills in from run user_ids - enough to demo the feature. enforcement (the disabled"
    )
    print("kill switch) is what authentication/authorization add on top.")
    print("=" * 80)
