import asyncio
from contextlib import suppress
from dataclasses import replace
from typing import Any, Dict, List, Optional, Tuple, Union, cast
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
from agno.eval.suite import Case, EvalSuite, JudgeMode, SuiteResult, arun_cases
from agno.exceptions import RunCancelledException
from agno.models.base import Model
from agno.models.utils import get_model
from agno.os.routers.evals.schemas import EvalRunInput, EvalSchema, EvalSuiteInput
from agno.os.utils import get_agent_by_id, get_team_by_id
from agno.run.cancel import ais_cancelled
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error


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
        fresh_agent = cast(
            Agent, get_agent_by_id(agent_id=cast(str, target.agent.id), agents=agents, create_fresh=True)
        )
        return replace(eval_suite, cases=tuple(replace(case, agent=fresh_agent) for case in eval_suite.cases))
    fresh_team = cast(
        Team, get_team_by_id(team_id=cast(str, cast(Team, target.team).id), teams=teams, create_fresh=True)
    )
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
    db: Union[BaseDb, AsyncBaseDb], eval_run_id: str, eval_data: Dict[str, Any]
) -> None:
    """Replace the eval data of a background suite run; a run deleted meanwhile stays deleted"""
    if isinstance(db, AsyncBaseDb):
        await db.update_eval_run_data(eval_run_id=eval_run_id, eval_data=eval_data)
    else:
        db.update_eval_run_data(eval_run_id=eval_run_id, eval_data=eval_data)


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


async def aread_eval_suite_run(
    db: Union[BaseDb, AsyncBaseDb], eval_run_id: str, user_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Read an eval run row as a dict, or None when it is missing or, with user_id, owned by another user"""
    if isinstance(db, AsyncBaseDb):
        eval_run = await db.get_eval_run(eval_run_id=eval_run_id, deserialize=False, user_id=user_id)
    else:
        eval_run = db.get_eval_run(eval_run_id=eval_run_id, deserialize=False, user_id=user_id)
    return cast(Optional[Dict[str, Any]], eval_run)


async def arun_eval_suite_cases(
    selected: Tuple[Case, ...], default_timeout: int, eval_run_id: str, cancellation_poll_interval: float = 0.5
) -> SuiteResult:
    """Run the cases of a background suite run, raising RunCancelledException when the run is deleted"""
    # Each case runs its agent or team under its own run id, so the suite's cancellation is polled while the
    # cases run, as background_run_slot polls it while a run waits for a slot.
    # No db= here, as in the synchronous run: the suite record carries every case's result.
    cases_task = asyncio.ensure_future(arun_cases(selected, default_timeout=default_timeout))
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
