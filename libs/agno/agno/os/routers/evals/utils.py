import asyncio
from contextlib import suppress
from dataclasses import replace
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union, cast
from uuid import uuid4

from fastapi import HTTPException

from agno.agent import Agent, RemoteAgent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.db.schemas.evals import EvalRunRecord
from agno.db.schemas.scheduler import strip_reserved_run_metadata
from agno.eval.accuracy import AccuracyEval
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.eval.performance import PerformanceEval
from agno.eval.reliability import ReliabilityEval
from agno.eval.suite import Case, CaseResult, EvalSuite, JudgeMode, SuiteResult, _component_id, arun_cases
from agno.exceptions import EvalError, RunCancelledException
from agno.models.base import Model
from agno.models.utils import get_model
from agno.os.routers.evals.schemas import EvalRunInput, EvalSchema, EvalSuiteInput
from agno.os.utils import get_agent_by_id, get_db, get_eval_suite_by_id, get_team_by_id
from agno.remote.base import RemoteDb
from agno.run.base import RunStatus
from agno.run.cancel import ais_cancelled
from agno.run.status_persist import RunPersistOutcome
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_info, log_warning


async def run_accuracy_eval(
    eval_run_input: EvalRunInput,
    db: Union[BaseDb, AsyncBaseDb],
    agent: Optional[Agent] = None,
    team: Optional[Team] = None,
    default_model: Optional[Model] = None,
) -> EvalSchema:
    """Run an Accuracy evaluation for the given agent or team"""
    if not eval_run_input.expected_output:
        raise HTTPException(status_code=400, detail="expected_output is required for accuracy evaluation")

    accuracy_eval = AccuracyEval(
        db=db,
        agent=agent,
        team=team,
        input=eval_run_input.input,
        expected_output=eval_run_input.expected_output,
        additional_guidelines=eval_run_input.additional_guidelines,
        additional_context=eval_run_input.additional_context,
        num_iterations=eval_run_input.num_iterations or 1,
        name=eval_run_input.name,
        model=default_model,
    )

    result = await accuracy_eval.arun(print_results=False, print_summary=False)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to run accuracy evaluation")

    eval_run = EvalSchema.from_accuracy_eval(accuracy_eval=accuracy_eval, result=result)

    # Restore original model after eval
    if default_model is not None:
        if agent is not None:
            agent.model = default_model
        elif team is not None:
            team.model = default_model

    return eval_run


async def run_agent_as_judge_eval(
    eval_run_input: EvalRunInput,
    db: Union[BaseDb, AsyncBaseDb],
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    default_model: Optional[Model] = None,
) -> EvalSchema:
    """Run an AgentAsJudge evaluation for the given agent or team"""
    if not eval_run_input.criteria:
        raise HTTPException(status_code=400, detail="criteria is required for agent-as-judge evaluation")

    # Run agent/team to get output
    if agent:
        agent_response = await agent.arun(eval_run_input.input, stream=False)  # type: ignore[misc]
        output = str(agent_response.content) if agent_response.content else ""
        agent_id = agent.id
        team_id = None
    elif team:
        team_response = await team.arun(eval_run_input.input, stream=False)  # type: ignore[misc]
        output = str(team_response.content) if team_response.content else ""
        agent_id = None
        team_id = team.id
    else:
        raise HTTPException(status_code=400, detail="Either agent_id or team_id must be provided")

    agent_as_judge_eval = AgentAsJudgeEval(
        db=db,
        criteria=eval_run_input.criteria,
        scoring_strategy=eval_run_input.scoring_strategy or "binary",
        threshold=eval_run_input.threshold or 7,
        additional_guidelines=eval_run_input.additional_guidelines,
        name=eval_run_input.name,
        model=default_model,
    )

    result = await agent_as_judge_eval.arun(
        input=eval_run_input.input, output=output, print_results=False, print_summary=False
    )
    if not result:
        raise HTTPException(status_code=500, detail="Failed to run agent as judge evaluation")

    # Use evaluator's model
    eval_model_id = agent_as_judge_eval.model.id if agent_as_judge_eval.model is not None else None
    eval_model_provider = agent_as_judge_eval.model.provider if agent_as_judge_eval.model is not None else None

    eval_run = EvalSchema.from_agent_as_judge_eval(
        agent_as_judge_eval=agent_as_judge_eval,
        result=result,
        agent_id=agent_id,
        team_id=team_id,
        model_id=eval_model_id,
        model_provider=eval_model_provider,
    )

    # Restore original model after eval
    if default_model is not None:
        if agent is not None and isinstance(agent, Agent):
            agent.model = default_model
        elif team is not None and isinstance(team, Team):
            team.model = default_model

    return eval_run


