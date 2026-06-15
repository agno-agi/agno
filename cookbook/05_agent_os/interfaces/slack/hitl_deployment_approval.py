"""
Slack HITL — Deployment Approval
================================

DevOps agent that deploys services to production. Deployments require
admin approval via os.agno.com before executing.

Try in Slack:
  @bot deploy payment-service to prod v2.5.0
  @bot rollback orders-api in staging
"""

from typing import Any, Dict, List

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool

_SERVICES: Dict[str, Dict[str, Any]] = {
    "payment-service": {
        "prod": {"version": "2.4.1", "replicas": 3},
        "staging": {"version": "2.5.0", "replicas": 2},
    },
    "orders-api": {
        "prod": {"version": "1.8.0", "replicas": 5},
        "staging": {"version": "1.9.0-rc1", "replicas": 2},
    },
    "user-auth": {
        "prod": {"version": "3.2.0", "replicas": 4},
        "staging": {"version": "3.3.0", "replicas": 2},
    },
}

_DEPLOYMENT_LOG: List[Dict[str, str]] = []


@tool
def list_services() -> str:
    """List all services and their current versions."""
    lines = []
    for service, envs in _SERVICES.items():
        env_info = ", ".join(f"{e}: v{d['version']}" for e, d in envs.items())
        lines.append(f"  {service}: {env_info}")
    return "Services:\n" + "\n".join(lines)


@tool
def get_service_status(service: str, environment: str) -> str:
    """Get status of a service in an environment."""
    if service not in _SERVICES:
        return f"Service {service!r} not found."
    if environment not in _SERVICES[service]:
        return f"Environment {environment!r} not found for {service}."
    info = _SERVICES[service][environment]
    return f"{service} ({environment}): v{info['version']}, {info['replicas']} replicas"


@approval
@tool(requires_confirmation=True)
def deploy_service(service: str, environment: str, version: str) -> str:
    """Deploy a service. Requires admin approval."""
    if service not in _SERVICES:
        return f"Service {service!r} not found."
    if environment not in _SERVICES[service]:
        return f"Environment {environment!r} not configured."

    old_version = _SERVICES[service][environment]["version"]
    _SERVICES[service][environment]["version"] = version

    deploy_id = f"D{len(_DEPLOYMENT_LOG) + 1:04d}"
    _DEPLOYMENT_LOG.append(
        {
            "id": deploy_id,
            "description": f"{service} {environment}: v{old_version} -> v{version}",
        }
    )
    return f"Deployment {deploy_id}: {service} ({environment}) v{old_version} -> v{version}"


@approval
@tool(requires_confirmation=True)
def rollback_service(service: str, environment: str) -> str:
    """Rollback a service to previous version. Requires admin approval."""
    if service not in _SERVICES:
        return f"Service {service!r} not found."
    if environment not in _SERVICES[service]:
        return f"Environment {environment!r} not configured."

    current = _SERVICES[service][environment]["version"]
    parts = current.split(".")
    if len(parts) >= 2:
        parts[-1] = "0"
        parts[-2] = str(max(0, int(parts[-2]) - 1))
    previous = ".".join(parts)
    _SERVICES[service][environment]["version"] = previous

    deploy_id = f"R{len(_DEPLOYMENT_LOG) + 1:04d}"
    _DEPLOYMENT_LOG.append(
        {
            "id": deploy_id,
            "description": f"ROLLBACK {service} {environment}: v{current} -> v{previous}",
        }
    )
    return f"Rollback {deploy_id}: {service} ({environment}) v{current} -> v{previous}"


db = SqliteDb(
    db_file="tmp/hitl_deployment_approval.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="Deployment Agent",
    id="deployment-agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[list_services, get_service_status, deploy_service, rollback_service],
    instructions=[
        "You are a DevOps assistant managing service deployments.",
        "Check service status before deploying. Report deployment ID after completion.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL — deployment approval",
    agents=[agent],
    db=db,
    interfaces=[Slack(agent=agent, reply_to_mentions_only=True)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_deployment_approval:app", reload=True, port=7777)
