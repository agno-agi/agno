import threading

from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.evals import EvalRunCreate
from agno.utils.log import log_debug


def _send_eval_run(eval_run: EvalRunCreate) -> None:
    """Send eval run telemetry via HTTP (called from background thread)."""
    with api.Client() as api_client:
        try:
            api_client.post(ApiRoutes.EVAL_RUN_CREATE, json=eval_run.model_dump(exclude_none=True))
        except Exception as e:
            log_debug(f"Could not create evaluation run: {e}")


def create_eval_run_telemetry(eval_run: EvalRunCreate) -> None:
    """Telemetry recording for Eval runs (fire-and-forget in background thread)."""
    threading.Thread(target=_send_eval_run, args=(eval_run,), daemon=True).start()


async def async_create_eval_run_telemetry(eval_run: EvalRunCreate) -> None:
    """Telemetry recording for async Eval runs (fire-and-forget via executor)."""
    import asyncio

    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, _send_eval_run, eval_run)
