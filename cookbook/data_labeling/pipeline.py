"""
Labeling workflow.

Composition:

    Parallel(Labeler A, Labeler B)
        -> Reviewer (executor extracts both outputs by name, formats, calls agent)
        -> Condition(needs_adjudication, [Adjudicator (executor)])

The Workflow's input `files=[invoice_pdf]` propagates to every step so the
adjudicator can re-read the document. The reviewer and adjudicator wrap their
agents in executor functions so the prompt explicitly contains the prior
structured outputs by name.
"""

import json

from agents import (
    build_adjudicator,
    build_labeler_a,
    build_labeler_b,
    build_reviewer,
)
from agno.db.sqlite import SqliteDb
from agno.workflow import Condition, Parallel, Step, Workflow
from agno.workflow.types import StepInput, StepOutput
from schemas import DisagreementReport, LabelResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _coerce(content: object, model_cls):
    """Coerce a previous step's content into a Pydantic instance, if possible."""
    if isinstance(content, model_cls):
        return content
    if isinstance(content, dict):
        return model_cls.model_validate(content)
    if isinstance(content, str):
        try:
            return model_cls.model_validate_json(content)
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Reviewer executor: pull both labelers' outputs by name, call reviewer agent
# ---------------------------------------------------------------------------
_reviewer_agent = build_reviewer()


async def reviewer_executor(step_input: StepInput) -> StepOutput:
    outputs = step_input.previous_step_outputs or {}

    a_out = outputs.get("Labeler A")
    b_out = outputs.get("Labeler B")
    a = _coerce(a_out.content if a_out else None, LabelResult)
    b = _coerce(b_out.content if b_out else None, LabelResult)

    prompt = (
        "Compare these two labelers' outputs for the same invoice.\n\n"
        "## Labeler A\n"
        f"{json.dumps(a.model_dump() if a else None, indent=2, default=str)}\n\n"
        "## Labeler B\n"
        f"{json.dumps(b.model_dump() if b else None, indent=2, default=str)}\n"
    )

    response = await _reviewer_agent.arun(input=prompt)
    return StepOutput(content=response.content)


# ---------------------------------------------------------------------------
# Adjudicator executor: pull labelers + reviewer, call adjudicator agent with
# the original files still attached via step_input.files
# ---------------------------------------------------------------------------
_adjudicator_agent = build_adjudicator()


async def adjudicator_executor(step_input: StepInput) -> StepOutput:
    outputs = step_input.previous_step_outputs or {}

    a = _coerce(
        outputs.get("Labeler A").content if outputs.get("Labeler A") else None,
        LabelResult,
    )
    b = _coerce(
        outputs.get("Labeler B").content if outputs.get("Labeler B") else None,
        LabelResult,
    )
    review_step_output = outputs.get("Reviewer")
    review = _coerce(
        review_step_output.content if review_step_output else None,
        DisagreementReport,
    )

    prompt = (
        "Resolve every field flagged in the disagreement report below by "
        "re-reading the attached invoice.\n\n"
        "## Labeler A\n"
        f"{json.dumps(a.model_dump() if a else None, indent=2, default=str)}\n\n"
        "## Labeler B\n"
        f"{json.dumps(b.model_dump() if b else None, indent=2, default=str)}\n\n"
        "## Reviewer Report\n"
        f"{json.dumps(review.model_dump() if review else None, indent=2, default=str)}\n"
    )

    response = await _adjudicator_agent.arun(
        input=prompt,
        files=step_input.files,
    )
    return StepOutput(content=response.content)


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------
def needs_adjudication(step_input: StepInput) -> bool:
    outputs = step_input.previous_step_outputs or {}
    reviewer_out = outputs.get("Reviewer")
    if not reviewer_out:
        return False
    report = _coerce(reviewer_out.content, DisagreementReport)
    return bool(report and report.needs_adjudication)


# ---------------------------------------------------------------------------
# Build the workflow
# ---------------------------------------------------------------------------
def build_pipeline(db_file: str = "tmp/labeling.db") -> Workflow:
    labeler_a_step = Step(name="Labeler A", agent=build_labeler_a())
    labeler_b_step = Step(name="Labeler B", agent=build_labeler_b())
    reviewer_step = Step(name="Reviewer", executor=reviewer_executor)
    adjudicator_step = Step(name="Adjudicator", executor=adjudicator_executor)

    return Workflow(
        name="Invoice Labeling Pipeline",
        description="Two-labeler extraction with reviewer diff and conditional adjudication.",
        db=SqliteDb(session_table="labeling_sessions", db_file=db_file),
        steps=[
            Parallel(labeler_a_step, labeler_b_step, name="Labelers"),
            reviewer_step,
            Condition(
                name="Adjudicate If Needed",
                evaluator=needs_adjudication,
                steps=[adjudicator_step],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Run a single document for a smoke test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import asyncio

    from agno.media import File

    workflow = build_pipeline()

    sample = File(url="https://agno-public.s3.amazonaws.com/recipes/ThaiRecipes.pdf")

    asyncio.run(
        workflow.aprint_response(
            input=(
                "Extract structured fields from the attached document. "
                "Treat any document as if it were an invoice; if a field is "
                "absent, leave it null. This is a smoke test."
            ),
            files=[sample],
            markdown=True,
        )
    )
