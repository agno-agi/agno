"""
Bring your own WorkOS token issuer
==================================

Configure AgentOS to verify a WorkOS JWKS, read scopes from the permissions
claim, and enforce the token audience. Without WorkOS credentials this file
runs the required construction smoke using an equivalent local JWKS.

Prerequisites: WORKOS_CLIENT_ID and WORKOS_API_KEY for live provisioning
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/workos_byot.py
Try: with credentials, call GET /agents using a provisioned WorkOS token
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.middleware import JWTMiddleware
from agno.utils.cryptography import generate_rsa_keys
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from fastapi.testclient import TestClient
from jwt.algorithms import RSAAlgorithm

# ---------------------------------------------------------------------------
# Create the WorkOS-integrated AgentOS
# ---------------------------------------------------------------------------


def build_agent_os(jwks_file: str, audience: str) -> tuple[AgentOS, Any]:
    """The production integration: JWKS + permissions claim + audience."""
    research_agent = Agent(
        id="research-agent",
        name="Research Agent",
        model=OpenAIResponses(id="gpt-5.5"),
    )
    agent_os = AgentOS(
        id="workos-security-demo",
        agents=[research_agent],
    )
    app = agent_os.get_app()
    app.add_middleware(
        JWTMiddleware,
        jwks_file=jwks_file,
        algorithm="RS256",
        scopes_claim="permissions",
        admin_scope="agent_os:admin",
        authorization=True,
        verify_audience=True,
        audience=audience,
    )
    return agent_os, app


def _download_workos_jwks(client_id: str, destination: Path) -> Path:
    response = httpx.get(
        f"https://api.workos.com/sso/jwks/{client_id}",
        timeout=10.0,
    )
    response.raise_for_status()
    destination.write_text(response.text, encoding="utf-8")
    return destination


# ---------------------------------------------------------------------------
# Optional demo provisioning ceremony
# ---------------------------------------------------------------------------

PERMISSIONS = ["agents:read", "agents:run", "sessions:read", "agent_os:admin"]
ROLES = {
    "admin": ["agent_os:admin"],
    "member": ["agents:read", "agents:run", "sessions:read"],
    "viewer": ["sessions:read"],
}


def provision_demo_tokens(api_key: str, client_id: str) -> list[tuple[str, str]]:
    """Create a small WorkOS demo tenant and return (role, token) pairs."""
    try:
        from workos import WorkOSClient
        from workos.organization_membership._resource import RoleSingle
        from workos.user_management import PasswordPlaintext
    except ImportError as exc:
        raise RuntimeError("Install the WorkOS SDK with `pip install workos`.") from exc

    workos = WorkOSClient(api_key=api_key, client_id=client_id)
    for permission in PERMISSIONS:
        try:
            workos.authorization.create_permission(slug=permission, name=permission)
        except Exception:
            pass
    for role, permissions in ROLES.items():
        try:
            workos.authorization.create_environment_role(slug=role, name=role)
        except Exception:
            pass
        workos.authorization.set_environment_role_permissions(
            role, permissions=permissions
        )

    organization_name = "Agno BYOT Demo"
    organizations = workos.organizations.list_organizations(limit=100).data
    organization = next(
        (item for item in organizations if item.name == organization_name),
        None,
    )
    if organization is None:
        organization = workos.organizations.create_organization(name=organization_name)

    password_text = "Agno-Demo-Passw0rd!"
    password = PasswordPlaintext(password=password_text)
    tokens: list[tuple[str, str]] = []
    for role in ROLES:
        email = f"{role}@agno-byot-demo.com"
        try:
            user = workos.user_management.create_user(
                email=email,
                password=password,
                email_verified=True,
            )
        except Exception:
            user = workos.user_management.list_users(email=email).data[0]
            workos.user_management.update_user(user.id, password=password)
        try:
            workos.organization_membership.create_organization_membership(
                user_id=user.id,
                organization_id=organization.id,
                role=RoleSingle(role_slug=role),
            )
        except Exception:
            pass
        authentication = workos.user_management.authenticate_with_password(
            email=email,
            password=password_text,
        )
        tokens.append((role, authentication.access_token))
    return tokens


def run_construction_smoke() -> list[str]:
    """Construct the protected app without any WorkOS account or network call."""
    _, public_key = generate_rsa_keys()
    public_key_object = load_pem_public_key(public_key.encode("utf-8"))
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key_object))
    jwk.update({"kid": "construction-key", "alg": "RS256", "use": "sig"})

    with tempfile.TemporaryDirectory() as temp_dir:
        jwks_path = Path(temp_dir) / "jwks.json"
        jwks_path.write_text(json.dumps({"keys": [jwk]}), encoding="utf-8")
        _, app = build_agent_os(str(jwks_path), "construction-client")
        with TestClient(app) as client:
            openapi_response = client.get("/openapi.json")
            health_response = client.get("/health")
        assert openapi_response.status_code == 200
        assert health_response.status_code == 200
        route_paths = sorted(openapi_response.json()["paths"])

    for required_path in ["/agents", "/config", "/health"]:
        assert required_path in route_paths
    return route_paths


# ---------------------------------------------------------------------------
# Run construction smoke or live WorkOS demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    workos_client_id = os.getenv("WORKOS_CLIENT_ID")
    workos_api_key = os.getenv("WORKOS_API_KEY")

    if not workos_client_id or not workos_api_key:
        constructed_routes = run_construction_smoke()
        print("CONSTRUCTION_SMOKE PASS")
        print(
            "Built WorkOS-style JWKS validation with permissions scopes and "
            "audience verification."
        )
        print(f"Mounted {len(constructed_routes)} routes including /agents.")
    else:
        live_jwks_path = _download_workos_jwks(
            workos_client_id, Path("/tmp/agno_workos_jwks.json")
        )
        live_agent_os, live_app = build_agent_os(str(live_jwks_path), workos_client_id)
        demo_tokens = provision_demo_tokens(workos_api_key, workos_client_id)
        for role_name, access_token in demo_tokens:
            print(f"\n{role_name} token:")
            print(access_token)
        live_agent_os.serve(app=live_app, port=7777)
