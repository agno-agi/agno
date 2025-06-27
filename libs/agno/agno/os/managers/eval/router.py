from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from agno.db.base import BaseDb
from agno.eval import AccuracyEval
from agno.eval.performance import PerformanceEval
from agno.eval.schemas import EvalType
from agno.os.managers.eval.schemas import AccuracyEvalInput, EvalSchema, PerformanceEvalInput, ReliabilityEvalInput
from agno.os.managers.utils import PaginatedResponse, PaginationInfo, SortOrder


def attach_routes(router: APIRouter, db: BaseDb) -> APIRouter:
    @router.get("/evals", response_model=PaginatedResponse[EvalSchema], status_code=200)
    async def get_eval_runs(
        agent_id: Optional[str] = Query(default=None, description="Agent ID"),
        team_id: Optional[str] = Query(default=None, description="Team ID"),
        workflow_id: Optional[str] = Query(default=None, description="Workflow ID"),
        model_id: Optional[str] = Query(default=None, description="Model ID"),
        eval_type: Optional[EvalType] = Query(default=None, description="Eval type"),
        limit: Optional[int] = Query(default=20, description="Number of eval runs to return"),
        page: Optional[int] = Query(default=1, description="Page number"),
        sort_by: Optional[str] = Query(default=None, description="Field to sort by"),
        sort_order: Optional[SortOrder] = Query(default=None, description="Sort order (asc or desc)"),
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
            eval_type=eval_type,
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

    @router.post("/evals/accuracy/run", response_model=EvalSchema, status_code=200)
    async def run_accuracy_eval(accuracy_eval_input: AccuracyEvalInput) -> EvalSchema:
        # TODO: get real agent/team
        agent = ...

        accuracy_eval = AccuracyEval(
            db=db,
            agent=agent,  # type: ignore
            input=accuracy_eval_input.input,
            expected_output=accuracy_eval_input.expected_output,
            additional_guidelines=accuracy_eval_input.additional_guidelines,
            num_iterations=accuracy_eval_input.num_iterations,
            name=accuracy_eval_input.name,
        )
        result = accuracy_eval.run(print_results=False, print_summary=False)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to run accuracy evaluation")

        return EvalSchema.from_accuracy_result(result)

    @router.post("/evals/performance/run", response_model=EvalSchema, status_code=200)
    async def run_performance_eval(performance_eval_input: PerformanceEvalInput) -> EvalSchema:
        # TODO: get real agent
        agent = ...

        def run_component() -> str:
            return agent.run(performance_eval_input.input)

        performance_eval = PerformanceEval(
            db=db,
            name=performance_eval_input.name,
            func=run_component,
            num_iterations=performance_eval_input.num_iterations,
            warmup_runs=performance_eval_input.warmup_runs,
        )
        result = performance_eval.run(print_results=False, print_summary=False)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to run performance evaluation")

        return EvalSchema.from_performance_result(result)

    @router.post("/evals/reliability/run", response_model=EvalSchema, status_code=200)
    async def run_reliability_eval(reliability_eval_input: ReliabilityEvalInput) -> EvalSchema:
        # TODO: get and run real agent
        agent = ...
        agent_response = agent.run(reliability_eval_input.input)

        reliability_eval = ReliabilityEval(
            db=db,
            name=reliability_eval_input.name,
            agent_response=agent_response,
            expected_tool_calls=reliability_eval_input.expected_tool_calls,
        )
        result = reliability_eval.run(print_results=False, print_summary=False)
        if not result:
            raise HTTPException(status_code=500, detail="Failed to run reliability evaluation")

        return EvalSchema.from_reliability_result(result)

    return router