async def run_performance_eval(
    eval_run_input: EvalRunInput,
    db: Union[BaseDb, AsyncBaseDb],
    agent: Optional[Agent] = None,
    team: Optional[Team] = None,
    default_model: Optional[Model] = None,
) -> EvalSchema:
    """Run a performance evaluation for the given agent or team"""
    if agent:

        async def run_component():  # type: ignore
            return await agent.arun(eval_run_input.input, stream=False)  # type: ignore[misc]

        model_id = agent.model.id if agent and agent.model else None
        model_provider = agent.model.provider if agent and agent.model else None

    elif team:

        async def run_component():  # type: ignore
            return await team.arun(eval_run_input.input, stream=False)  # type: ignore[misc]

        model_id = team.model.id if team and team.model else None
        model_provider = team.model.provider if team and team.model else None

    performance_eval = PerformanceEval(
        db=db,
        name=eval_run_input.name,
        func=run_component,
        num_iterations=eval_run_input.num_iterations or 10,
        warmup_runs=eval_run_input.warmup_runs,
        agent_id=agent.id if agent else None,
        team_id=team.id if team else None,
        model_id=model_id,
        model_provider=model_provider,
    )

    result = await performance_eval.arun(print_results=False, print_summary=False)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to run performance evaluation")

    eval_run = EvalSchema.from_performance_eval(
        performance_eval=performance_eval,
        result=result,
        agent_id=agent.id if agent else None,
        team_id=team.id if team else None,
        model_id=model_id,
        model_provider=model_provider,
    )

    # Restore original model after eval
    if default_model is not None:
        if agent is not None:
            agent.model = default_model
        elif team is not None:
            team.model = default_model

    return eval_run


async def run_reliability_eval(
    eval_run_input: EvalRunInput,
    db: Union[BaseDb, AsyncBaseDb],
    agent: Optional[Agent] = None,
    team: Optional[Team] = None,
    default_model: Optional[Model] = None,
) -> EvalSchema:
    """Run a reliability evaluation for the given agent or team"""
    if eval_run_input.expected_tool_calls is None:
        raise HTTPException(status_code=400, detail="expected_tool_calls is required for reliability evaluations")

    if agent:
        agent_response = await agent.arun(eval_run_input.input, stream=False)  # type: ignore[misc]
        reliability_eval = ReliabilityEval(
            db=db,
            name=eval_run_input.name,
            agent_response=agent_response,
            expected_tool_calls=eval_run_input.expected_tool_calls,
            allow_additional_tool_calls=eval_run_input.allow_additional_tool_calls,
            expected_tool_call_arguments=eval_run_input.expected_tool_call_arguments,
        )
        model_id = agent.model.id if agent and agent.model else None
        model_provider = agent.model.provider if agent and agent.model else None

    elif team:
        team_response = await team.arun(eval_run_input.input, stream=False)  # type: ignore[misc]
        reliability_eval = ReliabilityEval(
            db=db,
            name=eval_run_input.name,
            team_response=team_response,
            expected_tool_calls=eval_run_input.expected_tool_calls,
            allow_additional_tool_calls=eval_run_input.allow_additional_tool_calls,
            expected_tool_call_arguments=eval_run_input.expected_tool_call_arguments,
        )
        model_id = team.model.id if team and team.model else None
        model_provider = team.model.provider if team and team.model else None

    result = await reliability_eval.arun(print_results=False)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to run reliability evaluation")

    eval_run = EvalSchema.from_reliability_eval(
        reliability_eval=reliability_eval,
        result=result,
        agent_id=agent.id if agent else None,
        team_id=team.id if team else None,
        model_id=model_id,
        model_provider=model_provider,
    )

    # Restore original model after eval
    if default_model is not None:
        if agent is not None:
            agent.model = default_model
        elif team is not None:
            team.model = default_model

    return eval_run


