from os import getenv

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.anthropic import Claude
from agno.os import AgentOS
from agno.tools.spotify import SpotifyTools

# Your Spotify access token (get one from https://developer.spotify.com/)
SPOTIFY_TOKEN = getenv("SPOTIFY_TOKEN")

# Initialize the Spotify toolkit
spotify = SpotifyTools(
    access_token=SPOTIFY_TOKEN,
    default_market="US",
)

# Create an agent with the Spotify toolkit
agent = Agent(
    name="Spotify Agent",
    model=Claude(id="claude-sonnet-4-5"),
    tools=[spotify],
    instructions=[
        "You are a helpful music assistant that can search for songs, manage playlists, and control playback.",
        "When creating a playlist:",
        "1. Use get_artist_top_tracks for requests about specific artists",
        "2. Use get_track_recommendations with mood parameters (target_valence for happiness, target_energy for intensity) for mood-based requests",
        "3. Use search_tracks for specific songs or general queries",
        "4. Use get_album_tracks when user wants an entire album added",
        "5. Collect track URIs and call create_playlist with them",
        "When updating a playlist:",
        "1. Use get_user_playlists to find the playlist by name",
        "2. Use the playlist ID to add or remove tracks",
        "For recommendations, use seed tracks/artists from what you've already found to get_track_recommendations.",
        "Always provide the playlist URL when created or modified.",
    ],
    markdown=True,
    db=SqliteDb(db_file="tmp/spotify_agent.db"),
    add_history_to_context=True,
    num_history_runs=5,
)

agent_os = AgentOS(
    description="Spotify Agent",
    agents=[agent],
)

app = agent_os.get_app()

# Example usage
if __name__ == "__main__":
    agent_os.serve(app="spotify_agent:app", reload=True)
