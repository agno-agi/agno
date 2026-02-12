"""Unsplash Tools Example

This example demonstrates how to use the UnsplashTools toolkit with an AI agent
to search for and retrieve high-quality, royalty-free images from Unsplash.

UnsplashTools provides:
- search_photos: Search photos by keyword with filters (orientation, color)
- get_photo: Get detailed info about a specific photo
- get_random_photo: Get random photo(s) with optional query
- download_photo: Track downloads for Unsplash API compliance

Setup:
1. Get a free API key from https://unsplash.com/developers
2. Set the environment variable: export UNSPLASH_ACCESS_KEY="your_access_key"
3. Install dependencies: pip install openai agno

Usage:
    python unsplash_tools.py
"""

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.unsplash import UnsplashTools

# ---------------------------------------------------------------------------
# Create Agent
# ---------------------------------------------------------------------------


# Example 1: Basic usage with default tools
# By default, search_photos, get_photo, and get_random_photo are enabled
agent = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[UnsplashTools()],
    instructions=[
        "You are a helpful assistant that can search for high-quality images.",
        "When presenting image results, include the image URL, author name, and description.",
        "Always credit the photographer by including their name and Unsplash profile link.",
    ],
    markdown=True,
)

# Example 2: Enable all tools including download tracking
# Use this when you need to comply with Unsplash's download tracking requirement
agent_with_download = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[UnsplashTools(enable_download_photo=True)],
    instructions=[
        "You are a helpful assistant that can search for high-quality images.",
        "When a user wants to use/download an image, use the download_photo tool to track it.",
    ],
    markdown=True,
)

# Example 3: Enable only specific tools
agent_search_only = Agent(
    model=OpenAIChat(id="gpt-4o"),
    tools=[
        UnsplashTools(
            enable_search_photos=True,
            enable_get_photo=False,
            enable_get_random_photo=False,
        )
    ],
    markdown=True,
)

# Run examples
# ---------------------------------------------------------------------------
# Run Agent
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Search for photos
    print("=" * 60)
    print("Example 1: Searching for nature photos")
    print("=" * 60)
    agent.print_response(
        "Find me 3 beautiful landscape photos of mountains",
        stream=True,
    )

    # Get a random photo
    print("\n" + "=" * 60)
    print("Example 2: Getting a random photo")
    print("=" * 60)
    agent.print_response(
        "Get me a random photo of a coffee shop",
        stream=True,
    )

    # Search with filters
    print("\n" + "=" * 60)
    print("Example 3: Search with orientation filter")
    print("=" * 60)
    agent.print_response(
        "Find 2 portrait-oriented photos of city skylines at night",
        stream=True,
    )

# --- Download Compliance Note ---
#
# The download_photo tool exists for Unsplash API compliance.
# According to Unsplash API guidelines, you must trigger the download endpoint
# when a photo is actually downloaded or used in your application.
#
# What download_photo does:
# - Calls /photos/{id}/download to increment the photographer's download count
# - Returns a time-limited download URL
# - Does NOT download the image file itself
#
# This is required for proper attribution tracking and is part of Unsplash's
# terms of service. The tool is disabled by default (enable_download_photo=False)
# since it's only needed when actually using/downloading images.
#
# See: https://unsplash.com/documentation#track-a-photo-download
