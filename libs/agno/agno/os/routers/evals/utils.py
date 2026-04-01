from typing import Optional, Union

from fastapi import HTTPException

from agno.agent import Agent, RemoteAgent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.eval.accuracy import AccuracyEval
from agno.eval.agent_as_judge import AgentAsJudgeEval
from agno.eval.performance import PerformanceEval
from agno.eval.reliability import ReliabilityEval
from agno.models.base import Model
from agno.os.routers.evals.schemas import EvalRunInput, EvalSchema
from agno.team import RemoteTeam, Team


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
    if not eval_run_input.expected_tool_calls:
        raise HTTPException(status_code=400, detail="expected_tool_calls is required for reliability evaluations")

    if agent:
        agent_response = await agent.arun(eval_run_input.input, stream=False)  # type: ignore[misc]
        reliability_eval = ReliabilityEval(
            db=db,
            name=eval_run_input.name,
            agent_response=agent_response,
            expected_tool_calls=eval_run_input.expected_tool_calls,
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
