from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.os import OSLaunch


def log_os_telemetry(launch: OSLaunch) -> None:
    """Telemetry recording for OS launches"""
    api.post_in_background(ApiRoutes.AGENT_OS_LAUNCH, launch.model_dump(exclude_none=True))
