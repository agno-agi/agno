"""
Jev Tools With a Fixed Schema
=============================

Demonstrates `JevTools(output_schema=...)`: the developer fixes the questions, the agent only
supplies the text.

This is the short leash. The agent gets an `evaluate` tool that always asks the same typed
questions, so every judgment is made the same way and the thresholds stay in your code. Use it
when the agent should check its own draft, or score incoming content, against rules you own.

`enable_ask_jev=False` removes the tool that lets the agent write its own questions.

Requirements:
- `pip install typesafe-sdk openai` (Python 3.10+)
- export TYPESAFE_API_KEY="your_api_key"
- export OPENAI_API_KEY="your_api_key"
"""

from enum import IntEnum

from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.tools.typesafe import JevTools
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Define the Questions
# ---------------------------------------------------------------------------


class Tone(IntEnum):
    cold = 0
    neutral = 1
    warm = 2


class ReplyCheck(BaseModel):
    promises_refund: bool = Field(
        description="Does the text promise or guarantee the customer a refund?"
    )
    blames_customer: bool = Field(
        description="Does the text say or imply the problem is the customer's fault?"
    )
    gives_next_step: bool = Field(
        description="Does the text tell the customer one concrete thing that happens next?"
    )
    tone: Tone = Field(
        description="How warm is the tone of the text?",
        json_schema_extra={
            "criteria": [
                "Cold or curt",
                "Neutral and businesslike",
                "Warm and personal",
            ]
        },
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    tools=[JevTools(output_schema=ReplyCheck, enable_ask_jev=False)],
    instructions=[
        "You draft replies to customer complaints.",
        "Before answering, check your draft with the evaluate tool by passing the draft as the state.",
        "A reply must not promise a refund, must not blame the customer, must give a next step, and must not be cold.",
        "If the check fails, rewrite and check again, at most twice. Then give the final reply and the check results.",
    ],
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    agent.print_response(
        "Customer: 'My blender arrived with a cracked jug. This is the second time. I want my money back.'",
        stream=True,
    )
