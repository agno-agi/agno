"""
Built-ins Need Their Own Scope - who can reach Super Agent

AgentOS serves a few components of its own: Super Agent (the team `superagent`),
and its helpers Platform Builder and Mini Agent. They can build and change the
platform, so a broad grant does not reach them:

- `teams:run` and `teams:*:run` run every team EXCEPT Super Agent
- only `teams:superagent:run`, or `agent_os:admin`, runs Super Agent

The same holds for `read`, `write` and `delete`, for the two helper agents, and for
lists: a caller who cannot read Super Agent does not see it in `GET /teams`. The rule
is the same for scopes on a token and for scopes on a role.

The `PLATFORM` list carries the built-ins by name, so the usual setup is two roles:

    member   = Role("member", scopes=READ + RUN)                 # the agents you built
    platform = Role("platform", scopes=READ + RUN + PLATFORM)    # plus Super Agent

This file makes real requests as a member, a platform user and an admin, and with
tokens that carry scopes, and prints ALLOWED or BLOCKED for each.

Run it:
    pip install "agno[os]"
    python 17_built_ins_need_their_own_scope.py
(no OpenAI key needed - the requests only check who is allowed)
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager
from agno.os.authz import PLATFORM, READ, RUN, Authorization, Role
from agno.team import Team

# ---------------------------------------------------------------------------
# Create Example
# ---------------------------------------------------------------------------

# JWT Secret (use environment variable in production)
JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "built-ins-os"

os.makedirs("tmp", exist_ok=True)
db = SqliteDb(db_file="tmp/built_ins.db")
model = OpenAIResponses(id="gpt-5.6-luna")

member = Role("member", scopes=READ + RUN)
platform = Role("platform", scopes=READ + RUN + PLATFORM)
admin = Role("admin", scopes=["agent_os:admin"])

authz = Authorization(
    roles=[member, platform, admin],
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    verify_audience=True,
    audience=OS_ID,
)
authz.assign("mia", "member")
authz.assign("paul", "platform")
authz.assign("ada", "admin")

support_agent = Agent(id="support-agent", name="Support Agent", model=model, db=db)
support_team = Team(id="support", name="Support", members=[support_agent], model=model)

# manager=OSManager(...) serves Super Agent as the team "superagent".
agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS with Super Agent and a support team",
    db=db,
    agents=[support_agent],
    teams=[support_team],
    manager=OSManager(model=model),
    authorization=authz,
)

# Get the app
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Run this file to print the decision for each caller.

    mia is a member, paul is a platform user and ada is an admin: their tokens carry
    no scopes, so their role decides. The last three callers have no role: the scopes
    on their token decide.
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
        print(f"  {label:48s} -> {verdict:7s} ({r.status_code})  {note}")

    def teams(headers: dict) -> list:
        return [team["id"] for team in client.get("/teams", headers=headers).json()]

    print("\n" + "=" * 92)
    print("BUILT-INS NEED THEIR OWN SCOPE - who can reach Super Agent")
    print("=" * 92)
    print("  member   = READ + RUN             can use every team but Super Agent")
    print("  platform = READ + RUN + PLATFORM  names Super Agent, so can use it too\n")

    print("  by role (no scopes on the token):")
    show(
        "mia (member) reads the support team",
        client.get("/teams/support", headers=auth("mia")),
        "teams:read covers it",
    )
    show(
        "mia (member) reads Super Agent",
        client.get("/teams/superagent", headers=auth("mia")),
        "teams:read stops short of a built-in",
    )
    print(f"     the teams mia sees:  {teams(auth('mia'))}")
    show(
        "paul (platform) reads Super Agent",
        client.get("/teams/superagent", headers=auth("paul")),
        "PLATFORM names teams:superagent:read",
    )
    print(f"     the teams paul sees: {teams(auth('paul'))}")
    show(
        "ada (admin) reads Super Agent",
        client.get("/teams/superagent", headers=auth("ada")),
        "agent_os:admin reaches everything",
    )

    print("\n  by token scopes (no role):")
    show(
        "a token with teams:read",
        client.get("/teams/superagent", headers=auth("t1", ["teams:read"])),
        "the type-wide scope does not reach it",
    )
    show(
        "a token with teams:*:read",
        client.get("/teams/superagent", headers=auth("t2", ["teams:*:read"])),
        "nor does the wildcard",
    )
    show(
        "a token with teams:superagent:read",
        client.get("/teams/superagent", headers=auth("t3", ["teams:superagent:read"])),
        "its own scope does",
    )

    print("=" * 92)
    print("the point: being able to use every team does not mean being able to use")
    print(
        "Super Agent. Give platform access by name, with PLATFORM or the explicit scope."
    )
    print("=" * 92)
