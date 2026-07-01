"""
Image Extraction - Basic
========================

Extract typed scene attributes from an image. The output is a Pydantic
object whose schema you control.
"""

from typing import List, Literal, Optional

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class Scene(BaseModel):
    subject: str = Field(..., description="The main subject of the image")
    setting: Literal["indoor", "outdoor", "studio", "unknown"]
    time_of_day: Optional[Literal["day", "night", "dawn_or_dusk"]] = None
    dominant_colors: List[str] = Field(
        default_factory=list, description="Two to four named colors"
    )
    notable_objects: List[str] = Field(
        default_factory=list, description="Up to five named objects in the scene"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Describe the image as a structured Scene. Be concrete and observational.
If a field is not determinable from the image, leave it null or empty.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=Scene,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.amazonaws.com/images/krakow_mariacki.jpg"
    run: RunOutput = agent.run("Extract the scene attributes.", images=[Image(url=url)])
    pprint({"url": url, "result": run.content})
