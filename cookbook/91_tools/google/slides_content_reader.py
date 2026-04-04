"""
Slides Content Reader
=====================
Reads and summarizes content from existing Google Slides presentations.

The agent extracts text, metadata, and thumbnails from presentations,
providing structured summaries of slide content.

Key concepts:
- read_all_text: extracts text from every slide (handles shapes, tables, groups)
- get_slide_text: targeted text extraction from a single slide
- get_presentation_metadata: lightweight metadata (title, slide count, IDs)
- get_slide_thumbnail: retrieves slide thumbnail image URLs

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Slides API + Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from typing import List

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.slides import GoogleSlidesTools
from pydantic import BaseModel, Field


class SlideSummary(BaseModel):
    slide_id: str = Field(..., description="The slide object ID")
    slide_number: int = Field(..., description="1-based slide position")
    title: str = Field(..., description="Inferred slide title or first text element")
    key_points: List[str] = Field(
        default_factory=list, description="Key points from the slide"
    )


class PresentationSummary(BaseModel):
    title: str = Field(..., description="Presentation title")
    slide_count: int = Field(..., description="Total number of slides")
    slides: List[SlideSummary] = Field(..., description="Summary of each slide")
    overall_summary: str = Field(
        ..., description="One-paragraph summary of the entire presentation"
    )


agent = Agent(
    name="Slides Reader",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleSlidesTools()],
    instructions=[
        "Use get_presentation_metadata first to understand structure.",
        "Use read_all_text to extract all content at once.",
        "Identify the main topic of each slide from its text content.",
        "Provide a concise overall summary of the presentation.",
    ],
    output_schema=PresentationSummary,
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Summarize this presentation: https://docs.google.com/presentation/d/"
        "1nJAZYHrAe-K0OOqZ3HA1-YrY6aNO5yOIV5MosOkaIOU "
        "Extract the presentation ID from the URL and read all content.",
        stream=True,
    )

    # Summarize a specific slide
    # agent.print_response(
    #     "Get the metadata for presentation ID <your_presentation_id>, "
    #     "then extract and summarize the text from the third slide.",
    #     stream=True,
    # )

    # List and pick a presentation
    # agent.print_response(
    #     "List all my presentations, then read and summarize the most recently modified one.",
    #     stream=True,
    # )
