"""
Authenticate a RemoteAgent run with a Bearer credential
=======================================================

Restart the native AgentOS backend with OS_SECURITY_KEY set, then pass that
same value through RemoteAgent.arun(auth_token=...). The token is attached to
this call rather than stored on the RemoteAgent.

Prerequisites: start `servers/agentos_server.py` with OS_SECURITY_KEY and set OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/20_remote/06_remote_auth.py
Try: run this client with a wrong OS_SECURITY_KEY and observe HTTP 401
"""

import asyncio
import os

from agno.agent import RemoteAgent

# ---------------------------------------------------------------------------
# Create Remote Agent
# ---------------------------------------------------------------------------

remote_assistant = RemoteAgent(
    base_url="http://127.0.0.1:7780",
    agent_id="assistant-agent",
)

# ---------------------------------------------------------------------------
# Run Authenticated Remote Agent
# ---------------------------------------------------------------------------


async def run_authenticated_agent() -> None:
    """Pass the configured security key as this run's Bearer token."""
    security_key = os.environ["OS_SECURITY_KEY"]
    response = await remote_assistant.arun(
        "Confirm this authenticated remote request in one sentence.",
        auth_token=security_key,
    )
    print(f"Authenticated run: {response.run_id}")
    print(response.content)


if __name__ == "__main__":
    asyncio.run(run_authenticated_agent())
