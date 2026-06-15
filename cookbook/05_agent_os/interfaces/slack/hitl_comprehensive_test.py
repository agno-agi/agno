"""
Slack HITL Comprehensive Test
=============================

Tests all HITL flows: regular tools, confirmation, user_input, and admin approval.
Use this cookbook to verify the full Slack HITL experience.

Test scenarios:
  @bot analyze system health          -> Regular tool calls (no pause)
  @bot restart nginx                  -> requires_confirmation (local approve/deny)
  @bot create user alice              -> requires_user_input (form fields)
  @bot deploy api to prod v2.0        -> @approval (admin approval via os.agno.com)
  @bot emergency shutdown datacenter  -> @approval + requires_confirmation (both)
"""

from typing import Any, Dict, List

from agno.agent import Agent
from agno.approval import approval
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS
from agno.os.interfaces.slack import Slack
from agno.tools import tool

# Mock data
_SERVICES: Dict[str, Dict[str, Any]] = {
    "nginx": {"status": "running", "cpu": 12, "memory": 256},
    "api": {"status": "running", "cpu": 45, "memory": 1024, "version": "1.9.0"},
    "database": {"status": "running", "cpu": 30, "memory": 2048},
    "cache": {"status": "running", "cpu": 5, "memory": 512},
}

_USERS: Dict[str, Dict[str, str]] = {
    "admin": {"role": "admin", "email": "admin@example.com"},
}

_DEPLOYMENTS: List[Dict[str, str]] = []


# 1. Regular tools (no confirmation needed)
@tool
def get_system_health() -> str:
    """Get overall system health metrics."""
    total_cpu = sum(s["cpu"] for s in _SERVICES.values())
    total_mem = sum(s["memory"] for s in _SERVICES.values())
    running = sum(1 for s in _SERVICES.values() if s["status"] == "running")
    return f"System Health: {running}/{len(_SERVICES)} services running, CPU: {total_cpu}%, Memory: {total_mem}MB"


@tool
def get_service_status(service: str) -> str:
    """Get status of a specific service."""
    if service not in _SERVICES:
        return f"Service '{service}' not found. Available: {', '.join(_SERVICES.keys())}"
    s = _SERVICES[service]
    version = f", v{s['version']}" if "version" in s else ""
    return f"{service}: {s['status']}, CPU: {s['cpu']}%, Memory: {s['memory']}MB{version}"


@tool
def list_users() -> str:
    """List all users in the system."""
    lines = [f"  {name}: {u['role']} ({u['email']})" for name, u in _USERS.items()]
    return "Users:\n" + "\n".join(lines)


# 2. Local confirmation (requires_confirmation)
@tool(requires_confirmation=True)
def restart_service(service: str) -> str:
    """Restart a service. Requires confirmation."""
    if service not in _SERVICES:
        return f"Service '{service}' not found."
    _SERVICES[service]["status"] = "restarting"
    _SERVICES[service]["status"] = "running"
    return f"Service '{service}' restarted successfully."


@tool(requires_confirmation=True)
def delete_user(username: str) -> str:
    """Delete a user. Requires confirmation."""
    if username not in _USERS:
        return f"User '{username}' not found."
    del _USERS[username]
    return f"User '{username}' deleted."


# 3. User input (requires_user_input)
@tool(
    requires_user_input=True,
    user_input_fields=["email", "role"],
)
def create_user(username: str, email: str = "", role: str = "user") -> str:
    """Create a new user. Requires user input for email and role."""
    if username in _USERS:
        return f"User '{username}' already exists."
    _USERS[username] = {"role": role, "email": email}
    return f"User '{username}' created with role '{role}' and email '{email}'."


# 4. Admin approval (@approval decorator)
@approval
@tool(requires_confirmation=True)
def deploy_service(service: str, environment: str, version: str) -> str:
    """Deploy a service. Requires admin approval via os.agno.com."""
    if service not in _SERVICES:
        return f"Service '{service}' not found."
    old_version = _SERVICES[service].get("version", "unknown")
    _SERVICES[service]["version"] = version
    deploy_id = f"D{len(_DEPLOYMENTS) + 1:04d}"
    _DEPLOYMENTS.append({
        "id": deploy_id,
        "service": service,
        "env": environment,
        "old": old_version,
        "new": version,
    })
    return f"Deployment {deploy_id}: {service} ({environment}) v{old_version} -> v{version}"


@approval
@tool(requires_confirmation=True)
def scale_service(service: str, replicas: int) -> str:
    """Scale a service. Requires admin approval."""
    if service not in _SERVICES:
        return f"Service '{service}' not found."
    old_replicas = _SERVICES[service].get("replicas", 1)
    _SERVICES[service]["replicas"] = replicas
    return f"Scaled {service}: {old_replicas} -> {replicas} replicas"


# 5. Admin approval + user input (combined)
@approval
@tool(
    requires_user_input=True,
    user_input_fields=["reason", "notify_team"],
)
def emergency_shutdown(
    datacenter: str,
    reason: str = "",
    notify_team: bool = True,
) -> str:
    """Emergency datacenter shutdown. Requires admin approval + reason input."""
    notification = " (team notified)" if notify_team else ""
    return f"EMERGENCY: Datacenter '{datacenter}' shutdown initiated. Reason: {reason}{notification}"


db = SqliteDb(
    db_file="tmp/hitl_comprehensive_test.db",
    session_table="agent_sessions",
    approvals_table="approvals",
)

agent = Agent(
    name="SysOps Agent",
    id="sysops-agent",
    model=OpenAIResponses(id="gpt-5.5"),
    db=db,
    tools=[
        get_system_health,
        get_service_status,
        list_users,
        restart_service,
        delete_user,
        create_user,
        deploy_service,
        scale_service,
        emergency_shutdown,
    ],
    instructions=[
        "You are a system operations assistant.",
        "Always check service status before operations.",
        "For deployments, confirm the service exists first.",
    ],
    markdown=True,
)

agent_os = AgentOS(
    description="Slack HITL Comprehensive Test",
    agents=[agent],
    db=db,
    interfaces=[Slack(agent=agent, reply_to_mentions_only=True)],
)
app = agent_os.get_app()


if __name__ == "__main__":
    agent_os.serve(app="hitl_comprehensive_test:app", reload=True, port=7777)
