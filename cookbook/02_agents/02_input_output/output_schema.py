"""
Output Schema
=============================

Use `output_schema` to return structured data that matches a Pydantic model.
"""

from typing import List

from agno.agent import Agent, RunOutput  # noqa
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


class BreakingNewsSummary(BaseModel):
    topic: str = Field(..., description="The topic or region being summarized")
    summary: str = Field(
        ..., description="A concise summary of the latest developments"
    )
    key_updates: List[str] = Field(
        ..., description="Important updates or headlines related to the topic"
    )
    overall_sentiment: str = Field(
        ..., description="Overall tone of the news coverage, such as positive or mixed"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.2"),
    description="You summarize current events into clean structured outputs.",
    output_schema=BreakingNewsSummary,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run: RunOutput = agent.run("Latest news from France?")
    pprint(run.content)
