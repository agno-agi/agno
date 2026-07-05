import asyncio
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.evals import EvalRunRecord, EvalType
from agno.utils.log import log_warning

if TYPE_CHECKING:
    from rich.console import Console
    from rich.live import Live

    from agno.eval.accuracy import AccuracyResult
    from agno.eval.agent_as_judge import AgentAsJudgeResult
    from agno.eval.performance import PerformanceResult
    from agno.eval.reliability import ReliabilityResult


def spinner_live(console: "Console", enabled: bool = True) -> "Live":
    """Transient Live context for an eval progress spinner.

    When disabled (embedders like the suite runner, which must not write to the
    console), the Live is bound to a quiet console and emits nothing - not even
    cursor control sequences.
    """
    from rich.console import Console
    from rich.live import Live

    if not enabled:
        console = Console(quiet=True)
    return Live(console=console, transient=True)


def log_eval_run(
    db: BaseDb,
    run_id: str,
    run_data: dict,
    eval_type: EvalType,
    eval_input: dict,
    agent_id: Optional[str] = None,
    model_id: Optional[str] = None,
    model_provider: Optional[str] = None,
    name: Optional[str] = None,
    evaluated_component_name: Optional[str] = None,
    team_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
) -> None:
    """Call the API to create an evaluation run."""

    try:
        db.create_eval_run(
            EvalRunRecord(
                run_id=run_id,
                eval_type=eval_type,
                eval_data=run_data,
                eval_input=eval_input,
                agent_id=agent_id,
                model_id=model_id,
                model_provider=model_provider,
                name=name,
                evaluated_component_name=evaluated_component_name,
                team_id=team_id,
                workflow_id=workflow_id,
            )
        )
    except Exception as e:
        # A failed write means eval history silently stops persisting - warn, don't debug-log.
        log_warning(f"Could not log eval run: {e}")


async def async_log_eval(
    db: Union[BaseDb, AsyncBaseDb],
    run_id: str,
    run_data: dict,
    eval_type: EvalType,
    eval_input: dict,
    agent_id: Optional[str] = None,
    model_id: Optional[str] = None,
    model_provider: Optional[str] = None,
    name: Optional[str] = None,
    evaluated_component_name: Optional[str] = None,
    team_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
) -> None:
    """Call the API to create an evaluation run."""

    try:
        if isinstance(db, AsyncBaseDb):
            await db.create_eval_run(
                EvalRunRecord(
                    run_id=run_id,
                    eval_type=eval_type,
                    eval_data=run_data,
                    eval_input=eval_input,
                    agent_id=agent_id,
                    model_id=model_id,
                    model_provider=model_provider,
                    name=name,
                    evaluated_component_name=evaluated_component_name,
                    team_id=team_id,
                    workflow_id=workflow_id,
                )
            )
        else:
            # A sync db driver would block the event loop (and defeat any caller-side
            # timeout, e.g. the suite runner's per-case wait_for) - run it off-loop.
            # Caveat: thread-affine drivers (e.g. sqlite :memory:, whose pool keeps a
            # separate database per thread) won't see writes made from this worker
            # thread; use a file-backed or server database for eval history.
            await asyncio.to_thread(
                db.create_eval_run,
                EvalRunRecord(
                    run_id=run_id,
                    eval_type=eval_type,
                    eval_data=run_data,
                    eval_input=eval_input,
                    agent_id=agent_id,
                    model_id=model_id,
                    model_provider=model_provider,
                    name=name,
                    evaluated_component_name=evaluated_component_name,
                    team_id=team_id,
                    workflow_id=workflow_id,
                ),
            )
    except Exception as e:
        # A failed write means eval history silently stops persisting - warn, don't debug-log.
        log_warning(f"Could not log eval run: {e}")


def store_result_in_file(
    file_path: str,
    result: Union["AccuracyResult", "AgentAsJudgeResult", "PerformanceResult", "ReliabilityResult"],
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
        log_warning(f"Failed to save result to file: {str(e)}")
