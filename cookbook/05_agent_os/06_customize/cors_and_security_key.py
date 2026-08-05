"""
Configure CORS and a shared AgentOS security key
================================================

``cors_allowed_origins`` replaces AgentOS's default allowed origins.
``AgnoAPISettings(os_security_key=...)`` protects the REST surface with a
Bearer token. The client verifies an unauthenticated rejection, an
authenticated discovery request, and an allowed CORS preflight.

Prerequisites: optional OS_SECURITY_KEY to replace the local demonstration key
Run: .venvs/demo/bin/python cookbook/05_agent_os/06_customize/cors_and_security_key.py
Try: Run this file with --demo in another terminal
"""

import argparse
import os

import httpx
from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.settings import AgnoAPISettings

# ---------------------------------------------------------------------------
# Create Secured AgentOS
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:7777"
ALLOWED_ORIGIN = "https://console.example.com"
SECURITY_KEY = os.getenv("OS_SECURITY_KEY", "cookbook-security-key")

db = SqliteDb(
    id="cors-security-db",
    db_file="tmp/agent_os_cors_security.db",
)

secured_agent = Agent(
    id="secured-agent",
    name="Secured Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
)

agent_os = AgentOS(
    id="cors-security-os",
    db=db,
    agents=[secured_agent],
    cors_allowed_origins=[ALLOWED_ORIGIN],
    settings=AgnoAPISettings(os_security_key=SECURITY_KEY),
)
app = agent_os.get_app()


def run_demo() -> None:
    """Verify security-key authentication and the configured CORS origin."""
    with httpx.Client(base_url=BASE_URL, timeout=30.0) as client:
        response = client.get("/config")
        if response.status_code != 401:
            raise RuntimeError(
                f"Expected unauthenticated HTTP 401, got {response.status_code}"
            )
        print("Unauthenticated /config: HTTP 401")

        response = client.get(
            "/config",
            headers={"Authorization": f"Bearer {SECURITY_KEY}"},
        )
        response.raise_for_status()
        print("Authenticated /config: HTTP 200")

        response = client.options(
            "/config",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        response.raise_for_status()
        if response.headers.get("access-control-allow-origin") != ALLOWED_ORIGIN:
            raise RuntimeError("The configured CORS origin was not allowed")
        print(f"CORS preflight allowed: {ALLOWED_ORIGIN}")


# ---------------------------------------------------------------------------
# Run Secured AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the HTTP client against a server already listening on port 7777.",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
    else:
        agent_os.serve(app=app, port=7777)
