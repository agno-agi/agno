"""
Quality Review - Basic
======================

Multi-agent quality control on a labeling task. Two labelers (different
providers) extract a Contact from the input text. A reviewer compares them
and decides if adjudication is needed. If yes, an adjudicator resolves
disagreements against the original text.

This is what the original cookbook/data_labeling/ invoice pipeline did,
condensed to one file and applied to text input so the pattern stands out.
The same shape composes on top of any extraction primitive in this
directory (text, image, audio, document).
"""

from typing import List, Optional

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
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
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=LABELER_INSTRUCTIONS,
    output_schema=Contact,
)

labeler_b = Agent(
    name="Labeler B",
    model=Claude(id="claude-sonnet-4-5"),
    instructions=LABELER_INSTRUCTIONS,
    output_schema=Contact,
)

reviewer = Agent(
    name="Reviewer",
    model=OpenAIResponses(id="gpt-5.5"),
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
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="""\
Re-read the original input text and resolve every reported disagreement.
Return a FinalLabel.contact populated with the correct values for all
fields (use the agreed values for fields not in dispute).
""",
    output_schema=FinalLabel,
)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def label_with_quality_review(text: str) -> FinalLabel:
    a = labeler_a.run(text).content
    b = labeler_b.run(text).content

    review_prompt = (
        f"Labeler A:\n{a.model_dump_json(indent=2)}\n\n"
        f"Labeler B:\n{b.model_dump_json(indent=2)}"
    )
    report = reviewer.run(review_prompt).content

    if not report.needs_adjudication:
        return FinalLabel(contact=a, notes="Labelers agreed.")

    adj_prompt = (
        f"Original input:\n{text}\n\n"
        f"Labeler A:\n{a.model_dump_json(indent=2)}\n\n"
        f"Labeler B:\n{b.model_dump_json(indent=2)}\n\n"
        f"Reviewer report:\n{report.model_dump_json(indent=2)}"
    )
    return adjudicator.run(adj_prompt).content


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    text = (
        "Sarah Johnson, VP Marketing at Acme Corp. "
        "Reach me at sarah@acme.com or +1-555-0102."
    )
    pprint(label_with_quality_review(text))
