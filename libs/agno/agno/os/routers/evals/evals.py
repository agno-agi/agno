import logging
from copy import deepcopy
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from agno.agent.agent import Agent
from agno.db.base import BaseDb
from agno.db.schemas.evals import EvalFilterType, EvalType
from agno.models.utils import get_model
from agno.os.auth import get_authentication_dependency
from agno.os.routers.evals.schemas import (
    DeleteEvalRunsRequest,
    EvalRunInput,
    EvalSchema,
    UpdateEvalRunRequest,
)
from agno.os.routers.evals.utils import run_accuracy_eval, run_performance_eval, run_reliability_eval
from agno.os.schema import PaginatedResponse, PaginationInfo, SortOrder
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_agent_by_id, get_db, get_team_by_id
from agno.team.team import Team

logger = logging.getLogger(__name__)


def get_eval_router(
    dbs: dict[str, BaseDb],
    agents: Optional[List[Agent]] = None,
    teams: Optional[List[Team]] = None,
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    router = APIRouter(dependencies=[Depends(get_authentication_dependency(settings))], tags=["Evals"])
    return attach_routes(router=router, dbs=dbs, agents=agents, teams=teams)


def attach_routes(
    router: APIRouter, dbs: dict[str, BaseDb], agents: Optional[List[Agent]] = None, teams: Optional[List[Team]] = None
) -> APIRouter:
    @router.get("/eval-runs", response_model=PaginatedResponse[EvalSchema], status_code=200)
    async def get_eval_runs(
        agent_id: Optional[str] = Query(default=None, description="Agent ID"),
        team_id: Optional[str] = Query(default=None, description="Team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Workflow ID"),
        model_id: Optional[str] = Query(default=None, description="Model ID"),
        filter_type: Optional[EvalFilterType] = Query(default=None, description="Filter type", alias="type"),
        eval_types: Optional[List[EvalType]] = Depends(parse_eval_types_filter),
        limit: Optional[int] = Query(default=20, description="Number of eval runs to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> PaginatedResponse[EvalSchema]:
        db = get_db(dbs, db_id)
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
            data=[EvalSchema.from_dict(eval_run) for eval_run in eval_runs],  # type: ignore
            meta=PaginationInfo(
                page=page,
                limit=limit,
                total_count=total_count,  # type: ignore
                total_pages=(total_count + limit - 1) // limit if limit is not None and limit > 0 else 0,  # type: ignore
            ),
        )

    @router.get("/eval-runs/{eval_run_id}", response_model=EvalSchema, status_code=200)
    async def get_eval_run(
        eval_run_id: str,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> EvalSchema:
        db = get_db(dbs, db_id)
        eval_run = db.get_eval_run(eval_run_id=eval_run_id, deserialize=False)
        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)  # type: ignore

    @router.delete("/eval-runs", status_code=204)
    async def delete_eval_runs(
        request: DeleteEvalRunsRequest,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> None:
        try:
            db = get_db(dbs, db_id)
            db.delete_eval_runs(eval_run_ids=request.eval_run_ids)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete eval runs: {e}")

    @router.patch("/eval-runs/{eval_run_id}", response_model=EvalSchema, status_code=200)
    async def update_eval_run(
        eval_run_id: str,
        request: UpdateEvalRunRequest,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> EvalSchema:
        try:
            db = get_db(dbs, db_id)
            eval_run = db.rename_eval_run(eval_run_id=eval_run_id, name=request.name, deserialize=False)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to rename eval run: {e}")

        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)  # type: ignore

    @router.post("/eval-runs", response_model=EvalSchema, status_code=200)
    async def run_eval(
        eval_run_input: EvalRunInput,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> Optional[EvalSchema]:
        db = get_db(dbs, db_id)

        if eval_run_input.agent_id and eval_run_input.team_id:
            raise HTTPException(status_code=400, detail="Only one of agent_id or team_id must be provided")

        if eval_run_input.agent_id:
            agent = get_agent_by_id(agent_id=eval_run_input.agent_id, agents=agents)
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent with id '{eval_run_input.agent_id}' not found")

            default_model = None
            if (
                hasattr(agent, "model")
                and agent.model is not None
                and eval_run_input.model_id is not None
                and eval_run_input.model_provider is not None
            ):
                default_model = deepcopy(agent.model)
                if eval_run_input.model_id != agent.model.id or eval_run_input.model_provider != agent.model.provider:
                    model = get_model(
                        model_id=eval_run_input.model_id.lower(),
                        model_provider=eval_run_input.model_provider.lower(),
                    )
                    agent.model = model

            team = None

        elif eval_run_input.team_id:
            team = get_team_by_id(team_id=eval_run_input.team_id, teams=teams)
            if not team:
                raise HTTPException(status_code=404, detail=f"Team with id '{eval_run_input.team_id}' not found")

            default_model = None
            if (
                hasattr(team, "model")
                and team.model is not None
                and eval_run_input.model_id is not None
                and eval_run_input.model_provider is not None
            ):
                default_model = deepcopy(team.model)
                if eval_run_input.model_id != team.model.id or eval_run_input.model_provider != team.model.provider:
                    model = get_model(
                        model_id=eval_run_input.model_id.lower(),
                        model_provider=eval_run_input.model_provider.lower(),
                    )
                    team.model = model

            agent = None

        else:
            raise HTTPException(status_code=400, detail="One of agent_id or team_id must be provided")

        # Run the evaluation
        if eval_run_input.eval_type == EvalType.ACCURACY:
            return await run_accuracy_eval(
                eval_run_input=eval_run_input, db=db, agent=agent, team=team, default_model=default_model
            )

        elif eval_run_input.eval_type == EvalType.PERFORMANCE:
            return await run_performance_eval(
                eval_run_input=eval_run_input, db=db, agent=agent, team=team, default_model=default_model
            )

        else:
            return await run_reliability_eval(
                eval_run_input=eval_run_input, db=db, agent=agent, team=team, default_model=default_model
            )

    return router


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
