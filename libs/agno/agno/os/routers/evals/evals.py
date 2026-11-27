import asyncio
import logging
from contextlib import suppress
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple, Union, cast
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from starlette._utils import get_route_path

from agno.agent import Agent, RemoteAgent
from agno.db.base import AsyncBaseDb, BaseDb, SessionType
from agno.db.schemas.evals import EvalFilterType, EvalRunRecord, EvalType
from agno.eval.suite import Case, EvalSuite, arun_cases
from agno.eval.utils import async_log_eval
from agno.exceptions import AgnoError, RunCancelledException
from agno.models.utils import get_model
from agno.os.auth import INTERNAL_SCHEDULER_USER_ID, get_auth_token_from_request, get_authentication_dependency
from agno.os.middleware.user_scope import (
    _schedule_owner_from_header,
    apply_scope_to_kwargs,
    assert_session_writable,
    caller_is_admin,
    get_scoped_user_id,
)
from agno.os.routers.evals.schemas import (
    DeleteEvalRunsRequest,
    EvalRunInput,
    EvalSchema,
    EvalSuiteInput,
    EvalSuiteRunInput,
    EvalSuiteSchema,
    UpdateEvalRunRequest,
)
from agno.os.routers.evals.utils import (
    adelete_eval_suite_run,
    apply_case_overrides,
    aprepare_eval_suite_run,
    aread_eval_suite_run,
    arun_eval_suite_cases,
    astore_eval_suite_run_data,
    build_posted_suite,
    build_registered_suite,
    run_accuracy_eval,
    run_agent_as_judge_eval,
    run_performance_eval,
    run_reliability_eval,
)
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
from agno.os.utils import AgnoHTTPException, get_agent_by_id, get_db, get_eval_suite_by_id, get_team_by_id
from agno.remote.base import RemoteDb
from agno.run.cancel import acancel_run, acleanup_run, araise_if_cancelled, aregister_run
from agno.run.concurrency import background_run_slot
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning

logger = logging.getLogger(__name__)


async def _require_eval_target_run_access(request: Request, *, resource_type: str, resource_id: str) -> None:
    """Refuse an eval whose caller may not RUN its target agent or team.

    Mirrors the ``require_resource_access(<family>, "run", ...)`` dependency on the run routes:
    dormant when authorization is off, decided by the configured provider (scope, managed roles,
    ReBAC) otherwise, and a denial is written to the decision trail so the audit shows what
    actually blocked the request. The target comes from the request body, not the path, which is
    why the run routes' path-based dependency cannot cover this endpoint."""
    if not getattr(request.state, "authorization_enabled", False):
        return
    from agno.os.auth import acheck_resource_access
    from agno.os.authz.audit import arecord_decision

    if await acheck_resource_access(request, resource_id, resource_type, "run"):
        return
    await arecord_decision(
        request,
        allowed=False,
        target=f"{request.method} {get_route_path(request.scope)} {resource_type}/{resource_id}",
        principal=getattr(request.state, "user_id", None),
        required_scopes=[f"{resource_type}:{resource_id}:run"],
        scopes=list(getattr(request.state, "scopes", None) or []),
        claims=getattr(request.state, "claims", None),
        reason="resource_access_denied",
    )
    singular = "agent" if resource_type == "agents" else "team"
    raise HTTPException(status_code=403, detail=f"Access denied to run this {singular}")


async def _readable_eval_suites(request: Request, eval_suites: Optional[List[EvalSuite]]) -> List[EvalSuite]:
    """The registered suites whose agent or team the caller may read, as GET /agents and /teams filter.

    A suite lists its target id and case names, so a caller who cannot see the agent or team must
    not see its suite either. Every suite runs one target, so this is one check per suite.
    """
    if not getattr(request.state, "authorization_enabled", False):
        return list(eval_suites or [])
    from agno.os.auth import afilter_resources_by_access

    agent_targets = [s.cases[0].agent for s in eval_suites or [] if s.cases[0].agent is not None]
    team_targets = [s.cases[0].team for s in eval_suites or [] if s.cases[0].team is not None]
    readable = [
        *await afilter_resources_by_access(request, agent_targets, "agents"),
        *await afilter_resources_by_access(request, team_targets, "teams"),
    ]
    return [s for s in eval_suites or [] if any((s.cases[0].agent or s.cases[0].team) is target for target in readable)]


