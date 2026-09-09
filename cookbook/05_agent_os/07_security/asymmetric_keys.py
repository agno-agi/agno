"""
JWT authentication with asymmetric keys
=======================================

Use an RS256 private key only in the token issuer and give AgentOS only the
public verification key. A local request proves signature and audience
verification before the server starts.

Prerequisites: none for the smoke; OPENAI_API_KEY for live agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/asymmetric_keys.py
Try: call GET /agents with the printed RS256 token
"""

from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.config import AuthorizationConfig
from agno.utils.cryptography import generate_rsa_keys
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create an RS256-protected AgentOS
# ---------------------------------------------------------------------------

OS_ID = "asymmetric-security-demo"
PRIVATE_KEY, PUBLIC_KEY = generate_rsa_keys()

security_agent = Agent(
    id="security-agent",
    name="Security Agent",
    model=OpenAIResponses(id="gpt-5.5"),
)

agent_os = AgentOS(
    id=OS_ID,
    agents=[security_agent],
    authorization=True,
    authorization_config=AuthorizationConfig(
        verification_keys=[PUBLIC_KEY],
        algorithm="RS256",
        verify_audience=True,
    ),
)
app = agent_os.get_app()


def make_token(subject: str, scopes: list[str]) -> str:
    """Sign a token as the example identity provider."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "aud": OS_ID,
            "scopes": scopes,
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        PRIVATE_KEY,
        algorithm="RS256",
    )


def run_smoke() -> int:
    token = make_token("reader", ["agents:read"])
    with TestClient(app) as client:
        status_code = client.get(
            "/agents", headers={"Authorization": f"Bearer {token}"}
        ).status_code
    assert status_code == 200, status_code
    return status_code


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    observed_status = run_smoke()
    print(f"RS256 GET /agents status: {observed_status}")
    print("\nReader token:")
    print(make_token("reader", ["agents:read"]))
    print(
        "\nProduction boundary: the issuer keeps the private key; "
        "AgentOS receives only the public key."
    )
    agent_os.serve(app=app, port=7777)
