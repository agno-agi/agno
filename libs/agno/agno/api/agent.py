from threading import Thread

from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.agent import AgentRunCreate
from agno.utils.log import log_debug


def _send_agent_run(run: AgentRunCreate) -> None:
    """Telemetry recording for Agent runs"""
    with api.Client() as api_client:
        try:
            api_client.post(
                ApiRoutes.RUN_CREATE,
                json=run.model_dump(exclude_none=True),
            )
        except Exception as e:
            log_debug(f"Could not create Agent run: {e}")


def create_agent_run(run: AgentRunCreate) -> None:
    """Telemetry recording for Agent runs"""
    Thread(target=_send_agent_run, args=(run,), daemon=True).start()


async def acreate_agent_run(run: AgentRunCreate) -> None:
    """Telemetry recording for async Agent runs"""
    async with api.AsyncClient() as api_client:
        try:
            await api_client.post(
                ApiRoutes.RUN_CREATE,
                json=run.model_dump(exclude_none=True),
            )
        except Exception as e:
            log_debug(f"Could not create Agent run: {e}")