def get_eval_router(
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    agents: Optional[List[Union[Agent, RemoteAgent]]] = None,
    teams: Optional[List[Union[Team, RemoteTeam]]] = None,
    eval_suites: Optional[List[EvalSuite]] = None,
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
    return attach_routes(router=router, dbs=dbs, agents=agents, teams=teams, eval_suites=eval_suites)


def attach_routes(
    router: APIRouter,
    dbs: dict[str, list[Union[BaseDb, AsyncBaseDb, RemoteDb]]],
    agents: Optional[List[Union[Agent, RemoteAgent]]] = None,
    teams: Optional[List[Union[Team, RemoteTeam]]] = None,
    eval_suites: Optional[List[EvalSuite]] = None,
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
        request: Request,
        agent_id: Optional[str] = Query(default=None, description="Agent ID"),
        team_id: Optional[str] = Query(default=None, description="Team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Workflow ID"),
        model_id: Optional[str] = Query(default=None, description="Model ID"),
        filter_type: Optional[EvalFilterType] = Query(default=None, description="Filter type", alias="type"),
        eval_types: Optional[List[EvalType]] = Depends(parse_eval_types_filter),
        limit: Optional[int] = Query(default=20, description="Number of eval runs to return", ge=1),
        page: Optional[int] = Query(default=1, description="Page number", ge=1),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default=SortOrder.DESC, description="Sort order (asc or desc)"),
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
        table: Optional[str] = Query(default=None, description="The database table to use"),
    ) -> PaginatedResponse[EvalSchema]:
        db = await get_db(dbs, db_id, table)

        scope = apply_scope_to_kwargs(request)

        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_eval_runs(
                limit=limit,
                page=page,
                sort_by=sort_by,
                sort_order=sort_order.value if sort_order else None,
                agent_id=agent_id,
                team_id=team_id,
                workflow_id=workflow_id,
                model_id=model_id,
                eval_types=eval_types,
                filter_type=filter_type.value if filter_type else None,
                headers=headers,
            )

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
                **scope,
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
                **scope,
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
        request: Request,
        eval_run_id: str,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
        table: Optional[str] = Query(default=None, description="Table to query eval run from"),
    ) -> EvalSchema:
        db = await get_db(dbs, db_id, table)
        scope = apply_scope_to_kwargs(request)
        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.get_eval_run(eval_run_id=eval_run_id, db_id=db_id, table=table, headers=headers)

        if isinstance(db, AsyncBaseDb):
            db = cast(AsyncBaseDb, db)
            eval_run = await db.get_eval_run(eval_run_id=eval_run_id, deserialize=False, **scope)
        else:
            eval_run = db.get_eval_run(eval_run_id=eval_run_id, deserialize=False, **scope)
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
        http_request: Request,
        request: DeleteEvalRunsRequest,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for deletion"),
        table: Optional[str] = Query(default=None, description="Table to use for deletion"),
    ) -> None:
        try:
            db = await get_db(dbs, db_id, table)
            scope = apply_scope_to_kwargs(http_request)
            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(http_request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.delete_eval_runs(
                    eval_run_ids=request.eval_run_ids, db_id=db_id, table=table, headers=headers
                )

            # A deleted background suite run is cancelled, so its cases stop making model calls: each id is read
            # with the caller's scope, and a RUNNING suite run gets its cancellation registered before the rows
            # are deleted. The cancellation is withdrawn when the delete fails or keeps the row; a run that
            # saw it before then has already stopped.
            cancelled_run_ids: List[str] = []
            for eval_run_id in request.eval_run_ids:
                eval_run = await aread_eval_suite_run(db, eval_run_id, **scope)  # type: ignore
                if eval_run is None or eval_run.get("eval_type") != EvalType.SUITE.value:
                    continue
                if ((eval_run.get("eval_data") or {}).get("summary") or {}).get("status") == "RUNNING":
                    cancelled_run_ids.append(eval_run_id)
            try:
                for eval_run_id in cancelled_run_ids:
                    await acancel_run(eval_run_id)
                if isinstance(db, AsyncBaseDb):
                    db = cast(AsyncBaseDb, db)
                    await db.delete_eval_runs(eval_run_ids=request.eval_run_ids, **scope)
                else:
                    db.delete_eval_runs(eval_run_ids=request.eval_run_ids, **scope)
            except BaseException:
                for eval_run_id in cancelled_run_ids:
                    with suppress(Exception):
                        await acleanup_run(eval_run_id)
                raise
            for eval_run_id in cancelled_run_ids:
                # Some databases log and swallow a failed delete: a row that is still there keeps its run.
                with suppress(Exception):
                    if await aread_eval_suite_run(db, eval_run_id, **scope) is not None:  # type: ignore
                        await acleanup_run(eval_run_id)
        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
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
        http_request: Request,
        eval_run_id: str,
        request: UpdateEvalRunRequest,
        db_id: Optional[str] = Query(default=None, description="The ID of the database to use"),
        table: Optional[str] = Query(default=None, description="Table to use for rename operation"),
    ) -> EvalSchema:
        try:
            db = await get_db(dbs, db_id, table)
            scope = apply_scope_to_kwargs(http_request)
            if isinstance(db, RemoteDb):
                auth_token = get_auth_token_from_request(http_request)
                headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
                return await db.update_eval_run(
                    eval_run_id=eval_run_id, name=request.name, db_id=db_id, table=table, headers=headers
                )

            if isinstance(db, AsyncBaseDb):
                db = cast(AsyncBaseDb, db)
                eval_run = await db.rename_eval_run(
                    eval_run_id=eval_run_id, name=request.name, deserialize=False, **scope
                )
            else:
                eval_run = db.rename_eval_run(eval_run_id=eval_run_id, name=request.name, deserialize=False, **scope)
        except HTTPException:
            raise
        except AgnoError as e:
            raise AgnoHTTPException(e)
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
            "Run evaluation tests on agents or teams. Supports accuracy, agent-as-judge, performance, and reliability evaluations. "
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
        request: Request,
        eval_run_input: EvalRunInput,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for evaluation"),
        table: Optional[str] = Query(default=None, description="Table to use for evaluation"),
    ) -> Optional[EvalSchema]:
        db = await get_db(dbs, db_id, table)
        if eval_run_input.eval_type == EvalType.SUITE:
            raise HTTPException(status_code=400, detail="Run a suite with POST /eval-suites/{suite_id}/runs")
        if isinstance(db, RemoteDb):
            auth_token = get_auth_token_from_request(request)
            headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
            return await db.create_eval_run(
                eval_type=eval_run_input.eval_type,
                input_text=eval_run_input.input,
                agent_id=eval_run_input.agent_id,
                team_id=eval_run_input.team_id,
                model_id=eval_run_input.model_id,
                model_provider=eval_run_input.model_provider,
                expected_output=eval_run_input.expected_output,
                expected_tool_calls=eval_run_input.expected_tool_calls,
                num_iterations=eval_run_input.num_iterations,
                db_id=db_id,
                table=table,
                headers=headers,
            )

        # Resolved before the run: get_scoped_user_id raises 403 and the eval below makes real model calls.
        creator_user_id = get_scoped_user_id(request) or getattr(request.state, "user_id", None)

        if eval_run_input.agent_id and eval_run_input.team_id:
            raise HTTPException(status_code=400, detail="Only one of agent_id or team_id must be provided")

        # An eval RUNS the target with real model calls, so it is gated exactly like the run
        # endpoints: the caller must hold "run" on that specific agent or team under the
        # configured provider. The route scope (evals:write) alone says nothing about which
        # targets the caller may execute, and the body names the target, so this is the only
        # place the per-resource decision can be made.
        if eval_run_input.agent_id or eval_run_input.team_id:
            await _require_eval_target_run_access(
                request,
                resource_type="agents" if eval_run_input.agent_id else "teams",
                resource_id=eval_run_input.agent_id or eval_run_input.team_id,  # type: ignore[arg-type]
            )

        if eval_run_input.agent_id:
            # create_fresh: the eval mutates the resolved agent (e.g. agent.model below), so
            # it must run on a per-request deep_copy, never the shared singleton instance.
            agent = get_agent_by_id(agent_id=eval_run_input.agent_id, agents=agents, create_fresh=True)
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent with id '{eval_run_input.agent_id}' not found")
            if isinstance(agent, RemoteAgent):
                log_warning("Evaluation against remote agents are not supported yet")
                return None
            if not isinstance(agent, Agent):
                log_warning("Evaluation against external framework agents is not supported yet")
                return None

            default_model = None
            if (
                hasattr(agent, "model")
                and agent.model is not None
                and eval_run_input.model_id is not None
                and eval_run_input.model_provider is not None
            ):
                default_model = deepcopy(agent.model)
                if eval_run_input.model_id != agent.model.id or eval_run_input.model_provider != agent.model.provider:
                    model_provider = eval_run_input.model_provider.lower()
                    model_id = eval_run_input.model_id.lower()
                    model_string = f"{model_provider}:{model_id}"
                    model = get_model(model_string)
                    agent.model = model

            team = None

        elif eval_run_input.team_id:
            # create_fresh: mirror the agent path -- eval runs must not share the singleton.
            team = get_team_by_id(team_id=eval_run_input.team_id, teams=teams, create_fresh=True)
            if not team:
                raise HTTPException(status_code=404, detail=f"Team with id '{eval_run_input.team_id}' not found")
            if isinstance(team, RemoteTeam):
                log_warning("Evaluation against remote teams are not supported yet")
                return None

            # If model_id/model_provider specified, override team's model temporarily
            default_model = None
            if (
                hasattr(team, "model")
                and team.model is not None
                and eval_run_input.model_id is not None
                and eval_run_input.model_provider is not None
            ):
                default_model = deepcopy(team.model)  # Save original
                if eval_run_input.model_id != team.model.id or eval_run_input.model_provider != team.model.provider:
                    model_provider = eval_run_input.model_provider.lower()
                    model_id = eval_run_input.model_id.lower()
                    model_string = f"{model_provider}:{model_id}"
                    model = get_model(model_string)
                    team.model = model  # Override temporarily

            agent = None

        else:
            raise HTTPException(status_code=400, detail="One of agent_id or team_id must be provided")

        # Run the evaluation
        eval_run: Optional[EvalSchema] = None
        if eval_run_input.eval_type == EvalType.ACCURACY:
            if isinstance(agent, RemoteAgent) or isinstance(team, RemoteTeam):
                # TODO: Handle remote evaluation
                log_warning("Evaluation against remote agents are not supported yet")
                return None
            eval_run = await run_accuracy_eval(
                eval_run_input=eval_run_input, db=db, agent=agent, team=team, default_model=default_model
            )

        elif eval_run_input.eval_type == EvalType.AGENT_AS_JUDGE:
            eval_run = await run_agent_as_judge_eval(
                eval_run_input=eval_run_input,
                db=db,
                agent=agent,
                team=team,
                default_model=default_model,  # type: ignore
            )

        elif eval_run_input.eval_type == EvalType.PERFORMANCE:
            if isinstance(agent, RemoteAgent) or isinstance(team, RemoteTeam):
                # TODO: Handle remote evaluation
                log_warning("Evaluation against remote agents are not supported yet")
                return None
            eval_run = await run_performance_eval(
                eval_run_input=eval_run_input, db=db, agent=agent, team=team, default_model=default_model
            )

        else:
            if isinstance(agent, RemoteAgent) or isinstance(team, RemoteTeam):
                # TODO: Handle remote evaluation
                log_warning("Evaluation against remote agents are not supported yet")
                return None
            eval_run = await run_reliability_eval(
                eval_run_input=eval_run_input, db=db, agent=agent, team=team, default_model=default_model
            )

        # Attribute the created run to the caller. Best-effort: the eval run is
        # already persisted, so a backend that can't stamp the owner (e.g. a
        # custom Db without update_eval_run_user_id) must not fail the request.
        if eval_run is not None:
            if creator_user_id is not None:
                try:
                    if isinstance(db, AsyncBaseDb):
                        await db.update_eval_run_user_id(eval_run_id=eval_run.id, user_id=creator_user_id)
                    else:
                        db.update_eval_run_user_id(eval_run_id=eval_run.id, user_id=creator_user_id)
                    eval_run.user_id = creator_user_id
                except Exception as e:
                    log_warning(f"Could not set owner on eval run {eval_run.id}: {e}")

        return eval_run

    @router.get(
        "/eval-suites",
        response_model=List[EvalSuiteSchema],
        status_code=200,
        operation_id="get_eval_suites",
        summary="List Evaluation Suites",
        description="List the eval suites registered on this OS, with the cases each one runs.",
        responses={
            200: {
                "description": "Evaluation suites retrieved successfully",
                "content": {
                    "application/json": {
                        "example": [
                            {
                                "id": "sales-setter-quality",
                                "name": "Sales setter quality",
                                "description": None,
                                "cases": [
                                    {
                                        "name": "offers_open_slots",
                                        "agent_id": "sales-setter",
                                        "team_id": None,
                                        "tags": ["smoke"],
                                        "timeout_seconds": 120,
                                    }
                                ],
                            }
                        ]
                    }
                },
            }
        },
    )
    async def get_eval_suites(request: Request) -> List[EvalSuiteSchema]:
        return [
            EvalSuiteSchema.from_eval_suite(eval_suite)
            for eval_suite in await _readable_eval_suites(request, eval_suites)
        ]

    @router.get(
        "/eval-suites/{suite_id}",
        response_model=EvalSuiteSchema,
        status_code=200,
        operation_id="get_eval_suite",
        summary="Get Evaluation Suite",
        description="Retrieve an eval suite and the cases it runs.",
        responses={
            200: {
                "description": "Evaluation suite retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "sales-setter-quality",
                            "name": "Sales setter quality",
                            "description": None,
                            "cases": [
                                {
                                    "name": "offers_open_slots",
                                    "agent_id": "sales-setter",
                                    "team_id": None,
                                    "tags": ["smoke"],
                                    "timeout_seconds": 120,
                                }
                            ],
                        }
                    }
                },
            },
            404: {"description": "Evaluation suite not found", "model": NotFoundResponse},
        },
    )
    async def get_eval_suite(request: Request, suite_id: str) -> EvalSuiteSchema:
        eval_suite = get_eval_suite_by_id(suite_id, eval_suites)
        if eval_suite is None:
            raise HTTPException(status_code=404, detail=f"Eval suite with id '{suite_id}' not found")
        # Same 404 as an unknown id, so the route does not reveal a suite the caller cannot read.
        if eval_suite not in await _readable_eval_suites(request, eval_suites):
            raise HTTPException(status_code=404, detail=f"Eval suite with id '{suite_id}' not found")
        return EvalSuiteSchema.from_eval_suite(eval_suite)

    async def _run_eval_suite(
        request: Request,
        db: Union[BaseDb, AsyncBaseDb],
        eval_suite: EvalSuite,
        *,
        tag: Optional[str],
        name: Optional[str],
        timeout: int,
        eval_input: Dict[str, Any],
        background: bool = False,
    ) -> EvalSchema:
        """Run the selected cases of a suite and store the result as one eval run of type suite.

        Shared by the registered-suite and the body-defined routes, so both gate, run and persist
        the same way; eval_input is the request a client reruns: the posted body, or the suite_id with
        the body posted to its run route.
        """
        # Resolved before the run: get_scoped_user_id raises 403 and the suite below makes real model calls.
        # The scheduler sentinel identifies the caller, not the owner: a scheduled run takes the forwarded
        # schedule owner, as the run routes take the owner the executor puts in the form.
        state_user_id = getattr(request.state, "user_id", None)
        creator_user_id = get_scoped_user_id(request) or (
            _schedule_owner_from_header(request) if state_user_id == INTERNAL_SCHEDULER_USER_ID else state_user_id
        )
        # The target is gated like the run endpoints, before case selection, so a refused caller gets 403 for any tag.
        agent_ids = {cast(str, case.agent.id) for case in eval_suite.cases if case.agent is not None}
        team_ids = {cast(str, case.team.id) for case in eval_suite.cases if case.team is not None}
        for resource_type, resource_ids in (("agents", agent_ids), ("teams", team_ids)):
            for resource_id in sorted(resource_ids):
                await _require_eval_target_run_access(request, resource_type=resource_type, resource_id=resource_id)
        selected = eval_suite.select(tag=tag, name=name)
        if not selected:
            raise HTTPException(status_code=400, detail="No cases match the given tag or name")
        # The caller's identity wins over a user_id set on the case, as on the run routes, so a case runs
        # and writes its session as the caller. A case's own user_id applies only when there is no caller.
        # Values the middleware put on request.state (from token claims) win over the case's own too.
        overrides = {
            field: getattr(request.state, field)
            for field in ("session_id", "session_state", "dependencies", "metadata")
            if getattr(request.state, field, None) is not None
        }
        if creator_user_id is not None:
            overrides["user_id"] = creator_user_id
        selected = apply_case_overrides(selected, overrides)
        # A case pinned to a session must not write into another user's session, as on the run routes.
        for case in selected:
            if case.session_id:
                target = case.agent if case.agent is not None else case.team
                await assert_session_writable(
                    getattr(target, "db", None) or db,
                    case.session_id,
                    case.user_id or getattr(target, "user_id", None),
                    session_type=SessionType.AGENT if case.agent is not None else SessionType.TEAM,
                    is_admin=caller_is_admin(request),
                )

        # A suite runs one agent or one team, so the run is stamped with it like every other eval
        # and GET /eval-runs?agent_id= or ?team_id= finds its history.
        agent_id = next(iter(agent_ids), None)
        team_id = next(iter(team_ids), None)
        if background:
            # A db without the update method could never replace the running row, so it is refused up front,
            # as the Company routes refuse a db that does not implement get_tasks.
            if type(db).update_eval_run_data in (BaseDb.update_eval_run_data, AsyncBaseDb.update_eval_run_data):
                raise HTTPException(
                    status_code=501, detail="Background eval suite runs are not supported by the configured database"
                )
            # Stored as running before the cases run, as a background agent run is, so the caller polls
            # GET /eval-runs/{id}; the owner is set now so a caller scoped to their own runs can read it.
            eval_run = EvalSchema.from_running_suite(
                eval_suite=eval_suite,
                total=len(selected),
                run_id=str(uuid4()),
                eval_input=eval_input,
                agent_id=agent_id,
                team_id=team_id,
            )
            running_record = EvalRunRecord(
                run_id=eval_run.id,
                eval_type=EvalType.SUITE,
                eval_data=eval_run.eval_data,
                eval_input=eval_input,
                agent_id=agent_id,
                team_id=team_id,
                name=eval_run.name,
            )
            # Register the run for cancellation tracking before its row is stored and its task spawned, as a
            # background agent run is, so a delete that lands before the task starts is kept.
            await aregister_run(eval_run.id)
            try:
                await aprepare_eval_suite_run(db, running_record, creator_user_id)
            except HTTPException:
                # The poll is scoped to the owner, so a run whose owner was not stored could never be read
                # back: it is removed and refused, where the synchronous run keeps it.
                await adelete_eval_suite_run(db, running_record.run_id)
                await acleanup_run(eval_run.id)
                raise
            except Exception:
                await acleanup_run(eval_run.id)
                raise
            eval_run.user_id = creator_user_id
            # Spawned like a background agent run, so shutdown drains it before the databases close.
            from agno.run.background import _spawn_background

            _spawn_background(_finish_eval_suite_run(db, selected, timeout, eval_run))
            return eval_run

        # No db= here: the per-case checks would each persist their own eval run next to the
        # suite's, and the suite record below already carries every case's result.
        suite_result = await arun_cases(selected, default_timeout=timeout)

        eval_run = EvalSchema.from_suite_result(
            eval_suite=eval_suite,
            result=suite_result,
            run_id=str(uuid4()),
            eval_input=eval_input,
            agent_id=agent_id,
            team_id=team_id,
        )
        # Persisted like a single eval run: a failed write is logged and the report is still returned,
        # so the model calls behind it are not lost.
        await async_log_eval(
            db=db,
            run_id=eval_run.id,
            run_data=eval_run.eval_data,
            eval_type=EvalType.SUITE,
            eval_input=eval_input,
            agent_id=agent_id,
            team_id=team_id,
            name=eval_run.name,
        )
        await _set_eval_run_owner(db, eval_run, creator_user_id)
        return eval_run

    async def _set_eval_run_owner(
        db: Union[BaseDb, AsyncBaseDb], eval_run: EvalSchema, creator_user_id: Optional[str]
    ) -> None:
        """Attribute the created run to the caller. Best-effort, as for a single eval run."""
        if creator_user_id is None:
            return
        try:
            if isinstance(db, AsyncBaseDb):
                await db.update_eval_run_user_id(eval_run_id=eval_run.id, user_id=creator_user_id)
            else:
                db.update_eval_run_user_id(eval_run_id=eval_run.id, user_id=creator_user_id)
            eval_run.user_id = creator_user_id
        except Exception as e:
            log_warning(f"Could not set owner on eval run {eval_run.id}: {e}")

    async def _finish_eval_suite_run(
        db: Union[BaseDb, AsyncBaseDb], selected: Tuple[Case, ...], timeout: int, eval_run: EvalSchema
    ) -> None:
        """Run the cases of a background suite run and replace its running row with the result."""
        error_data = {**eval_run.eval_data, "summary": {**eval_run.eval_data["summary"], "status": "ERROR"}}
        try:
            # A delete stored before the task started stops it here, as _execute_background checks it.
            await araise_if_cancelled(eval_run.id)
            # Held like a background agent run's slot, so the background concurrency cap bounds suite runs too.
            async with background_run_slot(run_id=eval_run.id):
                suite_result = await arun_eval_suite_cases(selected, timeout, eval_run.id)
            eval_data = suite_result.to_dict()
        except RunCancelledException:
            # Deleted while waiting for a slot or while its cases ran: the cases stop, and the write below finds
            # no row, so a deleted run stays deleted.
            eval_data = {**error_data, "error": "cancelled"}
        except asyncio.CancelledError:
            # A shutdown cancels the run: the row is marked ERROR, best-effort, and the cancellation goes on,
            # as a cancelled background agent run is marked cancelled. Shielded, so a second cancellation does
            # not lose the write.
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.shield(astore_eval_suite_run_data(db, eval_run.id, {**error_data, "error": "cancelled"}))
            raise
        except Exception as e:
            log_error(f"Eval suite run {eval_run.id} failed: {e}", exc_info=True)
            eval_data = {**error_data, "error": str(e)}
        finally:
            with suppress(Exception, asyncio.CancelledError):
                await asyncio.shield(acleanup_run(eval_run.id))
        try:
            # Shielded: a shutdown landing now must not leave the row RUNNING.
            await asyncio.shield(astore_eval_suite_run_data(db, eval_run.id, eval_data))
        except Exception as e:
            log_error(f"Could not store the result of eval suite run {eval_run.id}: {e}")

    @router.post(
        "/eval-suites/{suite_id}/runs",
        response_model=EvalSchema,
        status_code=200,
        operation_id="run_eval_suite",
        summary="Execute Evaluation Suite",
        description=(
            "Run an eval suite, or the subset selected by tag or case name, and store the result as an "
            "eval run of type 'suite'. The per-case results and the pass rate are in eval_data."
        ),
        responses={
            200: {
                "description": "Evaluation suite executed successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "f2b2d72f-e9e2-4f0e-8810-0a7e1ff58614",
                            "agent_id": "sales-setter",
                            "team_id": None,
                            "name": "Sales setter quality",
                            "eval_type": "suite",
                            "eval_data": {
                                "summary": {"total": 2, "passed": 2, "failed": 0, "status": "PASS"},
                                "cases": [{"name": "offers_open_slots", "passed": True}],
                            },
                            "eval_input": {
                                "suite_id": "sales-setter-quality",
                                "tag": None,
                                "case_name": None,
                                "default_timeout": 120,
                            },
                            "created_at": "2025-08-27T15:41:59Z",
                            "updated_at": "2025-08-27T15:41:59Z",
                        }
                    }
                },
            },
            202: {
                "description": "Background run started; poll GET /eval-runs/{eval_run_id} until it is not RUNNING. A server killed "
                "before it finishes leaves it RUNNING"
            },
            400: {"description": "No case matched the selection", "model": BadRequestResponse},
            404: {"description": "Evaluation suite not found", "model": NotFoundResponse},
        },
    )
    async def run_eval_suite(
        request: Request,
        suite_id: str,
        response: Response,
        suite_run_input: Optional[EvalSuiteRunInput] = Body(None, description="Optional tag or case selection"),
        db_id: Optional[str] = Query(default=None, description="Database ID to use for evaluation"),
        table: Optional[str] = Query(default=None, description="Table to use for evaluation"),
        background: bool = Query(
            default=False, description="Run the cases in the background and return 202 with the running eval run"
        ),
    ) -> EvalSchema:
        db = await get_db(dbs, db_id, table)
        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Eval suites are not supported for remote databases")
        eval_suite = get_eval_suite_by_id(suite_id, eval_suites)
        if eval_suite is None:
            raise HTTPException(status_code=404, detail=f"Eval suite with id '{suite_id}' not found")
        eval_suite = build_registered_suite(eval_suite, agents, teams)
        suite_run_input = suite_run_input or EvalSuiteRunInput()
        eval_run = await _run_eval_suite(
            request,
            db,
            eval_suite,
            tag=suite_run_input.tag,
            name=suite_run_input.case_name,
            timeout=suite_run_input.default_timeout,
            eval_input={"suite_id": suite_id, **suite_run_input.model_dump()},
            background=background,
        )
        if background:
            response.status_code = 202
        return eval_run

    @router.post(
        "/eval-suites",
        response_model=EvalSchema,
        status_code=200,
        operation_id="run_eval_suite_from_body",
        summary="Execute Evaluation Suite From Body",
        description=(
            "Run the cases posted in the body against registered agents or teams and store the result as an "
            "eval run of type 'suite'. The body, minus each case's dependencies, is saved as eval_input, so posting it "
            "again reruns the suite."
        ),
        responses={
            200: {
                "description": "Evaluation suite executed successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "id": "f2b2d72f-e9e2-4f0e-8810-0a7e1ff58614",
                            "agent_id": "sales-setter",
                            "team_id": None,
                            "name": "Sales setter smoke",
                            "eval_type": "suite",
                            "eval_data": {
                                "summary": {"total": 1, "passed": 1, "failed": 0, "status": "PASS"},
                                "cases": [{"name": "offers_open_slots", "passed": True}],
                            },
                            "eval_input": {
                                "name": "Sales setter smoke",
                                "cases": [
                                    {
                                        "name": "offers_open_slots",
                                        "agent_id": "sales-setter",
                                        "input": "Can I book a call tomorrow?",
                                        "criteria": "Offers at least one open slot",
                                    }
                                ],
                                "tag": None,
                                "case_name": None,
                                "default_timeout": 120,
                            },
                            "created_at": "2025-08-27T15:41:59Z",
                            "updated_at": "2025-08-27T15:41:59Z",
                        }
                    }
                },
            },
            202: {
                "description": "Background run started; poll GET /eval-runs/{eval_run_id} until it is not RUNNING. A server killed "
                "before it finishes leaves it RUNNING"
            },
            400: {
                "description": "Cases target more than one agent or team, or none matched",
                "model": BadRequestResponse,
            },
            404: {"description": "Agent or team not found", "model": NotFoundResponse},
        },
    )
    async def run_eval_suite_from_body(
        request: Request,
        response: Response,
        eval_suite_input: EvalSuiteInput,
        db_id: Optional[str] = Query(default=None, description="Database ID to use for evaluation"),
        table: Optional[str] = Query(default=None, description="Table to use for evaluation"),
        background: bool = Query(
            default=False, description="Run the cases in the background and return 202 with the running eval run"
        ),
    ) -> EvalSchema:
        db = await get_db(dbs, db_id, table)
        if isinstance(db, RemoteDb):
            raise HTTPException(status_code=501, detail="Eval suites are not supported for remote databases")
        # One target per suite, as every eval stamps exactly one agent or team.
        targets = {(case.agent_id or None, case.team_id or None) for case in eval_suite_input.cases}
        if len(targets) > 1:
            raise HTTPException(status_code=400, detail="All cases in a suite must run the same agent or team")
        agent_id, team_id = targets.pop()
        # Gated before the lookup, as run_eval does: a caller without run rights must not learn
        # from a 404 whether the id exists.
        await _require_eval_target_run_access(
            request,
            resource_type="agents" if agent_id else "teams",
            resource_id=cast(str, agent_id or team_id),
        )
        eval_suite = build_posted_suite(eval_suite_input, agent_id, team_id, agents, teams)
        eval_run = await _run_eval_suite(
            request,
            db,
            eval_suite,
            tag=eval_suite_input.tag,
            name=eval_suite_input.case_name,
            timeout=eval_suite_input.default_timeout,
            # A run's dependencies are never stored, as on the run routes, so they stay out of the saved
            # eval_input that GET /eval-runs returns to every evals:read caller.
            eval_input=eval_suite_input.model_dump(exclude={"cases": {"__all__": {"dependencies"}}}),
            background=background,
        )
        if background:
            response.status_code = 202
        return eval_run

    return router


def parse_eval_types_filter(
    eval_types: Optional[str] = Query(
        default=None,
        description="Comma-separated eval types (accuracy,agent_as_judge,performance,reliability,suite)",
        examples=["accuracy,agent_as_judge,performance,reliability,suite"],
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