def build_registered_suite(
    eval_suite: EvalSuite,
    agents: Optional[List[Union[Agent, RemoteAgent]]],
    teams: Optional[List[Union[Team, RemoteTeam]]],
) -> EvalSuite:
    """Build a registered suite against a copy of its agent or team"""
    # create_fresh, as for the posted-body suite: the cases run on one copy for this request, never the
    # instance shared with live traffic. A registered suite runs exactly one registered agent or team.
    target = eval_suite.cases[0]
    if target.agent is not None:
        agent_id = cast(str, target.agent.id)
        fresh_agent = get_agent_by_id(agent_id=agent_id, agents=agents, create_fresh=True)
        if fresh_agent is None:
            raise HTTPException(status_code=404, detail=f"Agent with id '{agent_id}' not found")
        return replace(
            eval_suite, cases=tuple(replace(case, agent=cast(Agent, fresh_agent)) for case in eval_suite.cases)
        )
    team_id = cast(str, cast(Team, target.team).id)
    fresh_team = cast(Team, get_team_by_id(team_id=team_id, teams=teams, create_fresh=True))
    if fresh_team is None:
        raise HTTPException(status_code=404, detail=f"Team with id '{team_id}' not found")
    return replace(eval_suite, cases=tuple(replace(case, team=fresh_team) for case in eval_suite.cases))


def build_posted_suite(
    eval_suite_input: EvalSuiteInput,
    agent_id: Optional[str],
    team_id: Optional[str],
    agents: Optional[List[Union[Agent, RemoteAgent]]],
    teams: Optional[List[Union[Team, RemoteTeam]]],
) -> EvalSuite:
    """Build the suite posted in a body against a copy of its agent or team"""
    # create_fresh, as for a single eval: one copy for this request, never the shared instance.
    agent: Optional[Agent] = None
    team: Optional[Team] = None
    if agent_id:
        resolved_agent = get_agent_by_id(agent_id=agent_id, agents=agents, create_fresh=True)
        if resolved_agent is None:
            raise HTTPException(status_code=404, detail=f"Agent with id '{agent_id}' not found")
        if not isinstance(resolved_agent, Agent):
            raise HTTPException(status_code=501, detail="Eval suites are not supported for remote or external agents")
        agent = resolved_agent
    else:
        resolved_team = get_team_by_id(team_id=cast(str, team_id), teams=teams, create_fresh=True)
        if resolved_team is None:
            raise HTTPException(status_code=404, detail=f"Team with id '{team_id}' not found")
        if not isinstance(resolved_team, Team):
            raise HTTPException(status_code=501, detail="Eval suites are not supported for remote teams")
        team = resolved_team
    # A posted case names its judge as text; it is built here, as POST /eval-runs builds its model.
    judge_models: List[Optional[Model]] = []
    for case_input in eval_suite_input.cases:
        judge_model = None
        if case_input.judge_model_id and case_input.judge_model_provider:
            model_string = f"{case_input.judge_model_provider}:{case_input.judge_model_id}"
            try:
                judge_model = get_model(model_string)
            except Exception as e:
                raise HTTPException(status_code=422, detail=f"Invalid judge model '{model_string}': {e}")
        judge_models.append(judge_model)
    cases = tuple(
        Case(
            name=case_input.name,
            input=case_input.input,
            agent=agent,
            team=team,
            judge_model=judge_model,
            tags=tuple(case_input.tags),
            timeout_seconds=case_input.timeout_seconds,
            criteria=case_input.criteria,
            judge_mode=JudgeMode(case_input.judge_mode),
            judge_threshold=case_input.judge_threshold,
            expected_tool_calls=tuple(case_input.expected_tool_calls)
            if case_input.expected_tool_calls is not None
            else None,
            allow_additional_tool_calls=case_input.allow_additional_tool_calls,
            session_id=case_input.session_id,
            session_state=case_input.session_state,
            dependencies=case_input.dependencies,
            metadata=case_input.metadata,
            knowledge_filters=case_input.knowledge_filters,
        )
        for case_input, judge_model in zip(eval_suite_input.cases, judge_models)
    )
    # The posted suite exists for this request only, so it gets a throwaway id.
    return EvalSuite(id=str(uuid4()), name=eval_suite_input.name, cases=cases)


