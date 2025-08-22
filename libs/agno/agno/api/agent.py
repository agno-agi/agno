from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.agent import AgentRunCreate
from agno.utils.log import log_debug


def create_agent_run(run: AgentRunCreate) -> None:
    with api.Client() as api_client:
        try:
            api_client.post(
                ApiRoutes.AGENT_TELEMETRY_RUN_CREATE,
                json={"run": run.model_dump(exclude_none=True)},
            )
        except Exception as e:
            log_debug(f"Could not create Agent run: {e}")
    return


async def acreate_agent_run(run: AgentRunCreate) -> None:
    async with api.AsyncClient() as api_client:
        try:
            await api_client.post(
                ApiRoutes.AGENT_TELEMETRY_RUN_CREATE,
                json={"run": run.model_dump(exclude_none=True)},
            )
        except Exception as e:
            log_debug(f"Could not create Agent run: {e}")

    return
