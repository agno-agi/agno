"""
Slack HITL — External Execution
===============================

DevOps assistant that inspects Kubernetes clusters the agent itself can't
reach. The tool is marked `external_execution=True`, so Slack pauses and
asks the requester to run the kubectl command on their own laptop and
paste the output back. The agent then analyses the pasted result. A local
runbook lookup + web search round out the toolbox so the agent can
correlate symptoms with known remediations.

Try in Slack:
  @bot check the api-gateway pods in the prod namespace

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from typing import Dict

from agno.agent import Agent
from agno.db.sqlite.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool
from agno.tools.duckduckgo import DuckDuckGoTools

# Stand-in runbook store — replace with Confluence / Notion client


_RUNBOOKS: Dict[str, str] = {
    "CrashLoopBackOff": (
        "1. `kubectl describe pod <name> -n <ns>` — inspect lastState.reason.\n"
        "2. If OOMKilled → bump memory limit in deployment.yaml.\n"
        "3. If non-zero exit → pull logs with `kubectl logs --previous`.\n"
    ),
    "ImagePullBackOff": (
        "1. Verify the image tag exists in the registry.\n"
        "2. Check imagePullSecrets are attached to the ServiceAccount.\n"
    ),
    "Pending": (
        "1. `kubectl describe pod` — look for Unschedulable events.\n"
        "2. Common causes: insufficient CPU / memory, no matching node selector.\n"
    ),
}


# Read-only runbook lookup


@tool
def lookup_runbook(symptom: str) -> str:
    """Return internal runbook steps for a known pod symptom. Use after
    seeing a status like CrashLoopBackOff / ImagePullBackOff / Pending.

    Args:
        symptom: Exact k8s pod status / reason string.
    """
    steps = _RUNBOOKS.get(symptom)
    if not steps:
        return f"No runbook for {symptom!r}. Try DuckDuckGo for public docs."
    return f"Runbook for {symptom}:\n{steps}"


# External tool — user runs it and pastes output back


@tool(external_execution=True)
def kubectl_get_pods(namespace: str, selector: str = "") -> str:
    """Describe pods matching a label selector. The agent does NOT run this —
    the requester pastes the raw command output back into the Slack card
    and the agent analyses it.

    Args:
        namespace: Kubernetes namespace.
        selector: Optional label selector, e.g. "app=api-gateway".
    """
    flag = f" -l {selector}" if selector else ""
    return f"kubectl get pods -n {namespace}{flag}"


# Agent + AgentOS + Slack interface

db = SqliteDb(
    db_file="tmp/hitl_external_execution.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="DevOps Agent",
    id="devops-agent",
    model=OpenAIResponses(id="gpt-5.4"),
    db=db,
    tools=[
        kubectl_get_pods,
        lookup_runbook,
        DuckDuckGoTools(),
    ],
    instructions=[
        "You are a DevOps assistant embedded in Slack.",
        "When the user asks about pod status, call kubectl_get_pods with the "
        "right namespace and selector. Slack will pause, show them the "
        "command, and ask them to paste the output back.",
        "After the paused result returns: (1) summarise pod health (Running / "
        "CrashLoopBackOff / Pending / Failed counts); (2) if you see a known "
        "symptom, call lookup_runbook — prefer internal docs over web search; "
        "(3) only fall back to DuckDuckGo if no runbook matches.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — external execution (kubectl)",
    agents=[agent],
    db=db,
    interfaces=[
        Slack(
            agent=agent,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_external_execution:app", reload=True)