def apply_case_overrides(selected: Tuple[Case, ...], overrides: Dict[str, Any]) -> Tuple[Case, ...]:
    """Apply the request's overrides to the selected cases"""
    # Runtime-owned metadata keys (version stamp, dispatch lineage) are stripped as on the run routes,
    # so a posted case cannot forge them.
    return tuple(
        replace(
            case, **{**overrides, "metadata": strip_reserved_run_metadata(overrides.get("metadata", case.metadata))}
        )
        for case in selected
    )


async def astore_eval_suite_run_data(
    db: Union[BaseDb, AsyncBaseDb],
    eval_run_id: str,
    eval_data: Dict[str, Any],
    expected_attempt: Optional[int] = None,
) -> bool:
    """Replace the eval data of a background suite run; a run deleted meanwhile stays deleted.

    With expected_attempt, a database with a fenced eval-row write refuses it when a newer queue attempt owns
    the row, as update_run_in_session fences a queued run: returns False then. Other databases write as before.
    The sweep uses astore_eval_suite_run_data_outcome instead: it needs the typed outcome.
    """
    outcome = await astore_eval_suite_run_data_outcome(db, eval_run_id, eval_data, expected_attempt)
    return outcome not in (RunPersistOutcome.STALE_ATTEMPT, RunPersistOutcome.TERMINAL_REFUSED)


async def astore_eval_suite_run_data_outcome(
    db: Union[BaseDb, AsyncBaseDb],
    eval_run_id: str,
    eval_data: Dict[str, Any],
    expected_attempt: Optional[int] = None,
) -> RunPersistOutcome:
    """Replace the eval data of a background suite run and name what happened, as apersist_run_status does."""
    method = getattr(db, "update_eval_run_data_in_attempt", None) if expected_attempt is not None else None
    if callable(method):
        kwargs = dict(eval_run_id=eval_run_id, eval_data=eval_data, expected_attempt=expected_attempt)
        if isinstance(db, AsyncBaseDb):
            outcome = await method(**kwargs)
        else:
            outcome = await asyncio.to_thread(method, **kwargs)
        if outcome in (RunPersistOutcome.STALE_ATTEMPT, RunPersistOutcome.TERMINAL_REFUSED):
            log_warning(
                f"Dropped fenced-out eval run save: eval run {eval_run_id} attempt {expected_attempt} "
                f"({outcome.value}) - a newer attempt or a terminal row owns it"
            )
        return outcome
    if isinstance(db, AsyncBaseDb):
        await db.update_eval_run_data(eval_run_id=eval_run_id, eval_data=eval_data)
    else:
        db.update_eval_run_data(eval_run_id=eval_run_id, eval_data=eval_data)
    return RunPersistOutcome.UNAVAILABLE


async def aprepare_eval_suite_run(
    db: Union[BaseDb, AsyncBaseDb], running_record: EvalRunRecord, user_id: Optional[str]
) -> None:
    """Store a background suite run as running, owned by its caller"""
    # Written directly, not through async_log_eval: no model call has run yet, so a failed write is
    # answered as an error instead of a 202 for a run nobody can poll.
    if isinstance(db, AsyncBaseDb):
        created = await db.create_eval_run(running_record)
    else:
        created = db.create_eval_run(running_record)
    if created is None:
        raise HTTPException(status_code=500, detail="Could not store the eval suite run")
    if user_id is not None:
        try:
            if isinstance(db, AsyncBaseDb):
                await db.update_eval_run_user_id(eval_run_id=running_record.run_id, user_id=user_id)
            else:
                db.update_eval_run_user_id(eval_run_id=running_record.run_id, user_id=user_id)
        except Exception as e:
            log_error(f"Could not set owner on eval run {running_record.run_id}: {e}")
            raise HTTPException(status_code=500, detail="Could not store the eval suite run")


