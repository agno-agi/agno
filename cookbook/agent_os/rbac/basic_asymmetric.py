"""
Basic RBAC Example with AgentOS (Asymmetric Keys)

This example demonstrates how to enable RBAC (Role-Based Access Control)
with JWT token authentication using RS256 asymmetric keys.

RS256 uses:
- Private key: Used by your auth server to SIGN tokens
- Public key: Used by AgentOS to VERIFY token signatures

Prerequisites:
- Set JWT_VERIFICATION_KEY and JWT_SIGNING_KEY environment variables with your public and private keys (PEM format)
- Or generate keys at runtime for testing (as shown below)
- Endpoints are automatically protected with default scope mappings
"""

from datetime import UTC, datetime, timedelta
import os
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from agno.os import AgentOS
from agno.os.config import JWTConfig
from agno.tools.duckduckgo import DuckDuckGoTools


def generate_rsa_keys():
    """Generate RSA key pair for RS256 JWT signing/verification."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Private key PEM (used by auth server to sign tokens)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    # Public key PEM (used by AgentOS to verify tokens)
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    return private_pem.decode("utf-8"), public_pem.decode("utf-8")

PUBLIC_KEY = os.getenv("JWT_VERIFICATION_KEY", None)
PRIVATE_KEY = os.getenv("JWT_SIGNING_KEY", None)

if not PUBLIC_KEY:
    # Generate keys for this example (in production, use your auth provider's public key)
    PRIVATE_KEY, PUBLIC_KEY = generate_rsa_keys()

# In production, load the public key from environment variable:
# PUBLIC_KEY = os.getenv("JWT_VERIFICATION_KEY")

# Setup database
db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")

# Create agents
research_agent = Agent(
    id="research-agent",
    name="Research Agent",
    model=OpenAIChat(id="gpt-4o"),
    db=db,
    tools=[DuckDuckGoTools()],
    add_history_to_context=True,
    markdown=True,
)

# Create AgentOS with RS256 (default algorithm)
agent_os = AgentOS(
    description="RBAC Protected AgentOS",
    agents=[research_agent],
    authorization=True,
    jwt_config=JWTConfig(
        verification_key=PUBLIC_KEY,
        algorithm="RS256",
    ),
)

# Get the app
app = agent_os.get_app()


if __name__ == "__main__":
    """
    Run your AgentOS with RBAC enabled using RS256 asymmetric keys.
    
    Key Distribution:
    - Private key: Keep secret on your auth server (signs tokens)
    - Public key: Share with AgentOS (verifies tokens)
    
    Default scope mappings protect all endpoints:
    - GET /agents/{agent_id}: requires "agents:read"
    - POST /agents/{agent_id}/runs: requires "agents:run"
    - GET /sessions: requires "sessions:read"
    - GET /memory: requires "memory:read"
    - etc.
    
    Special scopes:
    - "admin": grants access to all endpoints
    - "agents:*": grants all agent permissions
    """
    if PRIVATE_KEY:
        # Create test tokens signed with the PRIVATE key
        user_token_payload = {
            "sub": "user_123",
            "session_id": "session_456",
            "scopes": ["agents:read", "agents:run"],
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        }
        user_token = jwt.encode(user_token_payload, PRIVATE_KEY, algorithm="RS256")

        admin_token_payload = {
            "sub": "admin_789",
            "session_id": "admin_session_123",
            "scopes": ["admin"],  # Admin has access to everything
            "exp": datetime.now(UTC) + timedelta(hours=24),
            "iat": datetime.now(UTC),
        }
        admin_token = jwt.encode(admin_token_payload, PRIVATE_KEY, algorithm="RS256")

        print("\n" + "=" * 60)
        print("RBAC Test Tokens (RS256 Asymmetric)")
        print("=" * 60)
        print("\nUser Token (agents:read, agents:run):")
        print(user_token)
        print("\nAdmin Token (admin - full access):")
        print(admin_token)
        print("\n" + "=" * 60)
        print("\nTest commands:")
        print(
            f'\ncurl -H "Authorization: Bearer {user_token}" http://localhost:7777/agents'
        )
        print(
            f'\ncurl -H "Authorization: Bearer {admin_token}" http://localhost:7777/sessions'
        )
        print("\n" + "=" * 60 + "\n")

    agent_os.serve(app="basic_asymmetric:app", port=7777, reload=True)
