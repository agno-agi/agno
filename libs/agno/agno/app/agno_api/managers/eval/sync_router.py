from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from agno.app.agno_api.managers.eval.schemas import EvalSchema
from agno.app.agno_api.managers.utils import SortOrder
from agno.db.base import BaseDb
from agno.eval.schemas import EvalType


def attach_sync_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/evals", response_model=List[EvalSchema], status_code=200)
    def get_eval_runs(
        agent_id: Optional[str] = Query(default=None, description="Agent ID"),
        team_id: Optional[str] = Query(default=None, description="Team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Workflow ID"),
        model_id: Optional[str] = Query(default=None, description="Model ID"),
        eval_type: Optional[EvalType] = Query(default=None, description="Eval type"),
        limit: Optional[int] = Query(default=20, description="Number of eval runs to return"),
        offset: Optional[int] = Query(default=0, description="Number of eval runs to skip"),
        sort_by: Optional[str] = Query(default=None, description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default=None, description="Sort order (asc or desc)"),
    ) -> List[EvalSchema]:
        eval_runs = db.get_eval_runs_raw(
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
            agent_id=agent_id,
            team_id=team_id,
            workflow_id=workflow_id,
            model_id=model_id,
            eval_type=eval_type,
        )
        return [EvalSchema.from_dict(eval_run) for eval_run in eval_runs]

    @router.get("/evals/{eval_run_id}", response_model=EvalSchema, status_code=200)
    def get_eval_run(eval_run_id: str) -> EvalSchema:
        eval_run = db.get_eval_run_raw(eval_run_id=eval_run_id)
        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")

        return EvalSchema.from_dict(eval_run)

    return router
