"""
Jev Basic
=========

Demonstrates Jev, TypeSafe's System One model, filling an `output_schema`.

Jev does not write text. It reads the input and answers typed questions about it, each with a
calibrated probability. The `output_schema` is the list of questions:

- a `Literal` or `Enum` field is a pick-one question
- a `bool` field is a yes/no question
- an `IntEnum` field is a rating along ordered levels
- the field description is the question Jev is asked

Requirements:
- `pip install typesafe-sdk` (Python 3.10+)
- export TYPESAFE_API_KEY="your_api_key"   (https://console.typesafe.ai/keys)
"""

import json
from enum import IntEnum
from typing import Literal

from agno.agent import Agent
from agno.models.typesafe import Jev
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define the Questions
# ---------------------------------------------------------------------------


class Frustration(IntEnum):
    calm = 0
    frustrated = 1
    furious = 2


class Triage(BaseModel):
    department: Literal["billing", "technical", "sales"] = Field(
        description="Which team should handle this message?",
        # Describing each option sharpens the boundary between them
        json_schema_extra={
            "criteria": {
                "billing": "Charges, refunds, invoices and payment methods",
                "technical": "Bugs, outages, errors and integrations",
                "sales": "Pricing questions, upgrades and new accounts",
            }
        },
    )
    is_urgent: bool = Field(
        description="Does the message convey urgency or time pressure?"
    )
    frustration: Frustration = Field(
        description="How frustrated does the customer appear?",
        json_schema_extra={
            "criteria": [
                "Calm, just stating facts",
                "Frustrated but civil",
                "Very angry, strong language",
            ]
        },
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(model=Jev(), output_schema=Triage)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run = agent.run(
        "I've been trying to connect my Stripe account for 3 days and the integration keeps failing. "
        "I'm losing sales. Please help ASAP."
    )

    triage: Triage = run.content
    print("department: ", triage.department)
    print("is_urgent:  ", triage.is_urgent)
    print("frustration:", triage.frustration.name)

    # Every probability and confidence behind the result
    print("\nWhat Jev decided:")
    print(json.dumps(run.model_provider_data, indent=2))
    print(
        "\nTokens:", run.metrics.input_tokens, "in /", run.metrics.output_tokens, "out"
    )
