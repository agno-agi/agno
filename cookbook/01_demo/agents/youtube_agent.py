from textwrap import dedent

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.youtube import YouTubeTools
from db import demo_db

# ============================================================================
# Description & Instructions
# ============================================================================
description = dedent("""\
    You are the YouTube Agent — an AI Agent that analyzes YouTube videos
    and answers questions about their content with accuracy and clarity.
    """)
instructions = dedent("""
    1. When given a YouTube URL, use the `get_youtube_video_data` and `get_youtube_video_captions`
       tools to retrieve video info and captions.
    2. Use that data to answer the user's question clearly and concisely.
    3. If the answer isn't in the video, say so and ask for more details.
    4. Keep responses short, engaging, and focused on key insights.
    """)

# ============================================================================
# Create the Agent
# ============================================================================
youtube_agent = Agent(
    name="YouTube Agent",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[YouTubeTools()],
    description=description,
    instructions=instructions,
    add_history_to_context=True,
    add_datetime_to_context=True,
    markdown=True,
    db=demo_db,
)
