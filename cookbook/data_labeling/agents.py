"""
Agent builders for the labeling pipeline.

Two labelers (different model providers for ensemble diversity), one reviewer
that diffs them, and one adjudicator that resolves any disagreement.

Each agent has a typed output_schema, so all outputs are Pydantic-validated.
All models opt into retries with exponential backoff for transient errors.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.models.openai import OpenAIResponses
from schemas import DisagreementReport, FinalLabel, LabelResult

# ---------------------------------------------------------------------------
# Instructions
# ---------------------------------------------------------------------------
LABELER_INSTRUCTIONS = """\
You extract structured fields from an invoice PDF that is attached to this run.

Rules:
- Use exactly what the document shows. Do not paraphrase.
- If a field is missing or illegible, leave it null. Do not guess.
- Currency must be ISO 4217 (USD, EUR, GBP, ...). Dates must be ISO yyyy-mm-dd.
- For every top-level Invoice field you populate, emit a FieldConfidence entry
  with "high", "medium", or "low" and a short note on why.
- Set overall_confidence based on the worst field-level confidence.

Return a LabelResult.
"""


REVIEWER_INSTRUCTIONS = """\
You are given two labelers' outputs for the same invoice.

Compare them field by field. A field needs adjudication if either:
- The two labelers report different non-null values, or
- Either labeler reported "low" confidence for that field.

For each field that needs adjudication, add a FieldDisagreement entry with
value_a, value_b, and a one-sentence reason.

Set needs_adjudication=true if any field needs adjudication, false otherwise.
Set any_low_confidence=true if either labeler reported any "low" confidence.

Return a DisagreementReport.
"""


ADJUDICATOR_INSTRUCTIONS = """\
You are the adjudicator. You have:
- The original invoice PDF attached to this run.
- Two labelers' outputs.
- The reviewer's disagreement report.

For every field in the disagreement report, re-read the PDF and decide the
final value. Emit an AdjudicatedField entry with the field name, the final
value as a string, and a one-sentence rationale.

Then assemble a complete FinalLabel.invoice using:
- The agreed values from the two labelers for fields not in the report.
- Your adjudicated values for fields that were in the report.

Return a FinalLabel.
"""


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def build_labeler_a() -> Agent:
    return Agent(
        name="Labeler A",
        model=OpenAIResponses(
            id="gpt-5.4",
            retries=3,
            exponential_backoff=True,
        ),
        instructions=LABELER_INSTRUCTIONS,
        output_schema=LabelResult,
    )


def build_labeler_b() -> Agent:
    return Agent(
        name="Labeler B",
        model=Claude(
            id="claude-sonnet-4-5",
            retries=3,
            exponential_backoff=True,
        ),
        instructions=LABELER_INSTRUCTIONS,
        output_schema=LabelResult,
    )


def build_reviewer() -> Agent:
    return Agent(
        name="Reviewer",
        model=OpenAIResponses(
            id="gpt-5.4",
            retries=3,
            exponential_backoff=True,
        ),
        instructions=REVIEWER_INSTRUCTIONS,
        output_schema=DisagreementReport,
    )


def build_adjudicator() -> Agent:
    return Agent(
        name="Adjudicator",
        model=OpenAIResponses(
            id="gpt-5.4",
            retries=3,
            exponential_backoff=True,
        ),
        instructions=ADJUDICATOR_INSTRUCTIONS,
        output_schema=FinalLabel,
    )
