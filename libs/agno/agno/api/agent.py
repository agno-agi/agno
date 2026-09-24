from threading import Thread

from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.agent import AgentRunCreate


def _send_agent_run(run: AgentRunCreate) -> None:
    """Telemetry recording for Agent runs"""
    api.post_in_background(ApiRoutes.RUN_CREATE, run.model_dump(exclude_none=True))


def create_agent_run(run: AgentRunCreate) -> None:
    """Telemetry recording for Agent runs"""
    Thread(target=_send_agent_run, args=(run,), daemon=True).start()


async def acreate_agent_run(run: AgentRunCreate) -> None:
    """Telemetry recording for async Agent runs"""
    await api.apost_in_background(ApiRoutes.RUN_CREATE, run.model_dump(exclude_none=True))
