from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from agno.db.base import BaseDb
from agno.eval.schemas import EvalFilterType, EvalType
from agno.os.managers.eval.schemas import DeleteEvalRunsRequest, EvalSchema, UpdateEvalRunRequest
from agno.os.managers.utils import PaginatedResponse, PaginationInfo, SortOrder


def attach_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/evals", response_model=PaginatedResponse[EvalSchema], status_code=200)
    async def get_eval_runs(
        agent_id: Optional[str] = Query(default=None, description="Agent ID"),
        team_id: Optional[str] = Query(default=None, description="Team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Workflow ID"),
        model_id: Optional[str] = Query(default=None, description="Model ID"),
        eval_type: Optional[str] = Query(
            default=None, description="Eval type(s) - comma separated (e.g., accuracy,performance,reliability)"
        ),
        filter_type: Optional[EvalFilterType] = Query(default=None, description="Filter type"),
        limit: Optional[int] = Query(default=20, description="Number of eval runs to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default="created_at", description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default="desc", description="Sort order (asc or desc)"),
    ) -> PaginatedResponse[EvalSchema]:
        # Parse comma-separated eval_type string into list of EvalType enums
        #  accuracy,performance,reliability -> [EvalType.ACCURACY, EvalType.PERFORMANCE, EvalType.RELIABILITY]

        parsed_eval_types: Optional[List[EvalType]] = None
        if eval_type:
            try:
                eval_type_strings = [t.strip() for t in eval_type.split(",") if t.strip()]
                parsed_eval_types = [EvalType(eval_type_str) for eval_type_str in eval_type_strings]
            except ValueError as e:
                raise HTTPException(status_code=422, detail=f"Invalid eval_type value: {e}")

        eval_runs, total_count = db.get_eval_runs_raw(
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=workflow_id,
            model_id=model_id,
            eval_type=parsed_eval_types,
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

    @router.get("/evals/{eval_run_id}", response_model=EvalSchema, status_code=200)
    async def get_eval_run(eval_run_id: str) -> EvalSchema:
        eval_run = db.get_eval_run_raw(eval_run_id=eval_run_id)
        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)

    @router.delete("/evals", status_code=204)
    async def delete_eval_runs(request: DeleteEvalRunsRequest) -> None:
        try:
            db.delete_eval_runs(eval_run_ids=request.eval_run_ids)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete eval runs: {e}")

    @router.patch("/evals/{eval_run_id}", response_model=EvalSchema, status_code=200)
    async def update_eval_run(eval_run_id: str, request: UpdateEvalRunRequest) -> EvalSchema:
        try:
            eval_run = db.update_eval_run_name(eval_run_id=eval_run_id, name=request.name)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to update eval run: {e}")

        return EvalSchema.from_dict(eval_run)

    return router
