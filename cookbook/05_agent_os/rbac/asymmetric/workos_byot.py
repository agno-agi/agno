"""
WorkOS BYOT with AgentOS - 3 roles, real WorkOS tokens, RBAC provisioned via API

Like the basic asymmetric cookbook (3 users / roles + printed curl commands), but
WorkOS is the token issuer. This script:
1. Provisions RBAC entirely via the WorkOS API - permissions, 3 roles, 1 org,
   and 3 users (one per role), each a member of that single org.
2. Mints a REAL WorkOS-signed access token for each user via the password grant
   (a single-org user gets an org-scoped token, so it carries `permissions`).
3. Prints a curl command per user.
4. Serves AgentOS, which verifies each token against the WorkOS JWKS and reads
   scopes from the `permissions` claim.

Roles (permission slugs match AgentOS scopes):
- admin  -> agent_os:admin                          (full access)
- member -> agents:read, agents:run, sessions:read  (can list/run agents)
- viewer -> sessions:read                           (no agents:read -> 403 on /agents)

One-time WorkOS dashboard prerequisites:
- Enable RBAC (so permissions/roles can be created).
- Enable Email + Password authentication (so the password grant works).

Setup:
    pip install workos
    export WORKOS_API_KEY=sk_...        # both from the SAME WorkOS environment
    export WORKOS_CLIENT_ID=client_...
    .venvs/demo/bin/python cookbook/05_agent_os/rbac/asymmetric/workos_byot.py
"""

import os

import httpx
import jwt
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware.jwt import JWTMiddleware
from workos import WorkOSClient
from workos.organization_membership._resource import RoleSingle
from workos.user_management import PasswordPlaintext

# ---------------------------------------------------------------------------
# WorkOS configuration
# ---------------------------------------------------------------------------


def _env(name: str) -> str | None:
    """Read an env var, stripping accidental surrounding quotes/whitespace."""
    value = os.getenv(name)
    return value.strip().strip("\"'").strip() if value else None


WORKOS_CLIENT_ID = _env("WORKOS_CLIENT_ID")
WORKOS_API_KEY = _env("WORKOS_API_KEY")
if not WORKOS_CLIENT_ID or not WORKOS_API_KEY:
    raise SystemExit(
        "Set WORKOS_CLIENT_ID and WORKOS_API_KEY (from the same WorkOS "
        "environment) before running."
    )

_JWKS_FILE = "/tmp/agno_workos_jwks.json"

workos = WorkOSClient(api_key=WORKOS_API_KEY, client_id=WORKOS_CLIENT_ID)

# RBAC definition - permission slugs are identical to AgentOS scope names.
ORG_NAME = "Agno BYOT Demo"
DEMO_DOMAIN = "agno-byot-demo.com"  # a domain with no SSO connection
DEMO_PASSWORD = "Agno-Demo-Passw0rd!"

PERMISSIONS = ["agents:read", "agents:run", "sessions:read", "agent_os:admin"]
ROLES = {
    "admin": ["agent_os:admin"],
    "member": ["agents:read", "agents:run", "sessions:read"],
    "viewer": ["sessions:read"],
}
# (label, email local-part, role slug)
USERS = [
    ("admin", "admin", "admin"),
    ("member", "member", "member"),
    ("viewer", "viewer", "viewer"),
]


def _download_workos_jwks(client_id: str, dest: str) -> str:
    """Fetch the public WorkOS JWKS and write it to a local file.

    `jwks_file` requires a local path (not a URL), which is why we download it.
    The JWKS endpoint is public (keyed by client_id), so no API key is needed.
    """
    url = f"https://api.workos.com/sso/jwks/{client_id}"
    response = httpx.get(url, timeout=10.0)
    response.raise_for_status()
    with open(dest, "w") as f:
        f.write(response.text)
    return dest


# ---------------------------------------------------------------------------
# RBAC provisioning via the WorkOS API (all idempotent)
#
# DEMO ONLY: this whole section just bootstraps a fresh WorkOS account so the
# example runs end to end with no dashboard clicks. If you already have WorkOS
# auth set up (orgs, roles, permissions, users), you do NOT need any of this -
# your users log in through your existing WorkOS flow and AgentOS only has to
# verify the token (see the JWTMiddleware setup below, which is the real
# integration).
# ---------------------------------------------------------------------------


def _ensure_permissions() -> None:
    for slug in PERMISSIONS:
        try:
            workos.authorization.create_permission(slug=slug, name=slug)
        except Exception:
            pass  # already exists


