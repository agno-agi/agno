"""
Roles and a Default Role - members and platform users

A role is an object: an id and the scopes it grants. Three scope lists cover most
setups, and they add together because a user holds one role:

- READ      see the agents, teams and workflows, and read sessions
- RUN       run them, and create and rename sessions
- PLATFORM  the built-in components (Super Agent and its helpers), the Company,
            schedules and the build tools

This file defines two roles from those lists and sets one of them as the role a new
user gets:

    member   = Role("member", scopes=READ + RUN)
    platform = Role("platform", scopes=READ + RUN + PLATFORM)

    AgentOS(
        authorization=Authorization(roles=[member, platform], ...),
        user_directory=UserDirectory(default_role=member),
    )

What it shows, with real requests:
1. A new user's first request creates them in the user directory as a member.
2. A member can use the agents but has no platform access.
3. An admin moves the user to platform through the /authz API, and the user's
   next request, with the same token, has platform access.
4. A token that carries scopes keeps working beside the roles.
5. The /authz API is there to create more roles at runtime.

Without `default_role` a new user gets no role, and an admin assigns one.

Run it:
    pip install "agno[os]"
    python 16_roles_and_default_role.py
(no OpenAI key needed - the requests only check who is allowed)
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.authz import PLATFORM, READ, RUN, Authorization, Role, UserDirectory

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "roles-and-default-role-os"

os.makedirs("tmp", exist_ok=True)
db = SqliteDb(db_file="tmp/roles_and_default_role.db")

# The two roles. platform is everything member has plus platform access.
member = Role("member", scopes=READ + RUN, name="Member", description="Uses the agents")
platform = Role(
    "platform",
    scopes=READ + RUN + PLATFORM,
    name="Platform",
    description="Uses the agents, Super Agent and the Company",
)

# Roles are defined on Authorization: they say what is allowed. A role that already
# has scopes in the database is left alone, so a change an admin made through the
# /authz API survives a restart. The object borrows the AgentOS database.
authz = Authorization(
    roles=[member, platform],
    # The administrator below is one by the scopes on their token, so token scopes count beside roles
    trust_token_scopes=True,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    verify_audience=True,
    audience=OS_ID,
)

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
)

# The default role is set on the user directory: it says what a new user gets.
# Pass the Role or its id. It must be a defined role, or AgentOS refuses to start.
agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS with a member role and a platform role",
    db=db,
    agents=[research_agent],
    authorization=authz,
    user_directory=UserDirectory(default_role=member),
)

# Get the app
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run this file to print the decision for each caller.

    dana is a new user: her token carries no scopes, so her role decides.
    root is an administrator whose token carries the admin scope, as a token
    from a control plane does.
    """

    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)  # quiet framework logs for a clean transcript
    client = TestClient(app)

    def auth(sub: str, scopes: list = []) -> dict:
        token = jwt.encode(
            {
                "sub": sub,
                "aud": OS_ID,
                "scopes": scopes,
                "exp": datetime.now(UTC) + timedelta(hours=24),
            },
            JWT_SECRET,
            algorithm="HS256",
        )
        return {"Authorization": f"Bearer {token}"}

    def show(label: str, r, note: str = "") -> None:
        # 200 means the request got in; 401/403 means it was bounced.
        verdict = "BLOCKED" if r.status_code in (401, 403) else "ALLOWED"
        print(f"  {label:50s} -> {verdict:7s} ({r.status_code})  {note}")

    dana = auth("dana@example.com")
    root = auth("root@example.com", ["agent_os:admin"])

    print("\n" + "=" * 86)
    print("ROLES AND A DEFAULT ROLE - member and platform")
    print("=" * 86)
    print("  member   = READ + RUN            (the role a new user gets)")
    print("  platform = READ + RUN + PLATFORM\n")

    show(
        "dana (new user) asks to LOOK at the agent",
        client.get("/agents/research-agent", headers=dana),
        "her first request made her a member",
    )
    print(f"     dana's role in the directory: {authz.roles_of('dana@example.com')}")
    show(
        "dana (member)   asks for the OS CONFIG",
        client.get("/config", headers=dana),
        "platform access only",
    )

    print("\n  >> an admin moves dana to 'platform' through the /authz API...\n")
    moved = client.post(
        "/authz/subjects/dana@example.com/roles",
        json={"role": "platform"},
        headers=root,
    )
    print(f"     {moved.json()}")
    show(
        "dana (platform) asks for the OS CONFIG",
        client.get("/config", headers=dana),
        "same dana, same token, now allowed",
    )

    print("\n  >> a token with scopes keeps working beside the roles...\n")
    show(
        "an operator's token with config:read",
        client.get("/config", headers=auth("operator@example.com", ["config:read"])),
        "its scopes allow it",
    )
    show(
        "another new user, with no scopes on the token",
        client.get("/config", headers=auth("erin@example.com", [])),
        "a member too: no platform access",
    )

    print("\n  >> and an admin can create another role at runtime...\n")
    created = client.post(
        "/authz/roles", json={"slug": "support", "name": "Support"}, headers=root
    )
    client.put(
        "/authz/roles/support/scopes",
        json={"scopes": READ + ["knowledge:read"]},
        headers=root,
    )
    print(f"     created: {created.status_code}")
    roles = client.get("/authz/roles", headers=root).json()["data"]
    for role in roles:
        default = " (default)" if role["is_default"] else ""
        print(f"     {role['slug']:9s} {len(role['scopes']):2d} scopes{default}")

    print("=" * 86)
    print(
        "the point: a person's own role in the user directory decides what they can do."
    )
    print("A new user starts on the default role, and an admin's change applies on the")
    print("next request.")
    print("=" * 86)
