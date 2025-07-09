from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from agno.agent.agent import Agent
from agno.db.base import BaseDb
from agno.eval.accuracy import AccuracyEval
from agno.eval.performance import PerformanceEval
from agno.eval.reliability import ReliabilityEval
from agno.eval.schemas import EvalFilterType, EvalType
from agno.os.managers.eval.schemas import (
    AccuracyEvalInput,
    DeleteEvalRunsRequest,
    EvalSchema,
    PerformanceEvalInput,
    ReliabilityEvalInput,
    UpdateEvalRunRequest,
)
from agno.os.managers.utils import PaginatedResponse, PaginationInfo, SortOrder
from agno.os.utils import get_agent_by_id
from agno.run.response import RunResponse
from agno.team.team import Team


def parse_eval_types_filter(
    eval_types: Optional[str] = Query(default=None, description="Comma-separated eval types"),
) -> Optional[List[EvalType]]:
    """Parse a comma-separated string of eval types into a list of EvalType enums"""
    if not eval_types:
        return None
    try:
        return [EvalType(item.strip()) for item in eval_types.split(",")]
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"Invalid eval_type: {e}")


def attach_routes(router: APIRouter, db: BaseDb, agents: List[Agent], teams: List[Team]) -> APIRouter:
    @router.get("/eval-runs", response_model=PaginatedResponse[EvalSchema], status_code=200)
    async def get_eval_runs(
        agent_id: Optional[str] = Query(default=None, description="Agent ID"),
        team_id: Optional[str] = Query(default=None, description="Team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Workflow ID"),
        model_id: Optional[str] = Query(default=None, description="Model ID"),
        filter_type: Optional[EvalFilterType] = Query(default=None, description="Filter type"),
        eval_types: Optional[List[EvalType]] = Depends(parse_eval_types_filter),
        limit: Optional[int] = Query(default=20, description="Number of eval runs to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
    ) -> PaginatedResponse[EvalSchema]:
        eval_runs, total_count = db.get_eval_runs_raw(
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=workflow_id,
            model_id=model_id,
            eval_type=eval_types,
            filter_type=filter_type,
        )

        return PaginatedResponse(
            data=[EvalSchema.from_dict(eval_run) for eval_run in eval_runs],
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=total_count,
                total_pages=(total_count + limit - 1) // limit if limit is not None and limit > 0 else 0,
            ),
        )

    @router.get("/eval-runs/{eval_run_id}", response_model=EvalSchema, status_code=200)
    async def get_eval_run(eval_run_id: str) -> EvalSchema:
        eval_run = db.get_eval_run_raw(eval_run_id=eval_run_id)
        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)

    @router.delete("/eval-runs", status_code=204)
    async def delete_eval_runs(request: DeleteEvalRunsRequest) -> None:
        try:
            db.delete_eval_runs(eval_run_ids=request.eval_run_ids)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete eval runs: {e}")

    @router.patch("/eval-runs/{eval_run_id}", response_model=EvalSchema, status_code=200)
    async def update_eval_run(eval_run_id: str, request: UpdateEvalRunRequest) -> EvalSchema:
        try:
            eval_run = db.rename_eval_run(eval_run_id=eval_run_id, name=request.name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to rename eval run: {e}")

        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)

    @router.post("/eval-runs/accuracy", response_model=EvalSchema, status_code=200)
    async def run_accuracy_eval(agent_id: str, accuracy_eval_input: AccuracyEvalInput) -> EvalSchema:
        agent = get_agent_by_id(agent_id=agent_id, agents=agents)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with id '{agent_id}' not found")

        accuracy_eval = AccuracyEval(
            db=db,
            agent=agent,  # type: ignore
            input=accuracy_eval_input.input,
            expected_output=accuracy_eval_input.expected_output,
            additional_guidelines=accuracy_eval_input.additional_guidelines,
            num_iterations=accuracy_eval_input.num_iterations or 1,
            name=accuracy_eval_input.name,
        )
        result = accuracy_eval.run(print_results=False, print_summary=False)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to run accuracy evaluation")

        return EvalSchema.from_accuracy_result(result)

    @router.post("/eval-runs/performance", response_model=EvalSchema, status_code=200)
    async def run_performance_eval(agent_id: str, performance_eval_input: PerformanceEvalInput) -> EvalSchema:
        agent = get_agent_by_id(agent_id=agent_id, agents=agents)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with id '{agent_id}' not found")

        def run_component() -> RunResponse:
            return agent.run(performance_eval_input.input)

        performance_eval = PerformanceEval(
            db=db,
            name=performance_eval_input.name,
            func=run_component,
            num_iterations=performance_eval_input.num_iterations or 10,
            warmup_runs=performance_eval_input.warmup_runs,
        )
        result = performance_eval.run(print_results=False, print_summary=False)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to run performance evaluation")

        return EvalSchema.from_performance_result(result)

    @router.post("/eval-runs/reliability", response_model=EvalSchema, status_code=200)
    async def run_reliability_eval(agent_id: str, reliability_eval_input: ReliabilityEvalInput) -> EvalSchema:
        agent = get_agent_by_id(agent_id=agent_id, agents=agents)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent with id '{agent_id}' not found")

        agent_response = agent.run(reliability_eval_input.input)

        reliability_eval = ReliabilityEval(
            db=db,
            name=reliability_eval_input.name,
            agent_response=agent_response,
            expected_tool_calls=reliability_eval_input.expected_tool_calls,
        )
        result = reliability_eval.run(print_results=False)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to run reliability evaluation")

        return EvalSchema.from_reliability_result(result)

    return router