def _ensure_roles() -> None:
    for slug, perms in ROLES.items():
        try:
            workos.authorization.create_environment_role(slug=slug, name=slug)
        except Exception:
            pass  # already exists
        # Idempotent: set replaces the role's permissions with exactly these.
        workos.authorization.set_environment_role_permissions(slug, permissions=perms)


def _ensure_org() -> str:
    for org in workos.organizations.list_organizations(limit=100).data:
        if org.name == ORG_NAME:
            return org.id
    return workos.organizations.create_organization(name=ORG_NAME).id


def _ensure_user(email: str) -> str:
    # NOTE: create_user/update_user only set the password when it is a
    # PasswordPlaintext object - a plain string is silently ignored (the user
    # ends up with no password and authenticate fails as invalid_credentials).
    password = PasswordPlaintext(password=DEMO_PASSWORD)
    try:
        return workos.user_management.create_user(
            email=email, password=password, email_verified=True
        ).id
    except Exception:
        # Already exists -> look it up and (re)set the password so the known
        # DEMO_PASSWORD works even for users created on an earlier run.
        user_id = workos.user_management.list_users(email=email).data[0].id
        workos.user_management.update_user(user_id, password=password)
        return user_id


def _ensure_membership(user_id: str, org_id: str, role_slug: str) -> None:
    try:
        workos.organization_membership.create_organization_membership(
            user_id=user_id,
            organization_id=org_id,
            role=RoleSingle(role_slug=role_slug),
        )
    except Exception:
        pass  # membership already exists


def _mint_token(email: str) -> str:
    """Mint a real WorkOS access token via the password grant.

    The user belongs to exactly one org, so WorkOS returns an org-scoped token
    that carries org_id + role + permissions (no org-selection step needed).
    """
    auth = workos.user_management.authenticate_with_password(
        email=email, password=DEMO_PASSWORD
    )
    return auth.access_token


# ---------------------------------------------------------------------------
# AgentOS configured to verify WorkOS tokens via JWKS + `permissions` claim
# This is the actual WorkOS integration - the only part you need in production.
# ---------------------------------------------------------------------------

_download_workos_jwks(WORKOS_CLIENT_ID, _JWKS_FILE)

db = SqliteDb(db_file="tmp/workos_byot.db")

research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    add_history_to_context=True,
    markdown=True,
)

# Create AgentOS WITHOUT authorization=True, then attach JWTMiddleware directly.
# AuthorizationConfig can't set claim names; WorkOS uses `permissions` (not the
# default `scopes`), so we need JWTMiddleware to override scopes_claim.
agent_os = AgentOS(
    id="my-agent-os",
    description="AgentOS verifying WorkOS-issued tokens (BYOT)",
    agents=[research_agent],
)

app = agent_os.get_app()

app.add_middleware(
    JWTMiddleware,
    jwks_file=_JWKS_FILE,  # local file downloaded above (jwks_file is a PATH, not a URL)
    algorithm="RS256",
    scopes_claim="permissions",  # WorkOS carries scopes under `permissions`
    admin_scope="agent_os:admin",
    authorization=True,
)


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("WorkOS BYOT - provisioning RBAC (permissions, roles, org, users)")
    print("=" * 70)

    _ensure_permissions()
    _ensure_roles()
    org_id = _ensure_org()
    print("Organization: " + ORG_NAME + " (" + org_id + ")")

    tokens = []
    for label, local_part, role_slug in USERS:
        email = f"{local_part}@{DEMO_DOMAIN}"
        user_id = _ensure_user(email)
        _ensure_membership(user_id, org_id, role_slug)
        token = _mint_token(email)
        perms = jwt.decode(token, options={"verify_signature": False}).get(
            "permissions", []
        )
        tokens.append((label, role_slug, perms, token))
        print(f"Provisioned {label:7} {email:32} role={role_slug} perms={perms}")

    print("\n" + "=" * 70)
    print("Test commands (each token is signed by WorkOS, verified via JWKS)")
    print("=" * 70)
    for label, role_slug, perms, token in tokens:
        print(f"\n# {label} ({role_slug}, permissions={perms}):")
        print(
            f'curl -i -H "Authorization: Bearer {token}" http://localhost:7777/agents'
        )

    print("\n# No token -> 401:")
    print("curl -i http://localhost:7777/agents")
    print("\n" + "=" * 70)
    print("Expected on GET /agents: admin 200, member 200, viewer 403, none 401.")
    print("Tokens are short-lived (~5 min) - re-run to mint fresh ones.")
    print("=" * 70 + "\n")

    agent_os.serve(app="workos_byot:app", port=7777, reload=True)
