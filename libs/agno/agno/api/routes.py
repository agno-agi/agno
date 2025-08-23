from dataclasses import dataclass


@dataclass
class ApiRoutes:
    """API routes for telemetry recordings"""

    # Runs
    AGENT_RUN_CREATE: str = "/v1/telemetry/agent/run/create"
    EVAL_RUN_CREATE: str = "/v1/telemetry/eval/run/create"
    TEAM_RUN_CREATE: str = "/v1/telemetry/team/run/create"
    WORKFLOW_RUN_CREATE: str = "/v1/telemetry/workflow/run/create"

    # OS launch
    AGENT_OS_LAUNCH: str = "/v1/telemetry/os/launch"