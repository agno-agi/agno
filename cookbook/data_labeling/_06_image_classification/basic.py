"""
Image Classification - Basic
============================

Assign a single label from a closed set to an image. Same primitive as text
classification with image input.
"""

from typing import Literal

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from agno.models.google import Gemini
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Classification(BaseModel):
    label: Literal["wildlife", "landscape", "sports", "architecture", "other"] = Field(
        ..., description="The primary scene type of the image"
    )


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model=Gemini(id="gemini-3.5-flash"),
    instructions="You classify images by scene type.",
    output_schema=Classification,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    samples = [
        "https://storage.googleapis.com/generativeai-downloads/images/generated_elephants_giraffes_zebras_sunset.jpg",
        "https://www.gstatic.com/webp/gallery/1.jpg",
        "https://www.gstatic.com/webp/gallery/2.jpg",
        "https://agno-public.s3.amazonaws.com/images/krakow_mariacki.jpg",
    ]
    for url in samples:
        run: RunOutput = agent.run("Classify this image.", images=[Image(url=url)])
        pprint({"url": url, "result": run.content})
