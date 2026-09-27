from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.team import TeamRunCreate


def create_team_run(run: TeamRunCreate) -> None:
    """Telemetry recording for Team runs"""
    api.post_in_background(ApiRoutes.RUN_CREATE, run.model_dump(exclude_none=True))


async def acreate_team_run(run: TeamRunCreate) -> None:
    """Telemetry recording for async Team runs"""
    await api.apost_in_background(ApiRoutes.RUN_CREATE, run.model_dump(exclude_none=True))
