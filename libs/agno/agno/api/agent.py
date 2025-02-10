from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.agent import AgentRunCreate, AgentSessionCreate
from agno.cli.settings import agno_cli_settings
from agno.utils.log import logger


def create_agent_session(session: AgentSessionCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    logger.debug("--**-- Logging Agent Session")
    with api.AuthenticatedClient() as api_client:
        try:
            api_client.post(
                ApiRoutes.AGENT_SESSION_CREATE if monitor else ApiRoutes.AGENT_TELEMETRY_SESSION_CREATE,
                json={"session": session.model_dump(exclude_none=True)},
            )
        except Exception as e:
            logger.debug(f"Could not create Agent session: {e}")
    return


def create_agent_run(run: AgentRunCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    logger.debug("--**-- Logging Agent Run")
    with api.AuthenticatedClient() as api_client:
        try:
            api_client.post(
                ApiRoutes.AGENT_RUN_CREATE if monitor else ApiRoutes.AGENT_TELEMETRY_RUN_CREATE,
                json={"run": run.model_dump(exclude_none=True)},
            )
        except Exception as e:
            logger.debug(f"Could not create Agent run: {e}")
    return


async def acreate_agent_session(session: AgentSessionCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    logger.debug("--**-- Logging Agent Session (Async)")
    async with api.AuthenticatedAsyncClient() as api_client:
        try:
            await api_client.post(
                ApiRoutes.AGENT_SESSION_CREATE if monitor else ApiRoutes.AGENT_TELEMETRY_SESSION_CREATE,
                json={"session": session.model_dump(exclude_none=True)},
            )
        except Exception as e:
            logger.debug(f"Could not create Agent session: {e}")


async def acreate_agent_run(run: AgentRunCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    logger.debug("--**-- Logging Agent Run (Async)")
    async with api.AuthenticatedAsyncClient() as api_client:
        try:
            await api_client.post(
                ApiRoutes.AGENT_RUN_CREATE if monitor else ApiRoutes.AGENT_TELEMETRY_RUN_CREATE,
                json={"run": run.model_dump(exclude_none=True)},
            )
        except Exception as e:
            logger.debug(f"Could not create Agent run: {e}")