async def adelete_eval_suite_run(db: Union[BaseDb, AsyncBaseDb], eval_run_id: str) -> None:
    """Remove a background suite run whose row or owner could not be stored, best-effort"""
    with suppress(Exception):
        if isinstance(db, AsyncBaseDb):
            await db.delete_eval_runs(eval_run_ids=[eval_run_id])
        else:
            db.delete_eval_runs(eval_run_ids=[eval_run_id])


async def aprepare_eval_suite_accepted_or_abort(
    queue_worker: Any,
    db: Union[BaseDb, AsyncBaseDb],
    running_record: EvalRunRecord,
    user_id: Optional[str],
    component_id: str,
) -> None:
    """Prepare a queued suite run after its enqueue, as aprepare_accepted_or_abort prepares a queued run: on
    failure the still-waiting ticket is cancelled and the error raised, or, when a worker already claimed it,
    the failure is swallowed, since the worker's claim-time ensure owns the row."""
    try:
        # A worker that already claimed the job wins: its row is never overwritten by this create.
        if await aread_eval_suite_run(db, running_record.run_id) is None:
            await aprepare_eval_suite_run(db, running_record, user_id)
    except Exception as e:
        cancelled = False
        with suppress(Exception):
            cancelled = bool(await queue_worker.store.cancel_job(running_record.run_id))
        if not cancelled:
            log_warning(
                f"Run {running_record.run_id}: accept-time prepare failed ({e}) but the ticket is already "
                "claimed - acknowledging; the worker's claim-time ensure owns the run row"
            )
            return
        # The poll is scoped to the owner, so a run whose owner was not stored could never be read
        # back: it is removed and refused, where the synchronous run keeps it.
        await adelete_eval_suite_run(db, running_record.run_id)
        log_error(f"Run {running_record.run_id}: acceptance aborted - run-row prepare failed ({e}); ticket cancelled")
        raise HTTPException(
            status_code=500,
            detail=f"Run acceptance aborted: the run row could not be prepared ({type(e).__name__}); "
            "the queued job was cancelled and will not execute. Retry the submission.",
        )

    log_info(f"Eval suite queued: {component_id} run={running_record.run_id}")


