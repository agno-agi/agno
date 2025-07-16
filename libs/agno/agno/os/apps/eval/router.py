from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from agno.agent.agent import Agent
from agno.db.base import BaseDb
from agno.db.schemas.evals import EvalFilterType, EvalType
from agno.os.apps.eval.schemas import (
    DeleteEvalRunsRequest,
    EvalRunInput,
    EvalSchema,
    UpdateEvalRunRequest,
)
from agno.os.apps.eval.utils import run_accuracy_eval, run_performance_eval, run_reliability_eval
from agno.os.apps.utils import PaginatedResponse, PaginationInfo, SortOrder
from agno.os.utils import get_agent_by_id, get_team_by_id
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


def attach_routes(
    router: APIRouter, db: BaseDb, agents: Optional[List[Agent]] = None, teams: Optional[List[Team]] = None
) -> APIRouter:
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
        eval_runs, total_count = db.get_eval_runs(
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
            deserialize=False,
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
        eval_run = db.get_eval_run(eval_run_id=eval_run_id, deserialize=False)
        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)  # type: ignore

    @router.delete("/eval-runs", status_code=204)
    async def delete_eval_runs(request: DeleteEvalRunsRequest) -> None:
        try:
            db.delete_eval_runs(eval_run_ids=request.eval_run_ids)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete eval runs: {e}")

    @router.patch("/eval-runs/{eval_run_id}", response_model=EvalSchema, status_code=200)
    async def update_eval_run(eval_run_id: str, request: UpdateEvalRunRequest) -> EvalSchema:
        try:
            eval_run = db.rename_eval_run(eval_run_id=eval_run_id, name=request.name, deserialize=False)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to rename eval run: {e}")

        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)  # type: ignore

    @router.post("/eval-runs", response_model=EvalSchema, status_code=200)
    async def run_eval(eval_run_input: EvalRunInput) -> Optional[EvalSchema]:
        if eval_run_input.agent_id and eval_run_input.team_id:
            raise HTTPException(status_code=400, detail="Only one of agent_id or team_id must be provided")

        if eval_run_input.agent_id:
            agent = get_agent_by_id(agent_id=eval_run_input.agent_id, agents=agents)
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent with id '{eval_run_input.agent_id}' not found")
            team = None

        elif eval_run_input.team_id:
            team = get_team_by_id(team_id=eval_run_input.team_id, teams=teams)
            if not team:
                raise HTTPException(status_code=404, detail=f"Team with id '{eval_run_input.team_id}' not found")
            agent = None

        else:
            raise HTTPException(status_code=400, detail="One of agent_id or team_id must be provided")

        # Run the evaluation
        if eval_run_input.eval_type == EvalType.ACCURACY:
            return await run_accuracy_eval(eval_run_input=eval_run_input, db=db, agent=agent, team=team)

        elif eval_run_input.eval_type == EvalType.PERFORMANCE:
            return await run_performance_eval(eval_run_input=eval_run_input, db=db, agent=agent, team=team)

        elif eval_run_input.eval_type == EvalType.RELIABILITY:
            return await run_reliability_eval(eval_run_input=eval_run_input, db=db, agent=agent, team=team)

    return router
