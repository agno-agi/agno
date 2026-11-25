"""
Tenant-scoped registry - one catalog in code, a role per tenant decides the view.

(New to authorization? Read 01_managed_roles.py first, then 10_idp_roles_claim.py.)

A Registry holds live Python objects (tool callables, model clients, database
connections), so it is defined in code and deployed once. Which of its entries
a tenant may SEE changes when a customer is onboarded or upgraded, and that
should not need a deploy.

No new concept is needed for that. A tenant is a role:

  - Registry(tools=[...])          the catalog. One, global, in code.
  - roles_claim="org_id"           the tenant on the caller's JWT names the role, so
                                   the user-to-tenant mapping stays in your IdP.
  - registry:<entry>:read          what a role's scopes grant: one catalog entry,
                                   matched by its name or id. registry:read grants all.
  - /authz/roles/...               the existing roles API. Onboard a tenant or
                                   change what it sees at runtime, stored in your db.

GET /registry is the same endpoint for everyone and answers differently per
tenant, the same way GET /agents already does for agents:<id>:read.

Run it:
    pip install "agno[os]"
    python 16_tenant_registry.py
(no extra services and no model key needed; roles live in SQLite under tmp/.)
"""

import os
from datetime import UTC, datetime, timedelta
from typing import List, Optional

import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, Authorization
from agno.registry import Registry

JWT_SECRET = os.getenv("JWT_VERIFICATION_KEY", "your-secret-key-at-least-256-bits-long")
OS_ID = "tenant-registry-os"

os.makedirs("tmp", exist_ok=True)
if os.path.exists("tmp/tenant_registry.db"):
    os.remove("tmp/tenant_registry.db")

db = SqliteDb(db_file="tmp/tenant_registry.db")


# ---------------------------------------------------------------------------
# The catalog: defined in code, deployed once, shared by every tenant.
# ---------------------------------------------------------------------------


def search(query: str) -> str:
    """Search the public web."""
    return f"results for {query}"


def sql(query: str) -> str:
    """Run a read-only SQL query against the warehouse."""
    return f"rows for {query}"


def slack(channel: str, message: str) -> str:
    """Post a message to a Slack channel."""
    return f"posted to {channel}"


registry = Registry(name="Catalog", tools=[search, sql, slack])


# ---------------------------------------------------------------------------
# A tenant is a role. The token's org_id claim names it.
# ---------------------------------------------------------------------------

authz = Authorization(
    db=db,
    verification_keys=[JWT_SECRET],
    algorithm="HS256",
    verify_audience=True,
    audience=OS_ID,
    roles_claim="org_id",  # <- the tenant claim your IdP sends
    # Operators are authorized by the scopes on their own token, tenants by their role.
    trust_token_scopes=True,
)
# What each tenant may see in the catalog.
authz.define_role("acme", ["registry:read"])  # the whole catalog
authz.define_role("globex", ["registry:search:read"])  # one entry

# AgentOS needs something to serve; the agent itself is never run here.
support_agent = Agent(
    id="support-agent",
    name="Support Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    db=db,
)

agent_os = AgentOS(
    id=OS_ID,
    description="AgentOS with a tenant-scoped registry",
    agents=[support_agent],
    db=db,
    registry=registry,
    authorization=authz,
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging

    from fastapi.testclient import TestClient

    logging.disable(logging.CRITICAL)
    client = TestClient(app)

    def token(
        sub: str, org_id: Optional[str] = None, scopes: Optional[List[str]] = None
    ) -> str:
        """A token the way an IdP would mint it: identity plus the person's tenant."""
        claims = {
            "sub": sub,
            "aud": OS_ID,
            "scopes": scopes or [],  # tenants carry no agno scopes; the ROLE decides
            "exp": datetime.now(UTC) + timedelta(hours=1),
        }
        if org_id is not None:
            claims["org_id"] = org_id
        return jwt.encode(claims, JWT_SECRET, algorithm="HS256")

    operator = {
        "Authorization": f"Bearer {token('operator', scopes=['agent_os:admin'])}"
    }

    def show_tools(label: str, tok: str) -> None:
        r = client.get(
            "/registry",
            params={"resource_type": "tool"},
            headers={"Authorization": f"Bearer {tok}"},
        )
        if r.status_code != 200:
            print(f"  {label:34s} -> BLOCKED ({r.status_code})")
            return
        names = ", ".join(item["name"] for item in r.json()["data"]) or "(nothing)"
        print(f"  {label:34s} -> {names}")

    print("\n" + "=" * 80)
    print("TENANT REGISTRY - one catalog, a role per tenant decides the view")
    print("=" * 80)
    print("  catalog in code: search, sql, slack")
    print("  roles: acme = registry:read | globex = registry:search:read\n")

    print("1. the same GET /registry, answered per tenant")
    show_tools("acme user    (org_id=acme)", token("alice", "acme"))
    show_tools("globex user  (org_id=globex)", token("bob", "globex"))
    show_tools("initech user (org_id=initech)", token("dana", "initech"))
    show_tools("user with no org_id claim", token("carol"))

    print(
        "\n2. globex upgrades: the operator adds sql through the roles API (no deploy)"
    )
    r = client.put(
        "/authz/roles/globex/scopes",
        headers=operator,
        json={"scopes": ["registry:search:read", "registry:sql:read"]},
    )
    print(f"  PUT /authz/roles/globex/scopes     -> {r.status_code}")
    show_tools("globex user  (org_id=globex)", token("bob", "globex"))

    print("\n3. initech is onboarded: a new role, created and scoped over the API")
    r = client.post("/authz/roles", headers=operator, json={"slug": "initech"})
    print(f"  POST /authz/roles                  -> {r.status_code}")
    r = client.put(
        "/authz/roles/initech/scopes",
        headers=operator,
        json={"scopes": ["registry:slack:read"]},
    )
    print(f"  PUT /authz/roles/initech/scopes    -> {r.status_code}")
    show_tools("initech user (org_id=initech)", token("dana", "initech"))

    print("\n4. a tenant cannot change its own role")
    r = client.put(
        "/authz/roles/globex/scopes",
        headers={"Authorization": f"Bearer {token('bob', 'globex')}"},
        json={"scopes": ["registry:read"]},
    )
    print(f"  globex user PUT own role scopes    -> {r.status_code}")

    print("=" * 80)
    print("the point: the catalog stays one object in code, and a tenant is a role.")
    print("The existing roles API and database decide who sees which entry.")
    print("=" * 80)