async def aread_eval_suite_run(
    db: Union[BaseDb, AsyncBaseDb], eval_run_id: str, user_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Read an eval run row as a dict, or None when it is missing or, with user_id, owned by another user."""
    if isinstance(db, AsyncBaseDb):
        eval_run = await db.get_eval_run(eval_run_id=eval_run_id, deserialize=False, user_id=user_id)
    else:
        eval_run = db.get_eval_run(eval_run_id=eval_run_id, deserialize=False, user_id=user_id)
    return cast(Optional[Dict[str, Any]], eval_run)


async def arun_eval_suite_cases(
    selected: Tuple[Case, ...],
    default_timeout: int,
    eval_run_id: str,
    finished: List[CaseResult],
    cancellation_poll_interval: float = 0.5,
) -> SuiteResult:
    """Run the cases of a suite run, raising RunCancelledException when the run is cancelled"""
    # Each case runs its agent or team under its own run id, so the suite's cancellation is polled while the
    # cases run, as background_run_slot polls it while a run waits for a slot. Each finished case is kept in
    # finished, so a run that stops early keeps them.
    # No db= here, as in the synchronous run: the suite record carries every case's result.
    cases_task = asyncio.ensure_future(
        arun_cases(
            selected,
            default_timeout=default_timeout,
            on_case_end=lambda case, result: finished.append(result),
        )
    )
    try:
        while True:
            done, _ = await asyncio.wait({cases_task}, timeout=cancellation_poll_interval)
            if cases_task in done:
                return cases_task.result()
            if await ais_cancelled(eval_run_id):
                raise RunCancelledException(eval_run_id)
    except BaseException:
        cases_task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await cases_task
        raise


async def arun_queued_eval_suite(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    agents: Optional[List[Union[Agent, RemoteAgent]]],
    teams: Optional[List[Union[Team, RemoteTeam]]],
    eval_suites: Optional[List[EvalSuite]],
    job: Dict[str, Any],
    holds_lease: Callable[[], Awaitable[bool]],
    cancellation_poll_interval: float = 0.5,
) -> Optional[bool]:
    """Run a background suite run claimed from the durable queue and replace its running row with the result.

    The suite is rebuilt from the ticket, as the worker rebuilds a queued agent run: the registered suite by
    id, or the posted body. Returns True when the row holds a finished result, False when this replica
    cannot reach the suite or its agent or team, and None when the row cannot be ensured or the lease is
    lost; on False and None the claim is left for one that can. A failure raises, so the worker retries it
    or marks the row ERROR, as for a run; a suite the ticket cannot rebuild raises EvalError, and a cancelled
    run raises RunCancelledException.
    """
    payload = job.get("payload") or {}
    # A run deleted while its ticket was claimed is never recreated: the delete registered its cancellation.
    if await ais_cancelled(job["id"]):
        raise RunCancelledException(job["id"])
    try:
        db = cast(Union[BaseDb, AsyncBaseDb], await get_db(dbs, payload.get("db_id"), payload.get("table")))
        eval_run = await aread_eval_suite_run(db, job["id"])
        if eval_run is None and job.get("attempt", 1) > 1:
            # Attempt 1 ensured this row before running, so a row missing on a later attempt was deleted: it is
            # never recreated. The cancelled write comes first, so a read error that reads as a missing row
            # raises here and leaves the claim.
            record_eval_data = payload["record"]["eval_data"]
            await astore_eval_suite_run_data(
                db,
                job["id"],
                {**record_eval_data, "summary": {**record_eval_data["summary"], "status": "CANCELLED"}},
            )
            raise RunCancelledException(job["id"])
        if eval_run is None:
            # The row must exist before the suite runs: the ticket commits the acceptance, but the accepting
            # request's prepare can fail or die between the two writes, as for a queued run. A create that
            # loses to the accepting request's own write is re-read, as an insert-if-absent run row is.
            with suppress(Exception):
                await aprepare_eval_suite_run(db, EvalRunRecord.model_validate(payload["record"]), job.get("user_id"))
            if await ais_cancelled(job["id"]):
                # Deleted while the row was being ensured: the created row is removed, never brought back.
                with suppress(Exception):
                    await adelete_eval_suite_run(db, job["id"])
                raise RunCancelledException(job["id"])
            eval_run = await aread_eval_suite_run(db, job["id"])
        if eval_run is not None and job.get("user_id") is not None and eval_run.get("user_id") != job["user_id"]:
            # The poll is scoped to the owner, so a row whose owner write failed on either side is owned here
            # before the suite runs; a failure leaves the claim, never an ownerless run nobody can poll.
            if isinstance(db, AsyncBaseDb):
                await db.update_eval_run_user_id(eval_run_id=job["id"], user_id=job["user_id"])
            else:
                db.update_eval_run_user_id(eval_run_id=job["id"], user_id=job["user_id"])
    except RunCancelledException:
        raise
    except Exception as e:
        log_error(
            f"Job queue: could not ensure the run row for claimed job {job['id']} ({e}); "
            "leaving the claim to go stale so a later attempt can retry"
        )
        return None
    if eval_run is None:
        log_error(
            f"Job queue: could not ensure the run row for claimed job {job['id']}; "
            "leaving the claim to go stale so a later attempt can retry"
        )
        return None
    status = ((eval_run.get("eval_data") or {}).get("summary") or {}).get("status")
    if status in ("PASS", "FAIL"):
        # An earlier attempt stored the result and stopped before settling: it is kept, as a run ticket honors
        # a terminal run row.
        return True
    if status == "CANCELLED":
        # Cancelled after the claim's read or while the ticket waited: it is not run, and its ticket tombstones.
        raise RunCancelledException(job["id"])
    if status == "ERROR":
        if not await holds_lease():
            return None
        # Requeued by an operator: RUNNING again while it runs, as a requeued run's row is.
        if not await astore_eval_suite_run_data(
            db, job["id"], payload["record"]["eval_data"], expected_attempt=job.get("attempt")
        ):
            return None
    elif callable(getattr(db, "update_eval_run_data_in_attempt", None)):
        # Establish this attempt's generation on the row BEFORE executing, as the run path stamps queue_attempt:
        # the fence compares later writes against it.
        if not await astore_eval_suite_run_data(
            db, job["id"], eval_run.get("eval_data") or {}, expected_attempt=job.get("attempt")
        ):
            return None
    try:
        if payload.get("suite_id") is not None:
            eval_suite = get_eval_suite_by_id(payload["suite_id"], eval_suites)
            if eval_suite is None:
                return False
            eval_suite = build_registered_suite(eval_suite, agents, teams)
        else:
            eval_suite_input = EvalSuiteInput.model_validate(payload["suite"])
            eval_suite = build_posted_suite(
                eval_suite_input,
                eval_suite_input.cases[0].agent_id or None,
                eval_suite_input.cases[0].team_id or None,
                agents,
                teams,
            )
    except HTTPException as e:
        if e.status_code == 404:
            return False
        raise EvalError(e.detail) from e
    except ValueError as e:
        raise EvalError(str(e)) from e
    selected = eval_suite.select(tag=payload.get("tag"), name=payload.get("case_name"))
    if not selected:
        raise EvalError("No cases match the given tag or name")
    selected = apply_case_overrides(selected, payload.get("overrides") or {})
    finished: List[CaseResult] = []
    try:
        suite_result = await arun_eval_suite_cases(
            selected, payload["default_timeout"], job["id"], finished, cancellation_poll_interval
        )
    except RunCancelledException:
        # Cancelled or deleted while its cases ran: the row is marked CANCELLED with the cases that finished, as
        # the in-process run marks it, and a deleted run stays deleted.
        if await holds_lease():
            with suppress(Exception):
                await astore_eval_suite_run_data(
                    db,
                    job["id"],
                    aborted_eval_suite_data(selected, finished, "CANCELLED"),
                    expected_attempt=job.get("attempt"),
                )
        raise
    if not await holds_lease():
        # Another worker owns the ticket now: anything written here would contradict its record.
        return None
    if not await astore_eval_suite_run_data(
        db, job["id"], eval_suite_result_data(suite_result), expected_attempt=job.get("attempt")
    ):
        return None
    return True


def eval_suite_result_data(suite_result: SuiteResult) -> Dict[str, Any]:
    """The eval data of a suite run whose cases ran; CANCELLED when a cancelled case run aborted it"""
    eval_data = suite_result.to_dict()
    # A case's own run cancelled (POST /agents/{agent_id}/runs/{run_id}/cancel) aborts the suite, as arun_cases
    # does, so the run reads as cancelled, not failed: the scheduler does not retry it.
    if any(
        result.response is not None and result.response.status == RunStatus.cancelled for result in suite_result.results
    ):
        eval_data["summary"]["status"] = "CANCELLED"
    return eval_data


def aborted_eval_suite_data(
    selected: Tuple[Case, ...], finished: List[CaseResult], status: str, error: Optional[str] = None
) -> Dict[str, Any]:
    """The eval data of a suite run that stopped early: the cases that finished, then the rest skipped"""
    # Every selected case is accounted for, as arun_cases records the cases a cancelled run leaves.
    results = list(finished) + [
        CaseResult(
            name=case.name,
            tags=case.tags,
            agent_id=_component_id(case) if case.agent is not None else None,
            team_id=_component_id(case) if case.team is not None else None,
            skipped=True,
            error=f"skipped: suite aborted after {'cancelled' if status == 'CANCELLED' else 'failed'} run",
        )
        for case in selected[len(finished) :]
    ]
    eval_data = SuiteResult(results=results).to_dict()
    eval_data["summary"]["status"] = status
    if error is not None:
        eval_data["error"] = error
    return eval_data


async def aread_queued_eval_suite_status(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], job: Dict[str, Any]
) -> Optional[str]:
    """Read the suite status on a queued suite run's row, or None (never raises) when the row cannot be read."""
    payload = job.get("payload") or {}
    try:
        db = cast(Union[BaseDb, AsyncBaseDb], await get_db(dbs, payload.get("db_id"), payload.get("table")))
        eval_run = await aread_eval_suite_run(db, job["id"])
    except Exception:
        return None
    if eval_run is None:
        return None
    return ((eval_run.get("eval_data") or {}).get("summary") or {}).get("status")


async def ais_deleted_queued_eval_suite(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]], job: Dict[str, Any]
) -> Optional[bool]:
    """Tell whether a queued suite run past its first attempt was deleted: attempt 1 ensured its row, so a row
    missing later was deleted. True when the row is gone, False when it is there, and None (never raises) when
    it cannot be told: the cancelled write comes first, so a read error that reads as a missing row is None."""
    payload = job.get("payload") or {}
    try:
        db = cast(Union[BaseDb, AsyncBaseDb], await get_db(dbs, payload.get("db_id"), payload.get("table")))
        if await aread_eval_suite_run(db, job["id"]) is not None:
            return False
        record_eval_data = payload["record"]["eval_data"]
        await astore_eval_suite_run_data(
            db,
            job["id"],
            {**record_eval_data, "summary": {**record_eval_data["summary"], "status": "CANCELLED"}},
        )
        return True
    except Exception as e:
        log_warning(f"Job queue: run-row error persist failed for job {job.get('id')}: {e}")
        return None


