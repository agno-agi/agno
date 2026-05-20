"""
Google Slides Tools
===================
Create, manage, and read Google Slides presentations.

The agent can create presentations, add slides with various layouts, insert
text boxes, tables, images, and videos, read slide content, and manage slides.

Key concepts:
- create_presentation: creates a new blank presentation
- add_slide: adds slides with layouts (TITLE, TITLE_AND_BODY, BLANK, etc.)
- read_all_text: extracts text from all slides
- get_presentation_metadata: lightweight metadata (slide IDs, title, count)

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Slides API + Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.slides import GoogleSlidesTools

# Example 1: Basic presentation creation
agent = Agent(
    name="Slides Assistant",
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        GoogleSlidesTools(
            # delete_presentation=True,  # Destructive, enable if needed
            # delete_slide=True,          # Destructive, enable if needed
        )
    ],
    instructions=[
        "You are a Google Slides assistant.",
        "Always call get_presentation_metadata before modifying slides.",
        "Use slide_id values returned by the API -- never guess them.",
        "Return both id and url with any additional text.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Create a new Google Slides presentation titled 'Q3 2026 Business Review'. "
        "Then add a TITLE slide with title 'Q3 2026 Business Review' and subtitle "
        "'Prepared by the Strategy Team'.",
        stream=True,
    )

    # Example 2: Add slides with content
    # agent.print_response(
    #     "Add a TITLE_AND_BODY slide with title 'Agenda' and body: "
    #     "'1. Revenue Overview\n2. Key Metrics\n3. Product Roadmap\n4. Q4 Goals'. "
    #     "Then add a BLANK slide at the end.",
    #     stream=True,
    # )

    # Example 3: Add a table
    # agent.print_response(
    #     "On the blank slide, add a table with 3 rows and 2 columns: "
    #     "Row 1: 'Metric', 'Value'. Row 2: 'MRR', '$1.5M'. Row 3: 'Churn', '2.8%'.",
    #     stream=True,
    # )

    # Example 4: Read presentation content
    # agent.print_response(
    #     "Read all text from every slide and summarize what each slide contains.",
    #     stream=True,
    # )

    # Example 5: Get metadata and thumbnails
    # agent.print_response(
    #     "Get the presentation metadata, then get the thumbnail URL for the first slide.",
    #     stream=True,
    # )

    # Example 6: List presentations
    # agent.print_response(
    #     "List all my Google Slides presentations.",
    #     stream=True,
    # )
