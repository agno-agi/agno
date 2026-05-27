"""
Image Extraction - OCR Fields
=============================

Extract text-heavy fields from an image: signs, menus, receipts, business
cards. The model reads the image and maps the visible text into a typed
schema.
"""

from typing import List, Optional

from agno.agent import Agent, RunOutput  # noqa
from agno.media import Image
from pydantic import BaseModel, Field
from rich.pretty import pprint  # noqa


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
class SignReading(BaseModel):
    primary_text: Optional[str] = Field(
        None, description="The main word or phrase shown on the sign"
    )
    secondary_text: List[str] = Field(
        default_factory=list,
        description="Any additional words shown, in reading order",
    )
    color_scheme: Optional[str] = Field(
        None, description="Dominant colors used on the sign, comma separated"
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
Read the text on the sign in the image. Return what is literally written -
do not translate, expand, or paraphrase. If the sign is partly obscured,
include what is legible and leave the rest null.
"""


# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
agent = Agent(
    model="google:gemini-3.5-flash",
    instructions=instructions,
    output_schema=SignReading,
)


# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    url = "https://agno-public.s3.us-east-1.amazonaws.com/images/agno-intro.png"
    run: RunOutput = agent.run(
        "Extract the text fields from this image.", images=[Image(url=url)]
    )
    pprint({"url": url, "result": run.content})
