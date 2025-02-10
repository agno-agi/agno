"""🎨 Image Generation with DALL-E - Creating AI Art with Agno

This example shows how to create an AI agent that generates images using DALL-E.
You can use this agent to create various types of images, from realistic photos to artistic
illustrations and creative concepts.

Example prompts to try:
- "Create a surreal painting of a floating city in the clouds at sunset"
- "Generate a photorealistic image of a cozy coffee shop interior"
- "Design a cute cartoon mascot for a tech startup"
- "Create an artistic portrait of a cyberpunk samurai"

Run `pip install openai agno` to install dependencies.
"""

from textwrap import dedent

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.dalle import DalleTools

# Create an Creative AI Artist Agent
image_agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[DalleTools()],
    description=dedent("""\
        You are an experienced AI artist with expertise in various artistic styles,
        from photorealism to abstract art. You have a deep understanding of composition,
        color theory, and visual storytelling.\
    """),
    instructions=dedent("""\
        As an AI artist, follow these guidelines:
        1. Analyze the user's request carefully to understand the desired style and mood
        2. Before generating, enhance the prompt with artistic details like lighting, perspective, and atmosphere
        3. Use the `create_image` tool with detailed, well-crafted prompts
        4. Provide a brief explanation of the artistic choices made
        5. If the request is unclear, ask for clarification about style preferences

        Always aim to create visually striking and meaningful images that capture the user's vision!\
    """),
    markdown=True,
    show_tool_calls=True,
)

# Example usage
image_agent.print_response(
    "Create a magical library with floating books and glowing crystals", stream=True
)

# Retrieve and display generated images
images = image_agent.get_images()
if images and isinstance(images, list):
    for image_response in images:
        image_url = image_response.url
        print(f"Generated image URL: {image_url}")

# More example prompts to try:
"""
Try these creative prompts:
1. "Generate a steampunk-style robot playing a violin"
2. "Design a peaceful zen garden during cherry blossom season"
3. "Create an underwater city with bioluminescent buildings"
4. "Generate a cozy cabin in a snowy forest at night"
5. "Create a futuristic cityscape with flying cars and skyscrapers"
"""
