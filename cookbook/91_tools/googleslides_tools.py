"""
Google Slides Toolkit can be used to create, manage, and manipulate Google Slides presentations.

The toolkit supports creating presentations, adding slides with various layouts, inserting text boxes,
tables, images, and videos, as well as reading slide content and managing slide order.

Required packages:
    pip install agno google-api-python-client google-auth-httplib2 google-auth-oauthlib

Setup:
    1. Go to Google Cloud Console (https://console.cloud.google.com)
    2. Enable the Google Slides API and Google Drive API
    3. Create OAuth 2.0 credentials (Desktop app) and download the credentials.json file
    4. Place credentials.json in your working directory, or set environment variables:
        - GOOGLE_CLIENT_ID
        - GOOGLE_CLIENT_SECRET
        - GOOGLE_PROJECT_ID

    For service accounts, set: GOOGLE_SERVICE_ACCOUNT_FILE=path/to/service-account.json

Note: Destructive tools (delete_presentation, delete_slide) are disabled by default.
      Pass enable_delete_presentation=True or enable_delete_slide=True to enable them.
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.google.slides import GoogleSlidesTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------

agent = Agent(
    model=Gemini(id="gemini-2.0-flash"),
    tools=[
        GoogleSlidesTools(
            # credentials_path="credentials.json",  # Path to your downloaded OAuth credentials
            # token_path="token.json",  # Path to store the OAuth token
            oauth_port=8080,  # Port used for OAuth authentication
        )
    ],
    instructions=[
        "You are a Google Slides assistant that helps users create and manage presentations.",
        "Always call get_presentation_metadata before modifying slides to get current slide IDs.",
        "Use slide_id values returned by the API -- never guess them.",
        "Return the presentation ID and URL after creating a presentation.",
    ],
    add_datetime_to_context=True,
    markdown=True,
)

# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # Example 1: Create a presentation with multiple slide layouts
    # Tools used: create_presentation, add_slide (x5), get_presentation_metadata
    agent.print_response(
        "Create a new Google Slides presentation titled 'Quarterly Business Review'. "
        "Then add the following slides: "
        "1. A TITLE slide with title 'Q3 2025 Business Review' and subtitle 'Prepared by the Strategy Team'. "
        "2. A TITLE_AND_BODY slide with title 'Agenda' and body listing: Revenue Overview, Key Metrics, Product Roadmap, Q4 Goals. "
        "3. A TITLE_AND_TWO_COLUMNS slide with title 'Revenue Breakdown' -- "
        "left column: 'North America: $12M ARR, 23%% YoY growth' and "
        "right column: 'EMEA & APAC: $8M ARR, 31%% YoY growth'. "
        "4. A SECTION_HEADER slide with title 'Key Metrics'. "
        "5. A BLANK slide at the end.",
        stream=True,
    )

    # Example 2: Add a table and a text box to a slide
    # Tools used: get_presentation_metadata, add_table, add_text_box
    # agent.print_response(
    #     "Get the presentation metadata for the most recent presentation. "
    #     "Then on the blank slide, add a table with 4 rows and 3 columns. "
    #     "Populate it: Row 1 (header): Metric, Q2 2025, Q3 2025. "
    #     "Row 2: MRR, $1.5M, $1.8M. Row 3: Churn Rate, 3.2%%, 2.8%%. "
    #     "Row 4: NPS Score, 72, 78. "
    #     "Then add a text box at x=1.0, y=6.5, width=8.0, height=0.5 with the text "
    #     "'Source: Internal Finance Dashboard'.",
    #     stream=True,
    # )

    # Example 3: Read slide content and get thumbnails
    # Tools used: read_all_text, get_slide_text, get_thumbnail_url
    # agent.print_response(
    #     "Read all text from every slide in the most recent presentation. "
    #     "Then get the text of just the Agenda slide. "
    #     "Finally, get the thumbnail URL for the first slide.",
    #     stream=True,
    # )

    # Example 4: Duplicate a slide and reorder
    # Tools used: get_presentation_metadata, duplicate_slide, move_slides
    # agent.print_response(
    #     "Get the presentation metadata for the most recent presentation. "
    #     "Duplicate the Agenda slide, then move the copy to the end of the presentation.",
    #     stream=True,
    # )

    # Example 5: Get detailed presentation and page info
    # Tools used: get_presentation, get_page, get_presentation_metadata
    # agent.print_response(
    #     "Get the full presentation data for the most recent presentation. "
    #     "Then get the detailed page object for the first slide.",
    #     stream=True,
    # )

    # Example 6: Insert a YouTube video
    # Tools used: get_presentation_metadata, insert_youtube_video
    # agent.print_response(
    #     "Get the presentation metadata for the most recent presentation. "
    #     "Insert a YouTube video (ID: dQw4w9WgXcQ) on the blank slide at "
    #     "x=2.0, y=1.5, width=6.0, height=3.5.",
    #     stream=True,
    # )

    # Example 7: Set background image on a slide
    # Tools used: get_presentation_metadata, set_background_image
    # agent.print_response(
    #     "Get the presentation metadata for the most recent presentation. "
    #     "Set the background image of the Section Header slide to "
    #     "https://images.unsplash.com/photo-1557683316-973673baf926?w=1920",
    #     stream=True,
    # )

    # Example 8: List all presentations
    # Tools used: list_presentations
    # agent.print_response("List all my Google Slides presentations.", stream=True)
