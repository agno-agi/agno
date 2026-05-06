"""
Slack Team HITL — External Execution
====================================

DevOps team with a Runbook Agent and a Cluster Agent. The cluster agent
has `@tool(external_execution=True)` for kubectl commands the agent
can't run itself — Slack shows a card asking the user to run the command
and paste the output. The runbook agent looks up remediation steps.

This demonstrates team-level HITL: member agent pauses for external
execution, pause propagates to the team, Slack shows the command + result
textarea, team continues with the user-provided output.

Try in Slack:
  @bot check the api-gateway pods in prod

Slack scopes: app_mentions:read, assistant:write, chat:write, im:history
"""

from typing import Dict

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os.app import AgentOS
from agno.os.interfaces.slack import Slack
from agno.team import Team
from agno.tools import tool

# Stand-in runbook store

_RUNBOOKS: Dict[str, str] = {
    "CrashLoopBackOff": (
        "1. `kubectl describe pod <name>` — check lastState.reason.\n"
        "2. If OOMKilled — increase memory limit.\n"
        "3. If exit code non-zero — check logs with `kubectl logs --previous`."
    ),
    "ImagePullBackOff": (
        "1. Verify image tag exists in registry.\n"
        "2. Check imagePullSecrets on the ServiceAccount."
    ),
    "Pending": (
        "1. `kubectl describe pod` — look for Unschedulable.\n"
        "2. Common: insufficient CPU/memory or node selector mismatch."
    ),
}


# Read-only tool for runbook agent


@tool
def lookup_runbook(symptom: str) -> str:
    """Look up remediation steps for a known pod symptom.

    Args:
        symptom: Pod status like CrashLoopBackOff, ImagePullBackOff, Pending.
    """
    steps = _RUNBOOKS.get(symptom)
    if not steps:
        return f"No runbook for {symptom}. Try searching the web."
    return f"Runbook for {symptom}:\n{steps}"


# External execution tool — user runs it and pastes output


@tool(external_execution=True)
def kubectl_get_pods(namespace: str, selector: str = "") -> str:
    """Get pod status from a Kubernetes cluster. The user runs this command
    and pastes the output back into Slack.

    Args:
        namespace: Kubernetes namespace.
        selector: Optional label selector, e.g. "app=api-gateway".
    """
    flag = f" -l {selector}" if selector else ""
    return f"kubectl get pods -n {namespace}{flag} -o wide"


@tool(external_execution=True)
def kubectl_describe_pod(namespace: str, pod_name: str) -> str:
    """Describe a specific pod for detailed diagnostics. The user runs this
    and pastes the output back into Slack.

    Args:
        namespace: Kubernetes namespace.
        pod_name: Name of the pod to describe.
    """
    return f"kubectl describe pod {pod_name} -n {namespace}"


# Member agents

runbook_agent = Agent(
    name="Runbook Agent",
    role="Looks up remediation steps for known issues",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[lookup_runbook],
    instructions=[
        "You provide remediation guidance.",
        "When the Cluster Agent reports a pod status, use lookup_runbook to find steps.",
        "If no runbook exists, suggest the user search documentation.",
    ],
)

cluster_agent = Agent(
    name="Cluster Agent",
    role="Inspects Kubernetes clusters via external commands",
    model=OpenAIResponses(id="gpt-5.4"),
    tools=[kubectl_get_pods, kubectl_describe_pod],
    instructions=[
        "You inspect Kubernetes clusters.",
        "Use kubectl_get_pods to list pods — the user runs the command and pastes output.",
        "If you see a failing pod, use kubectl_describe_pod for details.",
        "Summarize pod health and identify any issues.",
    ],
)


# Team + storage + Slack interface

db = SqliteDb(
    db_file="tmp/team_hitl_external_execution.db",
    session_table="team_sessions",
    approvals_table="approvals",
)

devops_team = Team(
    id="devops-team-hitl",
    name="DevOps Team",
    model=OpenAIResponses(id="gpt-5.4"),
    members=[cluster_agent, runbook_agent],
    instructions=[
        "You help diagnose Kubernetes issues.",
        "First, ask the Cluster Agent to inspect the pods.",
        "After getting pod status, ask the Runbook Agent for remediation steps.",
        "The kubectl commands will pause for the user to run them and paste output.",
    ],
    db=db,
    add_history_to_context=True,
    telemetry=False,
)

agent_os = AgentOS(
    description="Slack Team HITL — external execution (kubectl)",
    teams=[devops_team],
    db=db,
    interfaces=[
        Slack(
            team=devops_team,
            reply_to_mentions_only=True,
        ),
    ],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="team_hitl_external_execution:app", reload=True)