async def afail_queued_eval_suite(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    job: Dict[str, Any],
    error: str,
    create_missing: bool = False,
    missing_ok: bool = False,
    status: str = "ERROR",
) -> bool:
    """Persist ERROR on a queued suite run's row so pollers see it, never a stuck RUNNING.

    Returns True when the row is KNOWN not to be stuck: written now, or already finished. Returns False
    (never raises) when the row could not be read or written - callers must NOT terminalize the queue ticket
    on False, or the row is orphaned RUNNING forever with nothing left to revisit it. A missing row is
    False, since a database read error can read as one, unless create_missing writes it as ERROR from the
    ticket's record, as the sweep settles a run with no row: a create that fails is False too. With
    missing_ok, a missing row is True: a cancelled run's row is gone because the run was deleted. The sweep
    uses afail_queued_eval_suite_outcome instead: it needs the typed outcome (TERMINAL_REFUSED = the suite
    finished, reconcile rather than fail)."""
    return await afail_queued_eval_suite_outcome(dbs, job, error, create_missing, missing_ok, status) is not None


async def afail_queued_eval_suite_outcome(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    job: Dict[str, Any],
    error: str,
    create_missing: bool = False,
    missing_ok: bool = False,
    status: str = "ERROR",
) -> Optional[RunPersistOutcome]:
    """Persist ERROR (or, with status, CANCELLED) on a queued suite run's row and name the outcome, as
    _persist_run_error_outcome does for a run: TERMINAL_REFUSED when the row is already PASS or FAIL,
    STALE_ATTEMPT when a newer attempt owns it, MISSING when a deleted run's row is gone, None when the row
    could not be read or written. A CANCELLED row carries no error, as the in-process run writes it."""
    failure: Dict[str, Any] = {"error": error} if status == "ERROR" else {}
    payload = job.get("payload") or {}
    try:
        db = cast(Union[BaseDb, AsyncBaseDb], await get_db(dbs, payload.get("db_id"), payload.get("table")))
        eval_run = await aread_eval_suite_run(db, job["id"])
        if eval_run is None:
            if missing_ok:
                return RunPersistOutcome.MISSING
            if not create_missing:
                return None
            record = EvalRunRecord.model_validate(payload["record"])
            eval_data = record.eval_data or {}
            record.eval_data = {**eval_data, "summary": {**eval_data["summary"], "status": status}, **failure}
            await aprepare_eval_suite_run(db, record, job.get("user_id"))
            return RunPersistOutcome.UPDATED
        eval_data = eval_run.get("eval_data") or {}
        row_status = (eval_data.get("summary") or {}).get("status")
        if row_status in ("PASS", "FAIL"):
            return RunPersistOutcome.TERMINAL_REFUSED
        if row_status != "RUNNING":
            return RunPersistOutcome.UPDATED
        # A newer attempt that owns the row fences this write out: the row is that attempt's, not stuck.
        return await astore_eval_suite_run_data_outcome(
            db,
            job["id"],
            {**eval_data, "summary": {**eval_data["summary"], "status": status}, **failure},
            expected_attempt=job.get("attempt"),
        )
    except Exception as e:
        log_warning(f"Job queue: run-row error persist failed for job {job.get('id')}: {e}")
        return None
