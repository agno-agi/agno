from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.team import TeamRunCreate
from agno.utils.log import log_debug


def create_team_run(run: TeamRunCreate) -> None:
    """Telemetry recording for Team runs"""
    with api.Client() as api_client:
        try:
            response = api_client.post(
                ApiRoutes.RUN_CREATE,
                json=run.model_dump(exclude_none=True),
            )
            response.raise_for_status()
        except Exception as e:
            log_debug(f"Could not create Team run: {e}")


async def acreate_team_run(run: TeamRunCreate) -> None:
    """Telemetry recording for async Team runs"""
    async with api.AsyncClient() as api_client:
        try:
            response = await api_client.post(
                ApiRoutes.RUN_CREATE,
                json=run.model_dump(exclude_none=True),
            )
            response.raise_for_status()
        except Exception as e:
            log_debug(f"Could not create Team run: {e}")
