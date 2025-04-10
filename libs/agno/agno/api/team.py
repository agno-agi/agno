from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.team import TeamRunCreate, TeamSessionCreate
from agno.cli.settings import agno_cli_settings
from agno.utils.log import log_debug


def create_team_run(run: TeamRunCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    log_debug("--**-- Logging Team Run")
    with api.AuthenticatedClient() as api_client:
        try:
            response = api_client.post(
                ApiRoutes.TEAM_RUN_CREATE if monitor else ApiRoutes.TEAM_TELEMETRY_RUN_CREATE,
                json={"run": run.model_dump(exclude_none=True)},
            )
            response.raise_for_status()
        except Exception as e:
            log_debug(f"Could not create Team run: {e}")
    return


async def acreate_team_run(run: TeamRunCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    log_debug("--**-- Logging Team Run")
    async with api.AuthenticatedAsyncClient() as api_client:
        try:
            response = await api_client.post(
                ApiRoutes.TEAM_RUN_CREATE if monitor else ApiRoutes.TEAM_TELEMETRY_RUN_CREATE,
                json={"run": run.model_dump(exclude_none=True)},
            )
            response.raise_for_status()
        except Exception as e:
            log_debug(f"Could not create Team run: {e}")


def upsert_team_session(session: TeamSessionCreate, monitor: bool = False) -> None:
    if not agno_cli_settings.api_enabled:
        return

    log_debug("--**-- Logging Team Session")
    with api.AuthenticatedClient() as api_client:
        try:
            if monitor:
                api_client.post(
                    ApiRoutes.TEAM_SESSION_CREATE,
                    json={"session": session.model_dump(exclude_none=True)},
                )
        except Exception as e:
            log_debug(f"Could not create Agent session: {e}")
    return
