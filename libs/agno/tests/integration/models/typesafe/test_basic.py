"""Live tests for the Jev model. Need TYPESAFE_API_KEY."""

import json
from enum import IntEnum
from typing import Literal

import pytest
from pydantic import BaseModel, Field

from agno.agent import Agent, RunOutput
from agno.models.typesafe import Jev
from agno.run.base import RunStatus

URGENT_BILLING_TICKET = "I was charged twice for order A-104 and my rent is due tomorrow. Refund the duplicate today!"


class Frustration(IntEnum):
    calm = 0
    frustrated = 1
    furious = 2


class Triage(BaseModel):
    department: Literal["billing", "technical", "sales"] = Field(
        description="Which team should handle this message?",
        json_schema_extra={
            "criteria": {
                "billing": "Charges, refunds, invoices and payment methods",
                "technical": "Bugs, outages, errors and integrations",
                "sales": "Pricing questions, upgrades and new accounts",
            }
        },
    )
    is_urgent: bool = Field(description="Does the message convey urgency or time pressure?")
    frustration: Frustration = Field(
        description="How frustrated does the customer appear?",
        json_schema_extra={
            "criteria": ["Calm, just stating facts", "Frustrated but civil", "Very angry, strong language"]
        },
    )


def _assert_metrics(response: RunOutput):
    assert response.metrics is not None
    assert response.metrics.input_tokens > 0
    assert response.metrics.total_tokens == response.metrics.input_tokens + response.metrics.output_tokens


def test_output_schema():
    agent = Agent(model=Jev(), output_schema=Triage, telemetry=False)
    response = agent.run(URGENT_BILLING_TICKET)

    assert response.status == RunStatus.completed
    assert isinstance(response.content, Triage)
    assert response.content.department == "billing"
    assert response.content.is_urgent is True
    assert response.content.frustration in (Frustration.frustrated, Frustration.furious)
    _assert_metrics(response)

    data = response.model_provider_data
    assert data is not None
    assert data["mode"] == "schema"
    assert set(data["answers"]) == {"department", "is_urgent", "frustration"}
    assert 0.0 <= data["confidence"] <= 1.0
    assert data["model"].startswith("jev-")


@pytest.mark.asyncio
async def test_output_schema_async():
    agent = Agent(model=Jev(), output_schema=Triage, telemetry=False)
    response = await agent.arun(URGENT_BILLING_TICKET)
    assert isinstance(response.content, Triage)
    assert response.content.department == "billing"
    _assert_metrics(response)


def test_output_schema_stream():
    agent = Agent(model=Jev(), output_schema=Triage, telemetry=False)
    events = list(agent.run(URGENT_BILLING_TICKET, stream=True))
    # Jev answers in one piece; the stream still ends with the filled schema
    parsed = [e.content for e in events if isinstance(getattr(e, "content", None), Triage)]
    assert len(parsed) >= 1
    assert parsed[-1].department == "billing"


def test_raw_questions():
    questions = {
        "refund_requested": {"type": "noul", "instructions": "Does the customer ask for a refund?"},
        "channel": {
            "type": "choice",
            "instructions": "What is the message about?",
            "criteria": {"payment": "Money, charges, refunds", "login": "Signing in or passwords", "other": None},
        },
    }
    response = Agent(model=Jev(questions=questions), telemetry=False).run(URGENT_BILLING_TICKET)

    answers = json.loads(response.content)
    assert answers["refund_requested"]["noul"] > 0.5
    assert answers["channel"]["choice"] == "payment"
    assert set(answers["channel"]["probabilities"]) == {"payment", "login", "other"}


def test_system_message_is_context_for_the_judgment():
    class Eligibility(BaseModel):
        refund_allowed: bool = Field(
            description="Does the policy in `context` allow the refund asked for in `request`?"
        )

    agent = Agent(
        model=Jev(),
        output_schema=Eligibility,
        instructions="Refund policy: duplicate charges are always refunded in full.",
        telemetry=False,
    )
    response = agent.run("I was charged twice for the same order. Can I get the second charge back?")
    assert response.content.refund_allowed is True


def test_text_generation_is_refused():
    response = Agent(model=Jev(), telemetry=False).run("Write a haiku about autumn.")
    assert response.status == RunStatus.error
    assert "Jev cannot generate text" in response.content
