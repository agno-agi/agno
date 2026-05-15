"""Shared workflow builders for router post-execution output review tests.

Used by test_hitl_output_review.py and test_hitl.py — keep in one place to avoid
cross-importing between test modules.
"""

from agno.workflow import OnReject
from agno.workflow.step import Step
from agno.workflow.types import StepInput, StepOutput


def _quick_fn(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Quick result: basic analysis done")


def _deep_fn(step_input: StepInput) -> StepOutput:
    return StepOutput(content="Deep result: comprehensive analysis done")


def _report_fn(step_input: StepInput) -> StepOutput:
    prev = step_input.previous_step_content or ""
    return StepOutput(content=f"Report: {prev}")


def _make_router_review_workflow(_session_id: str):
    """Create a workflow with a Router that has output review (sync session DB)."""
    from agno.db.sqlite import SqliteDb
    from agno.workflow.router import Router
    from agno.workflow.workflow import Workflow

    return Workflow(
        name="test_router_review",
        db=SqliteDb(db_file="tmp/test_router_review.db"),
        steps=[
            Router(
                name="analysis",
                selector=lambda si: [Step(name="quick", executor=_quick_fn)],
                choices=[
                    Step(name="quick", description="Fast", executor=_quick_fn),
                    Step(name="deep", description="Thorough", executor=_deep_fn),
                ],
                requires_output_review=True,
                output_review_message="Approve the analysis?",
                on_reject=OnReject.retry,
                hitl_max_retries=2,
            ),
            Step(name="report", executor=_report_fn),
        ],
    )


def _make_async_router_review_workflow(_session_id: str):
    """Create an async-compatible workflow with a Router that has output review."""
    from agno.db.sqlite import SqliteDb
    from agno.workflow.router import Router
    from agno.workflow.workflow import Workflow

    return Workflow(
        name="test_async_router_review",
        db=SqliteDb(db_file="tmp/test_async_router_review.db"),
        steps=[
            Router(
                name="analysis",
                selector=lambda si: [Step(name="quick", executor=_quick_fn)],
                choices=[
                    Step(name="quick", description="Fast", executor=_quick_fn),
                    Step(name="deep", description="Thorough", executor=_deep_fn),
                ],
                requires_output_review=True,
                output_review_message="Approve the analysis?",
                on_reject=OnReject.retry,
                hitl_max_retries=2,
            ),
            Step(name="report", executor=_report_fn),
        ],
    )
