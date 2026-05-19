"""
Image Classification - Multilabel
=================================

Assign any subset of N tags to an image. Useful for scene tagging and
content categorization.
"""

from typing import List, Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from agno.models.openai import OpenAIResponses
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa

SceneTag = Literal[
    "outdoor",
    "indoor",
    "daytime",
    "nighttime",
    "people",
    "vehicle",
    "nature",
    "architecture",
]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Tagging(BaseModel):
    tags: List[SceneTag] = Field(
        ..., description="All scene tags that apply; empty if none"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Tag the image with every scene attribute that clearly applies. Include a
tag only if it is unambiguously present in the image - skip tags that are
inferred or implied.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=OpenAIResponses(id="gpt-5.5"),
    instructions=instructions,
    output_schema=Tagging,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "https://upload.wikimedia.org/wikipedia/commons/0/0c/GoldenGateBridge-001.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/a/a8/Tour_Eiffel_Wikimedia_Commons.jpg",
    ]
    for url in samples:
        run: RunOutput = agent.run("Tag this image.", images=[Image(url=url)])
        pprint({"url": url, "result": run.content})
