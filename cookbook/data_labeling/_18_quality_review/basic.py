"""
Quality Review - Basic
======================

Multi-agent quality control on a labeling task, expressed as an agno
Workflow. Two labelers (different providers) run concurrently, a reviewer
diffs them field by field, and an adjudicator runs only when the reviewer
flags disagreement. Every run is persisted to SQLite for traceability.

The same shape composes on top of any extraction primitive in this
directory (text, image, audio, document).
"""

from typing import List, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.models.google import Gemini
from agno.workflow import Step, Workflow
from agno.workflow.condition import Condition
from agno.workflow.parallel import Parallel
from agno.workflow.types import StepInput, StepOutput
from pydantic import BaseModel, Field
from rich.pretty import pprint


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class Contact(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None


class FieldDisagreement(BaseModel):
    field: str = Field(..., description="Top-level Contact field name")
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    reason: str = Field(..., description="Why this field needs adjudication")


class DisagreementReport(BaseModel):
    disagreements: List[FieldDisagreement] = Field(default_factory=list)
    needs_adjudication: bool = Field(..., description="True if any field disagrees")


class FinalLabel(BaseModel):
    contact: Contact
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Create Agents
# ---------------------------------------------------------------------------
LABELER_INSTRUCTIONS = """\
Extract contact information from the input. Use exactly what the text
shows. If a field is missing, leave it null. Do not guess.
"""

labeler_a = Agent(
    name="Labeler A",
    model=Gemini(id="gemini-3.5-flash"),
    instructions=LABELER_INSTRUCTIONS,
    output_schema=Contact,
)

labeler_b = Agent(
    name="Labeler B",
    model=Claude(id="claude-opus-4-7"),
    instructions=LABELER_INSTRUCTIONS,
    output_schema=Contact,
)

reviewer = Agent(
    name="Reviewer",
    model=Claude(id="claude-opus-4-7"),
    instructions="""\
You are given two labelers' Contact outputs. Compare them field by field.
A field needs adjudication when both labelers report non-null but
different values. Emit one FieldDisagreement per such field. Set
needs_adjudication=true if any field needs adjudication.
""",
    output_schema=DisagreementReport,
)

adjudicator = Agent(
    name="Adjudicator",
    model=Claude(id="claude-opus-4-7"),
    instructions="""\
Re-read the original input text and resolve every reported disagreement.
Return a FinalLabel.contact populated with the correct values for all
fields (use the agreed values for fields not in dispute).
""",
    output_schema=FinalLabel,
)


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
# Labelers are plain agent steps; they run in parallel below.
label_a = Step(name="Labeler A", agent=labeler_a)
label_b = Step(name="Labeler B", agent=labeler_b)


# Reviewer needs both labelers' outputs in its prompt, so wrap it in an
# executor that pulls them out by step name. get_step_output() recursively
# searches nested steps, so it finds labelers inside the Parallel block.
def run_reviewer(step_input: StepInput) -> StepOutput:
    a = step_input.get_step_output("Labeler A").content
    b = step_input.get_step_output("Labeler B").content
    prompt = (
        f"Labeler A:\n{a.model_dump_json(indent=2)}\n\n"
        f"Labeler B:\n{b.model_dump_json(indent=2)}"
    )
    report = reviewer.run(prompt).content
    return StepOutput(content=report)


review = Step(name="Reviewer", executor=run_reviewer)


# Adjudicator needs the original input, both labeler outputs, and the
# reviewer's report.
def run_adjudicator(step_input: StepInput) -> StepOutput:
    a = step_input.get_step_output("Labeler A").content
    b = step_input.get_step_output("Labeler B").content
    report = step_input.get_step_output("Reviewer").content
    prompt = (
        f"Original input:\n{step_input.input}\n\n"
        f"Labeler A:\n{a.model_dump_json(indent=2)}\n\n"
        f"Labeler B:\n{b.model_dump_json(indent=2)}\n\n"
        f"Reviewer report:\n{report.model_dump_json(indent=2)}"
    )
    final = adjudicator.run(prompt).content
    return StepOutput(content=final)


adjudicate = Step(name="Adjudicator", executor=run_adjudicator)


# Run the adjudicator only when the reviewer flagged a disagreement.
def has_disagreement(step_input: StepInput) -> bool:
    report = step_input.previous_step_content
    return bool(report and getattr(report, "needs_adjudication", False))


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------
workflow = Workflow(
    name="Quality review labeling",
    db=SqliteDb(db_file="tmp/labeling.db"),  # every run is persisted
    steps=[
        Parallel(label_a, label_b, name="Label"),  # labelers run concurrently
        review,  # diff them field by field
        Condition(  # adjudicate only on disagreement
            name="Adjudicate",
            evaluator=has_disagreement,
            steps=[adjudicate],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    text = (
        "Sarah Johnson, VP Marketing at Acme Corp. "
        "Reach me at sarah@acme.com or +1-555-0102."
    )
    response = workflow.run(input=text)
    pprint(response.content)
