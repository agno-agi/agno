"""
Return External Tool Execution to Slack
=======================================

Pause on a Kubernetes diagnostic the Agent cannot execute. Slack displays the
tool name and command argument, then collects the operator's external result.

Prerequisites: SLACK_TOKEN, SLACK_SIGNING_SECRET, OPENAI_API_KEY
Run: .venvs/demo/bin/python cookbook/05_agent_os/17_slack/hitl_external_execution.py
Try in Slack: Ask "Check api-gateway pods in the production namespace."
Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool
from agno.tools.websearch import WebSearchTools

runbooks = {
    "CrashLoopBackOff": "Inspect lastState, then check previous logs and memory limits.",
    "ImagePullBackOff": "Verify the image tag and the ServiceAccount imagePullSecrets.",
    "Pending": "Inspect scheduling events, requested resources, and node selectors.",
}


@tool(external_execution=True)
def run_kubectl(command: str) -> str:
    """Represent a kubectl command that the operator executes outside AgentOS."""
    return command


@tool
def lookup_runbook(symptom: str) -> str:
    """Return internal remediation guidance for a Kubernetes pod symptom."""
    return runbooks.get(symptom, f"No internal runbook found for {symptom}.")


# ---------------------------------------------------------------------------
# Create External-execution Slack AgentOS
# ---------------------------------------------------------------------------

db = SqliteDb(
    id="slack-hitl-external-db",
    db_file="tmp/slack_hitl_external.db",
)

devops_agent = Agent(
    id="slack-devops-agent",
    name="Slack DevOps Agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[run_kubectl, lookup_runbook, WebSearchTools()],
    instructions=[
        "For pod-health requests, call run_kubectl with the complete command argument.",
        "The Python entrypoint does not run before the pause. Slack displays the "
        "tool name and command argument, then collects the operator's external result.",
        "Analyze the submitted output and count healthy and unhealthy pods.",
        "Prefer lookup_runbook for a recognized symptom; use web search only as fallback.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    id="slack-hitl-external-os",
    description="AgentOS resuming an externally executed tool through Slack.",
    db=db,
    agents=[devops_agent],
    interfaces=[Slack(agent=devops_agent)],
)
app = agent_os.get_app()

# ---------------------------------------------------------------------------
# Run External-execution Slack AgentOS
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent_os.serve(app=app)
