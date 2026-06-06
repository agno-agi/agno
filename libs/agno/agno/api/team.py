import threading

from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.team import TeamRunCreate
from agno.utils.log import log_debug


def _send_team_run(run: TeamRunCreate) -> None:
    """Send team run telemetry via HTTP (called from background thread)."""
    with api.Client() as api_client:
        try:
            response = api_client.post(
                ApiRoutes.RUN_CREATE,
                json=run.model_dump(exclude_none=True),
            )
            response.raise_for_status()
        except Exception as e:
            log_debug(f"Could not create Team run: {e}")


def create_team_run(run: TeamRunCreate) -> None:
    """Telemetry recording for Team runs (fire-and-forget in background thread)."""
    threading.Thread(target=_send_team_run, args=(run,), daemon=True).start()


async def acreate_team_run(run: TeamRunCreate) -> None:
    """Telemetry recording for async Team runs (fire-and-forget via executor)."""
    import asyncio

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _send_team_run, run)
