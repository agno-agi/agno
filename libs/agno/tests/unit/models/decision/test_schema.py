from enum import Enum
from typing import List, Literal, Optional

import pytest
from pydantic import BaseModel, Field, field_validator
from typing_extensions import Annotated

from agno.models.decision import (
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    Predicate,
    PredicateAnswer,
    RefusalAnswer,
    Score,
    ScoreAnswer,
)
from agno.models.decision.schema import build_output, questions_from_schema


class Tier(str, Enum):
    free = "free"
    pro = "pro"


class Ticket(BaseModel):
    """Triage a support ticket."""

    area: Annotated[Literal["billing", "technical"], Choice(options={"billing": "Money", "technical": "Bugs"})] = Field(
        description="Which team owns it"
    )
    urgent: bool = Field(description="Needs action today")
    spam: Annotated[bool, Predicate(threshold=0.8, yes="Unsolicited", no="Expected")]
    tier: Optional[Tier] = None
    severity: Annotated[int, Score(levels={"Low": "Cosmetic", "High": "Outage"})] = Field(description="How bad")
    risk: Annotated[float, Score(instructions="Churn risk", levels=["Low", "Medium", "High"])]


def test_each_field_type_maps_to_a_question():
    questions = questions_from_schema(Ticket)

    assert questions["area"] == Choice(
        instructions="Triage a support ticket.\nWhich team owns it", options={"billing": "Money", "technical": "Bugs"}
    )
    assert questions["urgent"] == Noul(instructions="Triage a support ticket.\nNeeds action today")
    assert questions["spam"] == Predicate(
        instructions="Triage a support ticket.\nspam", threshold=0.8, yes="Unsolicited", no="Expected"
    )
    assert questions["tier"] == Choice(instructions="Triage a support ticket.\ntier", options=["free", "pro"])
    assert questions["severity"] == Score(
        instructions="Triage a support ticket.\nHow bad", levels={"Low": "Cosmetic", "High": "Outage"}
    )
    assert questions["risk"].instructions == "Triage a support ticket.\nChurn risk"


def test_annotated_question_does_not_change_field_validation():
    ticket = Ticket(area="billing", urgent=True, spam=False, severity=1, risk=0.5)
    assert ticket.area == "billing"


def test_build_output_reads_each_answer_kind():
    ticket = build_output(
        Ticket,
        {
            "area": ChoiceAnswer(value="technical", probabilities={"billing": 0.1, "technical": 0.9}),
            "urgent": NoulAnswer(probability=0.9, value=True),
            "spam": PredicateAnswer(probability=0.3, value=False),
            "tier": ChoiceAnswer(value="pro", probabilities={"free": 0.2, "pro": 0.8}),
            "severity": ScoreAnswer(value=0.7, level=1, label="High", probabilities={"Low": 0.3, "High": 0.7}),
            "risk": ScoreAnswer(value=1.4, level=1, label="Medium", probabilities={}),
        },
    )
    assert ticket == Ticket(area="technical", urgent=True, spam=False, tier=Tier.pro, severity=1, risk=1.4)


def test_refusal_fills_optional_field_with_none():
    answers = {
        "area": ChoiceAnswer(value="billing", probabilities={}),
        "urgent": NoulAnswer(probability=0.1, value=False),
        "spam": PredicateAnswer(probability=0.1, value=False),
        "tier": RefusalAnswer(),
        "severity": ScoreAnswer(value=0.0, level=0, label="Low", probabilities={}),
        "risk": ScoreAnswer(value=0.0, level=0, label="Low", probabilities={}),
    }
    assert build_output(Ticket, answers).tier is None

    answers["urgent"] = RefusalAnswer()
    with pytest.raises(ValueError, match="declined to answer 'urgent'"):
        build_output(Ticket, answers)


def test_build_output_runs_schema_validators():
    class Strict(BaseModel):
        area: Literal["billing", "technical"]

        @field_validator("area")
        @classmethod
        def no_billing(cls, value: str) -> str:
            if value == "billing":
                raise ValueError("billing is closed")
            return value

    with pytest.raises(ValueError, match="billing is closed"):
        build_output(Strict, {"area": ChoiceAnswer(value="billing", probabilities={})})


class NoText(BaseModel):
    summary: str


class NoLevels(BaseModel):
    severity: int


class WrongMarker(BaseModel):
    urgent: Annotated[bool, Choice(options=["a", "b"])]


class MismatchedOptions(BaseModel):
    area: Annotated[Literal["billing", "technical"], Choice(options=["billing", "sales"])]


class NestedList(BaseModel):
    tags: List[str]


@pytest.mark.parametrize(
    "schema, message",
    [
        (NoText, "NoText.summary has type"),
        (NoLevels, "needs Annotated"),
        (WrongMarker, "takes Noul or Predicate"),
        (MismatchedOptions, "do not match"),
        (NestedList, "NestedList.tags has type"),
    ],
)
def test_unsupported_fields_are_rejected(schema, message):
    with pytest.raises(ValueError, match=message):
        questions_from_schema(schema)


def test_dict_schema_is_rejected():
    with pytest.raises(ValueError, match="pydantic BaseModel class"):
        questions_from_schema({"type": "object"})  # type: ignore[arg-type]
