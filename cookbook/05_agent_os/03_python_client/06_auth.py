"""Authenticate AgentOSClient calls with the central OS security key.

Start ``_server.py`` with OS_SECURITY_KEY set, then run this file with the same
value. See lesson ``07_security`` in Phase 2 for JWT, RBAC, and service-account
authentication.

Prerequisites: start ``_server.py`` with OS_SECURITY_KEY and OPENAI_API_KEY.
Run: .venvs/demo/bin/python cookbook/05_agent_os/03_python_client/06_auth.py
Try: remove the Authorization header and observe the server return HTTP 401.
"""

import asyncio
import os

from agno.client import AgentOSClient

BASE_URL = "http://localhost:7778"
AGENT_ID = "assistant"


# ---------------------------------------------------------------------------
# Create the Authenticated Client
# ---------------------------------------------------------------------------


async def run_authenticated_calls() -> None:
    """Pass the Bearer header to every SDK operation."""
    security_key = os.environ["OS_SECURITY_KEY"]
    headers = {"Authorization": f"Bearer {security_key}"}
    client = AgentOSClient(base_url=BASE_URL)

    config = await client.aget_config(headers=headers)
    print(f"Authenticated with: {config.name or config.os_id}")

    response = await client.run_agent(
        agent_id=AGENT_ID,
        message="Reply with one sentence confirming this authenticated request.",
        headers=headers,
    )
    print(f"Authenticated run: {response.run_id}")
    print(response.content)


# ---------------------------------------------------------------------------
# Run the Example
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_authenticated_calls())
