import logging
from copy import deepcopy
from typing import List, Optional, Union, cast

from fastapi import APIRouter, Depends, HTTPException, Query

from agno.agent.agent import Agent
from agno.db.base import AsyncBaseDb, BaseDb
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
from agno.os.schema import (
    BadRequestResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    PaginatedResponse,
    PaginationInfo,
    SortOrder,
    UnauthenticatedResponse,
    ValidationErrorResponse,
)
from agno.os.settings import AgnoAPISettings
from agno.os.utils import get_agent_by_id, get_db, get_team_by_id
from agno.team.team import Team

logger = logging.getLogger(__name__)


def get_eval_router(
    dbs: dict[str, Union[BaseDb, AsyncBaseDb]],
    agents: Optional[List[Agent]] = None,
    teams: Optional[List[Team]] = None,
    settings: AgnoAPISettings = AgnoAPISettings(),
) -> APIRouter:
    """Create eval router with comprehensive OpenAPI documentation for agent/team evaluation endpoints."""
    router = APIRouter(
        dependencies=[Depends(get_authentication_dependency(settings))],
        tags=["Evals"],
        responses={
            400: {"description": "Bad Request", "model": BadRequestResponse},
            401: {"description": "Unauthorized", "model": UnauthenticatedResponse},
            404: {"description": "Not Found", "model": NotFoundResponse},
            422: {"description": "Validation Error", "model": ValidationErrorResponse},
            500: {"description": "Internal Server Error", "model": InternalServerErrorResponse},
        },
    )
    return attach_routes(router=router, dbs=dbs, agents=agents, teams=teams)


