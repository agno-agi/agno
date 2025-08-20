from dataclasses import dataclass


@dataclass
class ApiRoutes:
    # Agent paths
    AGENT_SESSION_CREATE: str = "/v1/agent-sessions"
    AGENT_RUN_CREATE: str = "/v1/agent-runs"
    AGENT_CREATE: str = "/v2/agents"

    # Team paths
    TEAM_RUN_CREATE: str = "/v1/team-runs"
    TEAM_SESSION_CREATE: str = "/v1/team-sessions"
    TEAM_CREATE: str = "/v2/teams"

    # Workflow paths
    WORKFLOW_CREATE: str = "/v2/workflows"
    # Telemetry paths
    # TODO: Update to use the new telemetry paths
    AGENT_TELEMETRY_SESSION_CREATE: str = "/v1/telemetry/agent/session/create"
    AGENT_TELEMETRY_RUN_CREATE: str = "/v1/telemetry/agent/run/create"

    TEAM_TELEMETRY_RUN_CREATE: str = "/v1/telemetry/team-runs"

    # Eval paths
    EVAL_RUN_CREATE: str = "/v2/eval-runs"
