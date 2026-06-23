"""
Slides Presentation Builder
============================
Creates a complete multi-slide presentation from a natural language brief.

The agent plans slide structure, creates the presentation, adds slides with
appropriate layouts, inserts tables with data, and adds text annotations.

Key concepts:
- create_presentation: creates a new blank presentation
- add_slide: supports TITLE, TITLE_AND_BODY, TITLE_AND_TWO_COLUMNS, BLANK, etc.
- add_table: pre-populates tables with structured data
- add_text_box: positions text annotations on slides
- get_presentation_metadata: returns page size, slide IDs, and element positions in inches

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Slides API + Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from typing import List, Optional

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.slides import GoogleSlidesTools
from pydantic import BaseModel, Field


class SlideSpec(BaseModel):
    layout: str = Field(
        ..., description="Slide layout: TITLE, TITLE_AND_BODY, BLANK, etc."
    )
    title: Optional[str] = Field(None, description="Slide title text")
    body: Optional[str] = Field(None, description="Slide body content")


class PresentationPlan(BaseModel):
    title: str = Field(..., description="Presentation title")
    slides: List[SlideSpec] = Field(..., description="Ordered list of slides to create")


agent = Agent(
    name="Presentation Builder",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleSlidesTools()],
    instructions=[
        "Create well-structured presentations with logical slide flow.",
        "Use TITLE layout for the cover slide with a subtitle.",
        "Use TITLE_AND_BODY for content slides with bullet points.",
        "Use SECTION_HEADER to divide major topics.",
        "Use BLANK slides for tables and custom layouts.",
        "Always call get_presentation_metadata to get page dimensions and element positions.",
        "Use page_width_inches and page_height_inches to position elements correctly.",
        "Check existing element positions to avoid overlaps when adding text boxes.",
        "After creating, return the presentation URL.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Create a presentation titled 'Engineering Team Q3 Review'. Include: "
        "1. A title slide with subtitle 'Performance, Goals, and Roadmap'. "
        "2. An agenda slide listing Revenue, Key Metrics, Product Updates, Q4 Goals. "
        "3. A two-column slide comparing Q2 vs Q3 metrics. "
        "4. A blank slide with a 4x3 table of KPIs (MRR, Churn Rate, NPS, DAU with Q2 and Q3 values). "
        "5. A section header for 'Q4 Goals'.",
        stream=True,
    )

    # Smart layout: use metadata to position annotations without overlaps
    # agent.print_response(
    #     "Using the presentation you just created, call get_presentation_metadata "
    #     "to check slide dimensions and element positions. Then add a text box "
    #     "annotation in the bottom-right corner of the KPI table slide that says "
    #     "'Source: Finance Dashboard, Sept 2026'. Make sure it does not overlap "
    #     "with the table.",
    #     stream=True,
    # )
