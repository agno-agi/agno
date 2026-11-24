"""
Several JWT verification keys on one AgentOS
============================================

`JWT_VERIFICATION_KEY` can hold several public keys separated by commas. AgentOS
then accepts a token signed by any of them, so one AgentOS can serve several
issuers, each with its own key pair: two organizations, or an old and a new key
while you rotate.

This applies to asymmetric algorithms (RS256, ES256, ...). With an HS algorithm
the value is one shared secret, commas included.

Prerequisites: none for the smoke; OPENAI_API_KEY for live agent runs
Run: .venvs/demo/bin/python cookbook/05_agent_os/07_security/multiple_verification_keys.py
Try: call GET /agents with either printed token
"""

import os
from datetime import UTC, datetime, timedelta

import jwt
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.utils.cryptography import generate_rsa_keys
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Create an AgentOS that trusts two issuers
# ---------------------------------------------------------------------------

OS_ID = "several-keys-demo"

# Each issuer keeps its private key. AgentOS only gets the public keys.
FIRST_PRIVATE_KEY, FIRST_PUBLIC_KEY = generate_rsa_keys()
SECOND_PRIVATE_KEY, SECOND_PUBLIC_KEY = generate_rsa_keys()
# A third key pair that AgentOS is not told about.
UNKNOWN_PRIVATE_KEY, _ = generate_rsa_keys()

# In a deployment this is set in the environment, not in code.
os.environ["JWT_VERIFICATION_KEY"] = f"{FIRST_PUBLIC_KEY},{SECOND_PUBLIC_KEY}"

security_agent = Agent(
    id="security-agent",
    name="Security Agent",
    model=OpenAIResponses(id="gpt-5.6-luna"),
)

# authorization=True verifies with the keys in JWT_VERIFICATION_KEY (RS256).
agent_os = AgentOS(
    id=OS_ID,
    agents=[security_agent],
    authorization=True,
)
app = agent_os.get_app()


def make_token(private_key: str) -> str:
    """Sign a token as one of the issuers."""
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": "reader",
            "aud": OS_ID,
            "scopes": ["agents:read"],
            "iat": now,
            "exp": now + timedelta(hours=1),
        },
        private_key,
        algorithm="RS256",
    )


def run_smoke() -> dict:
    statuses = {}
    with TestClient(app) as client:
        for issuer, private_key in (
            ("first issuer", FIRST_PRIVATE_KEY),
            ("second issuer", SECOND_PRIVATE_KEY),
            ("unknown issuer", UNKNOWN_PRIVATE_KEY),
        ):
            token = make_token(private_key)
            statuses[issuer] = client.get(
                "/agents", headers={"Authorization": f"Bearer {token}"}
            ).status_code
    assert statuses == {
        "first issuer": 200,
        "second issuer": 200,
        "unknown issuer": 401,
    }, statuses
    return statuses


# ---------------------------------------------------------------------------
# Run the smoke, then serve
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    for issuer, status_code in run_smoke().items():
        print(f"GET /agents with a token from the {issuer}: {status_code}")
    print("\nFirst issuer token:")
    print(make_token(FIRST_PRIVATE_KEY))
    print("\nSecond issuer token:")
    print(make_token(SECOND_PRIVATE_KEY))
    agent_os.serve(app=app, port=7777)
