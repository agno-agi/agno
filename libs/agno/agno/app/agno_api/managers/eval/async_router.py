from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from agno.app.agno_api.managers.eval.schemas import EvalSchema
from agno.app.agno_api.managers.utils import SortOrder
from agno.db.base import BaseDb


def attach_async_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/evals", response_model=List[EvalSchema], status_code=200)
    async def get_eval_runs(
        limit: Optional[int] = Query(default=20, description="Number of eval runs to return"),
        offset: Optional[int] = Query(default=0, description="Number of eval runs to skip"),
        sort_by: Optional[str] = Query(default=None, description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default=None, description="Sort order (asc or desc)"),
    ) -> List[EvalSchema]:
        eval_runs = db.get_eval_runs(limit=limit, offset=offset, sort_by=sort_by, sort_order=sort_order)
        return [EvalSchema.from_eval_run(eval_run) for eval_run in eval_runs]

    @router.get("/evals/{eval_run_id}", response_model=EvalSchema, status_code=200)
    async def get_eval_run(eval_run_id: str) -> EvalSchema:
        eval_run = db.get_eval_run(eval_run_id)
        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")
        return EvalSchema.from_eval_run(eval_run)

    return router
