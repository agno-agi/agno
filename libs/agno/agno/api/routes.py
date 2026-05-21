from dataclasses import dataclass


@dataclass
class ApiRoutes:
    """API routes for telemetry recordings"""

    # Runs
    RUN_CREATE: str = "/telemetry/runs"
    EVAL_RUN_CREATE: str = "/telemetry/evals"

    # OS launch
    AGENT_OS_LAUNCH: str = "/telemetry/os"
