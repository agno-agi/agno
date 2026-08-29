from agno.api.api import api
from agno.api.routes import ApiRoutes
from agno.api.schemas.evals import EvalRunCreate


def create_eval_run_telemetry(eval_run: EvalRunCreate) -> None:
    """Telemetry recording for Eval runs"""
    api.post_in_background(ApiRoutes.EVAL_RUN_CREATE, eval_run.model_dump(exclude_none=True))


async def async_create_eval_run_telemetry(eval_run: EvalRunCreate) -> None:
    """Telemetry recording for async Eval runs"""
    await api.apost_in_background(ApiRoutes.EVAL_RUN_CREATE, eval_run.model_dump(exclude_none=True))
