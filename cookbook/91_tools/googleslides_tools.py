"""Google Slides Toolkit - Comprehensive Cookbook Example

This cookbook demonstrates how to use the GoogleSlidesTools toolkit
to create, manage, and manipulate Google Slides presentations.

Required packages:
    pip install agno google-api-python-client google-auth-httplib2 google-auth-oauthlib

Required Environment Variables:
    GOOGLE_CLIENT_ID: Google OAuth client ID
    GOOGLE_CLIENT_SECRET: Google OAuth client secret
    GOOGLE_PROJECT_ID: Google Cloud project ID
    GOOGLE_REDIRECT_URI: (optional) defaults to http://localhost

    OR for service accounts:
    GOOGLE_SERVICE_ACCOUNT_FILE: path to service-account.json

Setup:
    1. Go to Google Cloud Console (https://console.cloud.google.com)
    2. Enable the Google Slides API and Google Drive API
    3. Create OAuth 2.0 credentials
    4. Set environment variables in a .envrc or .env file
"""

from agno.agent import Agent
from agno.models.google import Gemini
from agno.tools.google.slides import GoogleSlidesTools

# ──────────────────────────────────────────────
# 1. Basic: Create a presentation
# ──────────────────────────────────────────────

"""
- For destructive operations like delete_slide, you need to enable the tool by passing enable_delete_slide=True to the constructor.
- Use session or memory to store the presentation id and slide ids.
- if you are not prefer to use session or memory, you can pass the presentation id in the instructions in runtime.
"""
agent = Agent(
    name="Slides Assistant",
    model=Gemini(id="gemini-2.0-flash-lite"),
    tools=[
        GoogleSlidesTools(
            # enable_delete_presentation = True,  # -> Destructive tool, enable if required
            # enable_delete_slide = True,  # -> Destructive tool, enable if required
            oauth_port=8080,
        )
    ],
    instructions=[
        "You are a Google Slides assistant.",
        "Always call get_presentation_metadata before modifying slides.",
        "Use slide_id values returned by the API — never guess them.",
        "Return both id and url with any additional text.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    # Create a new presentation
    agent.print_response(
        "Create a new Google Slides presentation titled 'Q3 2026 Business Review'",
        stream=True,
    )

    # ──────────────────────────────────────────────
    # 2. Add slides with different layouts and text
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     """Using the presentation you just created:
    #     1. Add a TITLE slide with title 'Q3 2026 Business Review' and subtitle 'Prepared by the Strategy Team'
    #     2. Add a TITLE_AND_BODY slide with title 'Agenda' and body:
    #     '1. Revenue Overview\n2. Key Metrics\n3. Product Roadmap\n4. Q4 Goals'
    #     3. Add a TITLE_AND_TWO_COLUMNS slide with title 'Revenue Breakdown',
    #     body 'North America:\n- $12M ARR\n- 23% YoY growth',
    #     and body_2 'EMEA & APAC:\n- $8M ARR\n- 31% YoY growth'
    #     4. Add a SECTION_HEADER slide with title 'Key Metrics'
    #     5. Add a BLANK slide at the end
    #     """,
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 3. Add a table with data
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     """On the blank slide you just created, add a table with 4 rows and 3 columns.
    #     Populate it with this data:
    #     Row 1 (header): 'Metric', 'Q2 2026', 'Q3 2026'
    #     Row 2: 'MRR', '$1.5M', '$1.8M'
    #     Row 3: 'Churn Rate', '3.2%', '2.8%'
    #     Row 4: 'NPS Score', '72', '78'
    #     """,
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 4. Add text boxes for annotations
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     """On the 'Revenue Breakdown' slide, add a text box at the bottom
    #     (x=1.0, y=6.5, width=8.0, height=0.5) with the text:
    #     'Source: Internal Finance Dashboard — Updated Sept 2026'
    #     """,
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 5. Set a background image
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     """Set the background image of the 'Key Metrics' section header slide to:
    #     https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1920
    #     """,
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 6. Embed a YouTube video
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     """Add a new TITLE_ONLY slide with title 'Product Demo'.
    #     Then embed a YouTube video with ID 'dQw4w9WgXcQ' on that slide,
    #     positioned at x=2.0, y=1.8 with width=6.0 and height=3.5.
    #     """,
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 7. Duplicate and reorder slides
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     """Duplicate the 'Agenda' slide.
    #     Then move the duplicated slide to the end of the presentation.
    #     """,
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 8. Read all text from the presentation
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     "Read all text from every slide in the presentation and summarize what each slide contains.",
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 9. Get metadata and thumbnails
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     """Get the presentation metadata (title, slide count, slide IDs).
    #     Then get the thumbnail URL for the first slide.
    #     """,
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 10. Get specific slide content
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     "Get the full page content of the 'Revenue Breakdown' slide, then extract just its text.",
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 11. Batch update (advanced)
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     """Using batch_update_presentation, perform these operations on the presentation:
    #     1. Create a new shape (TEXT_BOX) on the first slide
    #     2. Insert the text 'CONFIDENTIAL' into that shape
    #     Make sure to use valid objectIds and the correct slide ID.
    #     """,
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 12. Delete a slide
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     "Delete the blank slide from the presentation.",
    #     stream=True,
    # )

    # ──────────────────────────────────────────────
    # 13. List and clean up
    # ──────────────────────────────────────────────

    # agent.print_response(
    #     "List all my Google Slides presentations.",
    #     stream=True,
    # )

    # Uncomment to delete the presentation when done:
    # agent.print_response(
    #     "Delete the 'Q3 2026 Business Review' presentation.",
    #     stream=True,
    # )
