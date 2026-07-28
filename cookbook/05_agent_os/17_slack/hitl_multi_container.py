"""
Multi-Container HITL with Pre-hook Re-authentication
=====================================================

Demonstrates @hook(run_on_continue=True) for stateless deployments where
each HTTP request may hit a different container/process.

Problem:
- User sends Slack message -> Container A handles run(), authenticates
- Run pauses for confirmation (requires_confirmation=True)
- User clicks Approve button -> Container B handles continue_run()
- Container B has no auth state - must re-authenticate before tool execution

Solution:
- Mark authentication hooks with @hook(run_on_continue=True)
- The hook runs on BOTH run() and continue_run()
- Each container re-authenticates before executing, regardless of state

This pattern is essential for:
- Kubernetes deployments with multiple replicas
- Serverless functions (Lambda, Cloud Functions)
- Load-balanced web servers
- Any stateless architecture

Prerequisites:
- SLACK_TOKEN or SLACK_AGENT_BOT_TOKEN
- SLACK_SIGNING_SECRET or SLACK_AGENT_SIGNING_SECRET
- OPENAI_API_KEY

Run:
    .venvs/demo/bin/python cookbook/05_agent_os/17_slack/hitl_multi_container.py

Expose with ngrok:
    ngrok http 7777 --domain=slack-agent.ngrok.app

Try in Slack:
    @bot Perform a database cleanup for user 123
"""

from os import getenv
from typing import Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.hooks import hook
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.run.agent import RunInput
from agno.tools import tool


# ---------------------------------------------------------------------------
# External Service Client (simulates per-container auth)
# ---------------------------------------------------------------------------
class ServiceClient:
    """
    Per-process service authentication state.

    In production each container/Lambda has its own instance.
    Auth tokens are fetched from environment on each request.
    """

    _authenticated: bool = False
    _api_key: Optional[str] = None

    @classmethod
    def authenticate(cls, api_key: str) -> None:
        print(f"[ServiceClient] Authenticating with key: {api_key[:8]}...")
        cls._api_key = api_key
        cls._authenticated = True

    @classmethod
    def is_authenticated(cls) -> bool:
        return cls._authenticated

    @classmethod
    def reset(cls) -> None:
        """Simulate container restart - auth is lost."""
        cls._authenticated = False
        cls._api_key = None

    @classmethod
    def execute(cls, operation: str, user_id: str) -> str:
        if not cls._authenticated:
            raise RuntimeError("ServiceClient not authenticated")
        return f"Executed '{operation}' for user {user_id}"


# ---------------------------------------------------------------------------
# Pre-hook: Authenticate Service (runs on continue_run too)
# ---------------------------------------------------------------------------
@hook(run_on_continue=True)
def authenticate_service(run_input: RunInput) -> None:
    """
    Re-authenticate service client before tool execution.

    @hook(run_on_continue=True) ensures this runs on:
    - Initial run() call
    - continue_run() after HITL approval

    Without this decorator, continue_run() would skip authentication
    and fail when trying to execute the tool from a fresh container.
    """
    if ServiceClient.is_authenticated():
        print("[Hook] Already authenticated, skipping")
        return

    api_key = getenv("SERVICE_API_KEY", "demo-api-key-12345")
    print(f"[Hook] Authenticating service with key: {api_key[:8]}...")
    ServiceClient.authenticate(api_key)


# ---------------------------------------------------------------------------
# Tool: Database Cleanup (requires confirmation)
# ---------------------------------------------------------------------------
@tool(requires_confirmation=True)
def database_cleanup(user_id: str, operation: str = "archive") -> str:
    """
    Perform a database cleanup operation for a user.

    Requires approval because it modifies production data.

    Args:
        user_id: The user ID to clean up
        operation: Type of cleanup (archive, delete, reset)

    Returns:
        Result of the cleanup operation
    """
    return ServiceClient.execute(operation, user_id)


# ---------------------------------------------------------------------------
# Agent and AgentOS
# ---------------------------------------------------------------------------
db = SqliteDb(
    id="slack-hitl-multi-container-db",
    db_file="tmp/slack_hitl_multi_container.db",
)

slack_agent = Agent(
    id="slack-multi-container-agent",
    name="Slack Multi-Container Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[database_cleanup],
    pre_hooks=[authenticate_service],
    instructions=[
        "You help users perform database operations.",
        "When a user requests a cleanup, call database_cleanup immediately with the provided user_id and operation.",
        "Do NOT ask for confirmation in text - the tool has requires_confirmation=True which shows an Approve/Deny card.",
        "Default operation is 'archive' if not specified.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    id="slack-hitl-multi-container-os",
    description="Demonstrates pre-hook re-auth on continue_run().",
    db=db,
    agents=[slack_agent],
    interfaces=[Slack(agent=slack_agent, prefix="/slack/agent")],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Starting Slack HITL Multi-Container demo...")
    print("Expose with: ngrok http 7777 --domain=slack-agent.ngrok.app")
    print("")
    print("The @hook(run_on_continue=True) decorator ensures authentication")
    print("runs on both run() and continue_run(), handling container restarts.")
    print("")
    agent_os.serve(app=app)
