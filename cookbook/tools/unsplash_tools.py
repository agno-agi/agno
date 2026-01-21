"""Unsplash Tools Example

This example demonstrates how to use the UnsplashTools toolkit with an AI agent
to search for and retrieve high-quality images from Unsplash.

Setup:
1. Get a free API key from https://unsplash.com/developers
2. Set the environment variable: export UNSPLASH_ACCESS_KEY="your_access_key"
3. Install the required dependencies: pip install openai

Usage:
    python unsplash_tools.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.unsplash import UnsplashTools

# Create an agent with Unsplash tools
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[UnsplashTools()],
    instructions=[
        "You are a helpful assistant that can search for high-quality images.",
        "When presenting image results, include the image URL, author name, and description.",
        "Always credit the photographer by including their name and Unsplash profile link.",
    ],
    show_tool_calls=True,
    markdown=True,
)

# Example 1: Search for photos
print("=" * 60)
print("Example 1: Searching for nature photos")
print("=" * 60)
agent.print_response(
    "Find me 3 beautiful landscape photos of mountains",
    stream=True,
)

# Example 2: Get a random photo
print("\n" + "=" * 60)
print("Example 2: Getting a random photo")
print("=" * 60)
agent.print_response(
    "Get me a random photo of a coffee shop",
    stream=True,
)

# Example 3: Search with filters
print("\n" + "=" * 60)
print("Example 3: Search with orientation filter")
print("=" * 60)
agent.print_response(
    "Find 2 portrait-oriented photos of city skylines at night",
    stream=True,
)
