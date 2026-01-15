"""
Example: Using YTMusicTools with an Agno Agent

This example shows how to create an agent that can:
- Search for songs, albums, and artists on YouTube Music
- Get detailed information about music content
- Get recommendations and radio playlists
- Get song lyrics

Note: This toolkit uses unauthenticated access only.
      Features like library management and playlist creation are not available.
"""

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.ytmusic import YTMusicTools

# Initialize the YouTube Music toolkit (unauthenticated)
ytmusic = YTMusicTools(
    language="en",
    location="US",
)

# Create an agent with the YouTube Music toolkit
agent = Agent(
    name="YouTube Music DJ",
    model=Claude(id="claude-sonnet-4-20250514"),
    tools=[ytmusic],
    instructions=[
        "You are a helpful music assistant that can search and explore YouTube Music.",
        "When searching for music, use the appropriate search method:",
        "- search_songs() for finding specific songs",
        "- search_artists() to find artist information",
        "- search_albums() to find albums",
        "- search_playlists() to find public playlists",
        "When getting recommendations, use get_watch_playlist() with a song or playlist ID.",
        "Always provide helpful information about the music you find.",
    ],
    markdown=True,
)

# Example usage
if __name__ == "__main__":
    print("YouTube Music Agent Example\n" + "=" * 50 + "\n")
    
    # Example 1: Search for songs
    print("Example 1: Searching for songs...")
    agent.print_response("Find me 5 popular songs by blink-182", stream=True)
    print("\n" + "=" * 50 + "\n")
    
    # Example 2: Get artist information
    print("Example 2: Getting artist information...")
    agent.print_response("Tell me about the artist Joji and show me some of his top songs", stream=True)
    print("\n" + "=" * 50 + "\n")
    
    # Example 3: Get recommendations
    print("Example 3: Getting song recommendations...")
    agent.print_response("Search for the song 'Rocket' by Green Day and give me similar song recommendations", stream=True)
    print("\n" + "=" * 50 + "\n")
  
    
   