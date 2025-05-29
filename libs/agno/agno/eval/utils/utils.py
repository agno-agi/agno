from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from agno.api.evals import async_create_eval_run, create_eval_run
from agno.api.schemas.evals import EvalRunCreate, EvalType
from agno.utils.log import log_debug, logger

if TYPE_CHECKING:
    from agno.eval.accuracy import AccuracyResult
    from agno.eval.performance import PerformanceResult
    from agno.eval.reliability import ReliabilityResult


def log_eval_run(
    run_id: str,
    run_data: dict,
    eval_type: EvalType,
    agent_id: Optional[str] = None,
    model_id: Optional[str] = None,
    model_provider: Optional[str] = None,
    name: Optional[str] = None,
    evaluated_entity_name: Optional[str] = None,
    team_id: Optional[str] = None,
) -> None:
    """Call the API to create an evaluation run."""

    try:
        create_eval_run(
            eval_run=EvalRunCreate(
                run_id=run_id,
                eval_type=eval_type,
                eval_data=run_data,
                agent_id=agent_id,
                model_id=model_id,
                model_provider=model_provider,
                name=name,
                evaluated_entity_name=evaluated_entity_name,
                team_id=team_id,
            )
        )
    except Exception as e:
        log_debug(f"Could not create agent event: {e}")


async def async_log_eval_run(
    run_id: str,
    run_data: dict,
    eval_type: EvalType,
    agent_id: Optional[str] = None,
    model_id: Optional[str] = None,
    model_provider: Optional[str] = None,
    name: Optional[str] = None,
    evaluated_entity_name: Optional[str] = None,
    team_id: Optional[str] = None,
) -> None:
    """Asycn call to the API to create an evaluation run."""

    try:
        await async_create_eval_run(
            eval_run=EvalRunCreate(
                run_id=run_id,
                eval_type=eval_type,
                eval_data=run_data,
                agent_id=agent_id,
                model_id=model_id,
                model_provider=model_provider,
                team_id=team_id,
                name=name,
                evaluated_entity_name=evaluated_entity_name,
            )
        )
    except Exception as e:
        log_debug(f"Could not create agent event: {e}")


def store_result_in_file(
    file_path: str,
    result: Union["AccuracyResult", "PerformanceResult", "ReliabilityResult"],
    eval_id: Optional[str] = None,
    name: Optional[str] = None,
):
    """Store the given result in the given file path"""
    try:
        import json

        fn_path = Path(file_path.format(name=name, eval_id=eval_id))
        if not fn_path.parent.exists():
            fn_path.parent.mkdir(parents=True, exist_ok=True)
        fn_path.write_text(json.dumps(asdict(result), indent=4))
    except Exception as e:
        logger.warning(f"Failed to save result to file: {e}")
