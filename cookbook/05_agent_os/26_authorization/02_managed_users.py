"""
Managed Users - a user directory for AgentOS, no identity provider needed

Already did 01_managed_roles.py? That showed ROLES (who can do what). This shows
USERS (who exists), for the case where you DON'T have an external login system
(no Okta/Auth0/WorkOS). Your own app still signs people in its own way and hands
them a token; AgentOS keeps the list of users and decides what they can do.

Important: AgentOS does NOT store passwords and does not log anyone in. It keeps
a directory - just id, optional email/name, and an on/off switch per person -
plus their roles. Think "address book with an off switch", not "login system".

Why bother keeping users at all (instead of only roles)?
1. You can SEE everyone who exists and pick a person to give a role to, instead
   of typing a raw id you have to remember.
2. You get a real OFF SWITCH. Disable someone and their very next request is
   blocked - even though their token is still valid and unexpired. A token alone
   can't be "un-issued"; the directory can.
3. The audit trail can say "bob@co" instead of an opaque id.

This file creates a few users, gives them roles, then:
- lists the directory,
- shows bob working normally,
- DISABLES bob and shows his next request bounce (same valid token),
- re-enables him,
- and shows a brand-new user auto-provision on their first request, landing usable
  with the default role - no admin step in between.

Run it:
    pip install "agno[roles]"
    python 02_managed_users.py
(no OpenAI key needed - we are only checking who is allowed, not chatting)
"""

import os

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, create_dev_token
from agno.os.authz import Authorization, ManagedUserStore
from agno.os.config import UserDirectoryConfig

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "managed-users-os"

os.makedirs("tmp", exist_ok=True)

# One database for everything: the directory, roles, and audit all live in the OS db.
db = SqliteDb(db_file="tmp/managed_users.db")

# The user directory (roster) is its own thing, separate from authorization. Create the store and
# seed people on it directly: an id + optional email/name, no passwords, plus the disabled off-switch.
users = ManagedUserStore(db=db)
users.upsert("alice", email="alice@co", name="Alice")
users.upsert("bob", email="bob@co", name="Bob")

# Authorization is verification + roles + the admin bootstrap. It never touches the directory.
authz = Authorization(
    db=db,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    verify_audience=True,
    audience=OS_ID,
)
# Roles: what each role can do. default=True flags "viewer" as the role an auto-provisioned user
# gets - single-role model, so exactly one role is the default (flagging another moves the flag).
authz.define_role("viewer", ["agents:*:read"], default=True)
authz.define_role("admin", ["agent_os:admin"])
authz.seed(admin="alice")  # alice is the bootstrap admin (the admin ROLE)
authz.role_store.assign(
    "bob", "viewer"
)  # give bob a role explicitly; everyone else gets the default

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

# The user directory is a top-level AgentOS switch, a peer of user_isolation. Pass the store you
# seeded; auto_provision creates + default-roles an unknown-but-authenticated user on first request.
# Authorization carries verification + roles; together they auto-mount the admin API (/users, /authz).
agent_os = AgentOS(
    id=OS_ID,
    db=db,
    description="Managed-users AgentOS",
    agents=[research_agent],
    user_directory=UserDirectoryConfig(user_store=users, auto_provision=True),
    authorization=authz,
)
app = agent_os.get_app()
# Inspect and manage the directory through the store (list / set_disabled / get) and roles through
# authz.role_store. See 06_manage_users_and_roles.py for a frontend that drives the admin API.
user_store = users


if __name__ == "__main__":
    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)  # quiet framework logs for a clean transcript
    client = TestClient(app)

    def token(sub: str) -> str:
        # create_dev_token (from agno.os) mints a local JWT so you can "be" any user without an
        # IdP. It is the honest local path: the token runs the exact same verification / isolation
        # pipeline as a production token, so what you see here is what you get in prod.
        return create_dev_token(
            sub, secret=JWT_SECRET, audience=OS_ID, expires_in=24 * 3600
        )

    def auth(sub: str) -> dict:
        return {"Authorization": f"Bearer {token(sub)}"}

    def show(label: str, r, note: str = "") -> None:
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:48s} -> {verdict:7s} ({r.status_code})  {note}")

    print("\n" + "=" * 80)
    print("A USER DIRECTORY - no identity provider, just AgentOS")
    print("=" * 80)

    # Everyone in the directory, with the role each one was assigned.
    print("\n  the directory:")
    for u in user_store.list():
        role = (authz.role_store.roles_of(u["id"]) or [None])[0]
        print(
            f"    - {u['id']:8s} {str(u['email'] or ''):12s} role={role}  disabled={u['disabled']}"
        )

    print("\n  bob is a viewer, so he can look at the agent:")
    show(
        "bob asks to LOOK at the agent",
        client.get("/agents/research-agent", headers=auth("bob")),
        "viewers can look",
    )

    print("\n  >> now an admin DISABLES bob (e.g. he left the company)...\n")
    user_store.set_disabled("bob", True, actor="alice")
    show(
        "bob asks to LOOK at the agent",
        client.get("/agents/research-agent", headers=auth("bob")),
        "same valid token, but he's blocked now",
    )

    print("\n  >> ...bob is back, re-enable him...\n")
    user_store.set_disabled("bob", False, actor="alice")
    show(
        "bob asks to LOOK at the agent",
        client.get("/agents/research-agent", headers=auth("bob")),
        "allowed again, instantly",
    )

    print(
        "\n  >> a brand-new user (dave) we've NEVER seen makes his first request...\n"
    )
    print(
        f"    dave in the directory beforehand?  {user_store.get('dave') is not None}"
    )
    show(
        "dave (unknown) asks to LOOK at the agent",
        client.get("/agents/research-agent", headers=auth("dave")),
        "auto-provisioned + granted the default role, so he's allowed on the same request",
    )
    dave_role = (authz.role_store.roles_of("dave") or [None])[0]
    print(
        f"    dave in the directory now?         {user_store.get('dave') is not None}  role={dave_role}"
    )

    print("=" * 80)
    print(
        "the point: you keep the list of users and an off-switch per person. disabling"
    )
    print("someone blocks their NEXT request even though their token is still valid -")
    print(
        "something you can't do with tokens alone. no passwords are ever stored here."
    )
    print("=" * 80)
