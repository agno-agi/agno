"""
AgentOS - Google I/O Keynote Analyzer (Video Data Labeling)
=============================================================
Serve a Gemini 3 agent through AgentOS that watches a Google I/O keynote
video and returns a structured list of products announced.

How to use:
1. Set the GOOGLE_API_KEY environment variable
2. Start the server: python cookbook/05_agent_os/google/gemini_3/data_labeling.py
3. Visit https://os.agno.com and add http://localhost:7777 as a local endpoint
4. Upload a keynote clip (or paste a YouTube URL) and run the agent

Key concepts:
- Gemini 3 understands video natively (no ffmpeg required)
- output_schema returns a typed GoogleIOAnnouncements object every run
- AgentOS exposes the agent as a FastAPI service for the UI and clients
"""

from pathlib import Path
from typing import List, Literal, Optional

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.google import Gemini
from agno.os import AgentOS
from agno.tools.youtube import YouTubeTools
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Output Schema
# ---------------------------------------------------------------------------
ProductCategory = Literal[
    "AI Model",
    "Developer Tool",
    "Consumer App",
    "Hardware",
    "Cloud Service",
    "Platform",
    "Research",
    "Other",
]


class AnnouncedProduct(BaseModel):
    name: str = Field(..., description="Product or feature name as stated on stage")
    category: ProductCategory = Field(..., description="High-level product category")
    description: str = Field(
        ...,
        description="One- or two-sentence description of the announcement",
    )
    key_features: List[str] = Field(
        default_factory=list,
        description="Distinguishing capabilities highlighted in the keynote",
    )
    availability: Optional[str] = Field(
        None,
        description="Availability or release window if stated (e.g. 'available today', 'preview in June')",
    )
    timestamp: Optional[str] = Field(
        None,
        description="Approximate timestamp in the video (mm:ss) when the announcement is made",
    )


class GoogleIOAnnouncements(BaseModel):
    event_title: str = Field(..., description="Title or theme of the keynote segment")
    summary: str = Field(
        ...,
        description="Two- to three-sentence summary of what happened in the video",
    )
    presenters: List[str] = Field(
        default_factory=list,
        description="Speakers featured in the video, if identifiable",
    )
    products: List[AnnouncedProduct] = Field(
        default_factory=list,
        description="All products and features announced in the video",
    )


# ---------------------------------------------------------------------------
# Agent Instructions
# ---------------------------------------------------------------------------
instructions = """\
You are a Google I/O keynote analyst. Watch the supplied video end-to-end and
extract every product, feature, or service that is announced or demoed.

## Rules

- Stick to what is actually shown or said in the video; do not invent products
- Record presenter names only when you can clearly attribute them
- Use mm:ss timestamps relative to the start of the clip
- Keep descriptions concise and factual
- If a product is mentioned more than once, list it a single time and merge details
- If no product announcements are present, return an empty products list and
  explain that in the summary
"""

# ---------------------------------------------------------------------------
# Database (used by AgentOS for sessions and run history)
# ---------------------------------------------------------------------------
WORKSPACE = Path(__file__).parent.joinpath("tmp")
WORKSPACE.mkdir(parents=True, exist_ok=True)
agents_db = SqliteDb(db_file=str(WORKSPACE / "google_io_agents.db"))

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------
io_analyst = Agent(
    id="google-io-analyst",
    model=Gemini(id="gemini-3.5-flash"),
    tools=[YouTubeTools()],
    db=agents_db,
    instructions=instructions,
    output_schema=GoogleIOAnnouncements,
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Create AgentOS
# ---------------------------------------------------------------------------
agent_os = AgentOS(
    id="google-io-analyzer-os",
    agents=[io_analyst],
)
app = agent_os.get_app()


# ---------------------------------------------------------------------------
# Run Example
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    agent_os.serve(app="data_labeling:app", port=7777, reload=True)
