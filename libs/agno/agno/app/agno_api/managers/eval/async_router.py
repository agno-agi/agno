from typing import List

from fastapi import APIRouter, HTTPException

from agno.app.agno_api.managers.eval.schemas import EvalSchema
from agno.db.base import BaseDb


def attach_async_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/evals", response_model=List[EvalSchema], status_code=200)
    async def get_eval_runs() -> List[EvalSchema]:
        eval_runs = db.get_eval_runs()
        return [EvalSchema.from_eval_run(eval_run) for eval_run in eval_runs]

    @router.get("/evals/{eval_run_id}", response_model=EvalSchema, status_code=200)
    async def get_eval_run(eval_run_id: str) -> EvalSchema:
        eval_run = db.get_eval_run(eval_run_id)
        if not eval_run:
            raise HTTPException(status_code=404, detail=f"Eval run with id '{eval_run_id}' not found")
        return EvalSchema.from_eval_run(eval_run)

    return router
