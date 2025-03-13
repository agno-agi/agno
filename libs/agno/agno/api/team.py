from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.team import TeamRunCreate, TeamSessionCreate
from agno.cli.settings import agno_cli_settings
from agno.utils.log import logger


def create_team_session(session: TeamSessionCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    logger.debug("--**-- Logging Team Session")
    with api.AuthenticatedClient() as api_client:
        try:
            response = api_client.post(
                ApiRoutes.TEAM_SESSION_CREATE if monitor else ApiRoutes.TEAM_TELEMETRY_SESSION_CREATE,
                json={"session": session.model_dump(exclude_none=True)},
            )
            response.raise_for_status()
        except Exception as e:
            logger.debug(f"Could not create Team session: {e}")
    return


def create_team_run(run: TeamRunCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    logger.debug("--**-- Logging Team Run")
    with api.AuthenticatedClient() as api_client:
        try:
            response = api_client.post(
                ApiRoutes.TEAM_RUN_CREATE if monitor else ApiRoutes.TEAM_TELEMETRY_RUN_CREATE,
                json={"run": run.model_dump(exclude_none=True)},
            )
            response.raise_for_status()
        except Exception as e:
            logger.debug(f"Could not create Team run: {e}")
    return


async def acreate_team_session(session: TeamSessionCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    logger.debug("--**-- Logging Team Session")
    async with api.AuthenticatedAsyncClient() as api_client:
        try:
            response = await api_client.post(
                ApiRoutes.TEAM_SESSION_CREATE if monitor else ApiRoutes.TEAM_TELEMETRY_SESSION_CREATE,
                json={"session": session.model_dump(exclude_none=True)},
            )
            response.raise_for_status()
        except Exception as e:
            logger.debug(f"Could not create Team session: {e}")


async def acreate_team_run(run: TeamRunCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    logger.debug("--**-- Logging Team Run")
    async with api.AuthenticatedAsyncClient() as api_client:
        try:
            response = await api_client.post(
                ApiRoutes.TEAM_RUN_CREATE if monitor else ApiRoutes.TEAM_TELEMETRY_RUN_CREATE,
                json={"run": run.model_dump(exclude_none=True)},
            )
            response.raise_for_status()
        except Exception as e:
            logger.debug(f"Could not create Team run: {e}")
