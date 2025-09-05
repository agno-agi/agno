from typing import Optional, Union

from fastapi import HTTPException

from agno.agent.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.eval.accuracy import AccuracyEval
from agno.eval.performance import PerformanceEval
from agno.eval.reliability import ReliabilityEval
from agno.models.base import Model
from agno.os.routers.evals.schemas import EvalRunInput, EvalSchema
from agno.team.team import Team


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
    )

    result = accuracy_eval.run(print_results=False, print_summary=False)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to run accuracy evaluation")

    eval_run = EvalSchema.from_accuracy_eval(accuracy_eval=accuracy_eval, result=result)

    if default_model is not None:
        if agent is not None:
            agent.model = default_model
        elif team is not None:
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

        def run_component():  # type: ignore
            return agent.run(eval_run_input.input)

        model_id = agent.model.id if agent and agent.model else None
        model_provider = agent.model.provider if agent and agent.model else None

    elif team:

        def run_component():
            return team.run(eval_run_input.input)

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
    result = performance_eval.run(print_results=False, print_summary=False)
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
    if not eval_run_input.expected_tool_calls:
        raise HTTPException(status_code=400, detail="expected_tool_calls is required for reliability evaluations")

    if agent:
        agent_response = agent.run(eval_run_input.input)
        reliability_eval = ReliabilityEval(
            db=db,
            name=eval_run_input.name,
            agent_response=agent_response,
            expected_tool_calls=eval_run_input.expected_tool_calls,
        )
        model_id = agent.model.id if agent and agent.model else None
        model_provider = agent.model.provider if agent and agent.model else None

    elif team:
        team_response = team.run(eval_run_input.input)
        reliability_eval = ReliabilityEval(
            db=db,
            name=eval_run_input.name,
            team_response=team_response,
            expected_tool_calls=eval_run_input.expected_tool_calls,
        )
        model_id = team.model.id if team and team.model else None
        model_provider = team.model.provider if team and team.model else None

    result = reliability_eval.run(print_results=False)
    if not result:
        raise HTTPException(status_code=500, detail="Failed to run reliability evaluation")

    eval_run = EvalSchema.from_reliability_eval(
        reliability_eval=reliability_eval,
        result=result,
        agent_id=agent.id if agent else None,
        model_id=model_id,
        model_provider=model_provider,
    )

    if default_model is not None:
        if agent is not None:
            agent.model = default_model
        elif team is not None:
            team.model = default_model

    return eval_run
