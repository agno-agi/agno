import asyncio
import threading
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

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
    # auto_refresh spawns a render thread per Live; skip it when nothing renders.
    return Live(console=console, transient=True, auto_refresh=enabled)


def _is_thread_affine_db(db: BaseDb) -> bool:
    """In-memory sqlite is thread-affine: SQLAlchemy gives it a SingletonThreadPool,
    which keeps one private database per thread, so a write from a worker thread lands
    in a throwaway db and silently disappears. Detect the pool class, not the URL -
    in-memory sqlite has too many spellings (":memory:", "", "file:x?mode=memory&uri=true")
    to enumerate. Such writes must stay on the loop thread."""
    pool = getattr(getattr(db, "db_engine", None), "pool", None)
    if pool is None:
        return False
    try:
        from sqlalchemy.pool import SingletonThreadPool
    except ImportError:
        return False
    return isinstance(pool, SingletonThreadPool)


async def _run_in_daemon_thread(fn: Callable[..., Any], *args: Any) -> None:
    """Run a blocking call on a daemon thread and await its completion.

    Not asyncio.to_thread: executor threads are non-daemon and are joined at
    interpreter shutdown, so a single hung db write would keep the process alive
    after the suite has finished. A daemon thread cannot block exit.
    """
    loop = asyncio.get_running_loop()
    future: "asyncio.Future[None]" = loop.create_future()

    def resolve(outcome: Optional[BaseException]) -> None:
        if future.cancelled():
            # The awaiter timed out and moved on - its CancelledError bypassed the
            # caller's except-Exception warning path, so a late failure is only
            # visible here.
            if outcome is not None:
                log_warning(f"Could not log eval run (write abandoned by timeout): {outcome}")
            return
        if outcome is None:
            future.set_result(None)
        else:
            future.set_exception(outcome)

    def worker() -> None:
        outcome: Optional[BaseException] = None
        try:
            fn(*args)
        except BaseException as exc:
            outcome = exc
        try:
            loop.call_soon_threadsafe(resolve, outcome)
        except RuntimeError:
            # Loop already closed (the caller gave up on a hung write) - the
            # outcome has nowhere to go.
            pass

    threading.Thread(target=worker, name="agno-eval-log", daemon=True).start()
    try:
        await future
    except asyncio.CancelledError:
        # The caller's timeout abandoned the write mid-flight: the daemon thread may
        # still land it, but it is killed outright if the interpreter exits first,
        # and its outcome can no longer be awaited. Warn now - cancellation is the
        # only moment a lost-at-exit write can still be reported.
        log_warning("eval-run db write abandoned by timeout; the row may not be persisted")
        raise


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
            record = EvalRunRecord(
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
            if _is_thread_affine_db(db):
                # Thread-affine: an off-loop write would land in a throwaway per-thread
                # db. In-memory writes don't block on I/O, so run on the loop.
                db.create_eval_run(record)
            else:
                # A sync db driver would block the event loop (and defeat any caller-side
                # timeout, e.g. the suite runner's per-case wait_for) - run it off-loop.
                await _run_in_daemon_thread(db.create_eval_run, record)
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
