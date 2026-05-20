"""
Slides Media and Rich Content
==============================
Adds images, YouTube videos, and styled backgrounds to presentations.

The agent creates visually rich slides by embedding media content from
external URLs and Google Drive.

Key concepts:
- set_background_image: sets a slide background from a public image URL
- insert_youtube_video: embeds a YouTube player on a slide
- insert_drive_video: embeds a Google Drive video on a slide
- add_text_box: positions text annotations alongside media

Setup:
1. Create OAuth credentials at https://console.cloud.google.com (enable Slides API + Drive API)
2. Export GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_PROJECT_ID env vars
3. pip install openai google-api-python-client google-auth-httplib2 google-auth-oauthlib
4. First run opens browser for OAuth consent, saves token.json for reuse
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.google.slides import GoogleSlidesTools

agent = Agent(
    name="Media Slides Agent",
    model=OpenAIChat(id="gpt-4o"),
    tools=[GoogleSlidesTools()],
    instructions=[
        "Create visually engaging slides with media content.",
        "Use BLANK or TITLE_ONLY layouts for media slides.",
        "Position videos and text boxes to avoid overlap.",
        "Always use get_presentation_metadata to get slide IDs before modifications.",
        "Add descriptive text boxes near embedded media.",
        "Return the presentation URL when done.",
    ],
    markdown=True,
)


if __name__ == "__main__":
    agent.print_response(
        "Create a presentation titled 'Product Launch'. "
        "1. Add a TITLE_ONLY slide titled 'Product Demo'. "
        "2. Embed a YouTube video with ID 'dQw4w9WgXcQ' on that slide "
        "at x=2.0, y=1.8 with width=6.0 and height=3.5. "
        "3. Add a text box below the video at y=5.5 with text "
        "'Watch our product walkthrough'.",
        stream=True,
    )

    # Set background image on a slide
    # agent.print_response(
    #     "Using the presentation you just created, add a SECTION_HEADER slide "
    #     "titled 'Our Vision'. Then set its background image to "
    #     "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=1920",
    #     stream=True,
    # )

    # Combine multiple media types
    # agent.print_response(
    #     "Add a BLANK slide to the presentation. "
    #     "Set a dark background image, then add a centered text box "
    #     "with 'Coming Soon' at y=3.0.",
    #     stream=True,
    # )
