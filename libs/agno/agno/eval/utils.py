from typing import Optional

from agno.api.evals import async_create_eval_run, create_eval_run
from agno.api.schemas.evals import EvalRunCreate, EvalType
from agno.utils.log import log_debug


def track_eval_run(
    run_id: str,
    run_data: dict,
    eval_type: EvalType,
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    team_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> None:
    """Call the API to create an evaluation run."""

    try:
        create_eval_run(
            eval_run=EvalRunCreate(
                run_id=run_id,
                type=eval_type,
                data=run_data,
                agent_id=agent_id,
                user_id=user_id,
                team_id=team_id,
                workspace_id=workspace_id,
                agent_name=agent_name,
            )
        )
    except Exception as e:
        log_debug(f"Could not create agent event: {e}")


async def async_track_eval_run(
    run_id: str,
    run_data: dict,
    eval_type: EvalType,
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    team_id: Optional[str] = None,
    workspace_id: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> None:
    """Asycn call to the API to create an evaluation run."""

    try:
        await async_create_eval_run(
            eval_run=EvalRunCreate(
                run_id=run_id,
                type=eval_type,
                data=run_data,
                agent_id=agent_id,
                user_id=user_id,
                team_id=team_id,
                workspace_id=workspace_id,
                agent_name=agent_name,
            )
        )
    except Exception as e:
        log_debug(f"Could not create agent event: {e}")