def attach_routes(
    router: APIRouter,
    dbs: dict[str, Union[BaseDb, AsyncBaseDb]],
    agents: Optional[List[Agent]] = None,
    teams: Optional[List[Team]] = None,
) -> APIRouter:
    @router.get(
        "/eval-runs",
        response_model=PaginatedResponse[EvalSchema],
        status_code=200,
        operation_id="get_eval_runs",
        summary="List Evaluation Runs",
        description=(
            "Retrieve paginated evaluation runs with filtering and sorting options. "
            "Filter by agent, team, workflow, model, or evaluation type."
        ),
        responses={
            200: {
                "description": "Evaluation runs retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "data": [
                                {
                                    "id": "a03fa2f4-900d-482d-afe0-470d4cd8d1f4",
                                    "agent_id": "basic-agent",
                                    "model_id": "gpt-4o",
                                    "model_provider": "OpenAI",
                                    "team_id": None,
                                    "workflow_id": None,
                                    "name": "Test ",
                                    "evaluated_component_name": None,
                                    "eval_type": "reliability",
                                    "eval_data": {
                                        "eval_status": "PASSED",
                                        "failed_tool_calls": [],
                                        "passed_tool_calls": ["multiply"],
                                    },
                                    "eval_input": {"expected_tool_calls": ["multiply"]},
                                    "created_at": "2025-08-27T15:41:59Z",
                                    "updated_at": "2025-08-27T15:41:59Z",
                                }
                            ]
                        }
                    }
                },
            }
        },
    )
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

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            eval_runs, total_count = await db.get_eval_runs(
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
        else:
            eval_runs, total_count = db.get_eval_runs(  # type: ignore
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

    @router.get(
        "/eval-runs/{eval_run_id}",
        response_model=EvalSchema,
        status_code=200,
        operation_id="get_eval_run",
        summary="Get Evaluation Run",
        description="Retrieve detailed results and metrics for a specific evaluation run.",
        responses={
            200: {
                "description": "Evaluation run details retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "a03fa2f4-900d-482d-afe0-470d4cd8d1f4",
                            "agent_id": "basic-agent",
                            "model_id": "gpt-4o",
                            "model_provider": "OpenAI",
                            "team_id": None,
                            "workflow_id": None,
                            "name": "Test ",
                            "evaluated_component_name": None,
                            "eval_type": "reliability",
                            "eval_data": {
                                "eval_status": "PASSED",
                                "failed_tool_calls": [],
                                "passed_tool_calls": ["multiply"],
                            },
                            "eval_input": {"expected_tool_calls": ["multiply"]},
                            "created_at": "2025-08-27T15:41:59Z",
                            "updated_at": "2025-08-27T15:41:59Z",
                        }
                    }
                },
            },
            404: {"description": "Evaluation run not found", "model": NotFoundResponse},
        },
    )
    async def get_eval_run(
        eval_run_id: str,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> EvalSchema:
        db = get_db(dbs, db_id)
        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            eval_run = await db.get_eval_run(eval_run_id=eval_run_id, deserialize=False)
        else:
            eval_run = db.get_eval_run(eval_run_id=eval_run_id, deserialize=False)
        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)  # type: ignore

    @router.delete(
        "/eval-runs",
        status_code=204,
        operation_id="delete_eval_runs",
        summary="Delete Evaluation Runs",
        description="Delete multiple evaluation runs by their IDs. This action cannot be undone.",
        responses={
            204: {},
            500: {"description": "Failed to delete evaluation runs", "model": InternalServerErrorResponse},
        },
    )
    async def delete_eval_runs(
        request: DeleteEvalRunsRequest,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for deletion"),
    ) -> None:
        try:
            db = get_db(dbs, db_id)
            if isinstance(db, AsyncBaseDb):
                db = cast(AsyncBaseDb, db)
                await db.delete_eval_runs(eval_run_ids=request.eval_run_ids)
            else:
                db.delete_eval_runs(eval_run_ids=request.eval_run_ids)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete eval runs: {e}")

    @router.patch(
        "/eval-runs/{eval_run_id}",
        response_model=EvalSchema,
        status_code=200,
        operation_id="update_eval_run",
        summary="Update Evaluation Run",
        description="Update the name or other properties of an existing evaluation run.",
        responses={
            200: {
                "description": "Evaluation run updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "a03fa2f4-900d-482d-afe0-470d4cd8d1f4",
                            "agent_id": "basic-agent",
                            "model_id": "gpt-4o",
                            "model_provider": "OpenAI",
                            "team_id": None,
                            "workflow_id": None,
                            "name": "Test ",
                            "evaluated_component_name": None,
                            "eval_type": "reliability",
                            "eval_data": {
                                "eval_status": "PASSED",
                                "failed_tool_calls": [],
                                "passed_tool_calls": ["multiply"],
                            },
                            "eval_input": {"expected_tool_calls": ["multiply"]},
                            "created_at": "2025-08-27T15:41:59Z",
                            "updated_at": "2025-08-27T15:41:59Z",
                        }
                    }
                },
            },
            404: {"description": "Evaluation run not found", "model": NotFoundResponse},
            500: {"description": "Failed to update evaluation run", "model": InternalServerErrorResponse},
        },
    )
    async def update_eval_run(
        eval_run_id: str,
        request: UpdateEvalRunRequest,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
    ) -> EvalSchema:
        try:
            db = get_db(dbs, db_id)
            if isinstance(db, AsyncBaseDb):
                db = cast(AsyncBaseDb, db)
                eval_run = await db.rename_eval_run(eval_run_id=eval_run_id, name=request.name, deserialize=False)
            else:
                eval_run = db.rename_eval_run(eval_run_id=eval_run_id, name=request.name, deserialize=False)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to rename eval run: {e}")

        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)  # type: ignore

    @router.post(
        "/eval-runs",
        response_model=EvalSchema,
        status_code=200,
        operation_id="run_eval",
        summary="Execute Evaluation",
        description=(
            "Run evaluation tests on agents or teams. Supports accuracy, performance, and reliability evaluations. "
            "Requires either agent_id or team_id, but not both."
        ),
        responses={
            200: {
                "description": "Evaluation executed successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "f2b2d72f-e9e2-4f0e-8810-0a7e1ff58614",
                            "agent_id": "basic-agent",
                            "model_id": "gpt-4o",
                            "model_provider": "OpenAI",
                            "team_id": None,
                            "workflow_id": None,
                            "name": None,
                            "evaluated_component_name": None,
                            "eval_type": "reliability",
                            "eval_data": {
                                "eval_status": "PASSED",
                                "failed_tool_calls": [],
                                "passed_tool_calls": ["multiply"],
                            },
                            "created_at": "2025-08-27T15:41:59Z",
                            "updated_at": "2025-08-27T15:41:59Z",
                        }
                    }
                },
            },
            400: {"description": "Invalid request - provide either agent_id or team_id", "model": BadRequestResponse},
            404: {"description": "Agent or team not found", "model": NotFoundResponse},
        },
    )
    async def run_eval(
        eval_run_input: EvalRunInput,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for evaluation"),
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
    eval_types: Optional[str] = Query(
        default=None,
        description="Comma-separated eval types (accuracy,performance,reliability)",
        examples=["accuracy,performance"],
    ),
) -> Optional[List[EvalType]]:
    """Parse comma-separated eval types into EvalType enums for filtering evaluation runs."""
    if not eval_types:
        return None
    try:
        return [EvalType(item.strip()) for item in eval_types.split(",")]
    except ValueError as e:
        valid_types = ", ".join([t.value for t in EvalType])
        raise HTTPException(status_code=422, detail=f"Invalid eval_type: {e}. Valid types: {valid_types}")
