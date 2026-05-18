"""
Image Classification - Basic
============================

Assign a single label from a closed set to an image. Same primitive as text
classification with image input.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    label: Literal["dog", "cat", "bird", "fish", "other"] = Field(
        ..., description="What kind of animal is in the image"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions="You classify images by animal type.",
    output_schema=Classification,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "https://upload.wikimedia.org/wikipedia/commons/4/4d/Cat_November_2010-1a.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/d/d9/Collage_of_Nine_Dogs.jpg",
    ]
    for url in samples:
        run: RunOutput = agent.run("Classify this image.", images=[Image(url=url)])
        pprint({"url": url, "result": run.content})
