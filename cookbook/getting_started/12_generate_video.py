"""🎥 Video Generation with ModelsLabs - Creating AI Videos with Agno

This example shows how to create an AI agent that generates videos using ModelsLabs.
You can use this agent to create various types of short videos, from animated scenes
to creative visual stories.

Example prompts to try:
- "Create a serene video of waves crashing on a beach at sunset"
- "Generate a magical video of butterflies flying in a enchanted forest"
- "Create a timelapse of a blooming flower in a garden"
- "Generate a video of northern lights dancing in the night sky"

Run `pip install openai agno` to install dependencies.
Remember to set your ModelsLabs API key in the environment variable `MODELS_LAB_API_KEY`.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.models_labs import ModelsLabTools

# Create a Creative AI Video Director Agent
video_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[ModelsLabTools()],
    description=dedent("""\
        You are an experienced AI video director with expertise in various video styles,
        from nature scenes to artistic animations. You have a deep understanding of motion,
        timing, and visual storytelling through video content.\
    """),
    instructions=dedent("""\
        As an AI video director, follow these guidelines:
        1. Analyze the user's request carefully to understand the desired style and mood
        2. Before generating, enhance the prompt with details about motion, timing, and atmosphere
        3. Use the `generate_media` tool with detailed, well-crafted prompts
        4. Provide a brief explanation of the creative choices made
        5. If the request is unclear, ask for clarification about style preferences

        The video will be displayed in the UI automatically below your response.
        Always aim to create captivating and meaningful videos that bring the user's vision to life!\
    """),
    markdown=True,
    show_tool_calls=True,
)

# Example usage
video_agent.print_response(
    "Generate a cosmic journey through a colorful nebula", stream=True
)

# Retrieve and display generated videos
videos = video_agent.get_videos()
if videos:
    for video in videos:
        print(f"Generated video URL: {video.url}")

# More example prompts to try:
"""
Try these creative prompts:
1. "Create a video of autumn leaves falling in a peaceful forest"
2. "Generate a video of a cat playing with a ball"
3. "Create a video of a peaceful koi pond with rippling water"
4. "Generate a video of a cozy fireplace with dancing flames"
5. "Create a video of a mystical portal opening in a magical realm"
"""
