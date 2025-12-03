# Spotify Agent

An Agent that can search for songs, manage playlists, get personalized recommendations, and control playback on Spotify.

## Authentication

Set the `SPOTIFY_TOKEN` environment variable with your Spotify access token.

To get a token for testing, go to https://developer.spotify.com/ and click "See it in action".

## Features

- **Top tracks & artists** - Get your most played songs and artists (last 4 weeks, 6 months, or all time)
- **Search** - Search for tracks, artists, albums, and playlists
- **Playlist management** - Create, update, and manage playlists
- **Recommendations** - Get personalized track recommendations based on seeds and mood (energy, happiness, danceability)
- **Artist top tracks** - Get any artist's most popular songs
- **Album tracks** - Add entire albums to playlists

## Getting Started

### 1. Clone the repository

```shell
git clone https://github.com/agno-ai/agno.git
cd agno/cookbook/examples/spotify_agent
```

### 2. Create and activate a virtual environment

```shell
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Set environment variables

```shell
export ANTHROPIC_API_KEY=xxx
export SPOTIFY_TOKEN=xxx
```

### 4. Install dependencies

```shell
pip install -U anthropic agno sqlalchemy
```

### 5. Run the agent

```shell
python spotify_agent.py
```

### 6. Connect via AgentOS

- Open [os.agno.com](https://os.agno.com/)
- Add your local AgentOS running on http://localhost:7777
- Start chatting with the Spotify Agent

## Example Prompts

- "What are my most played songs from the last 4 weeks?"
- "Who are my top artists of all time?"
- "Create a playlist of happy Eminem and Coldplay songs"
- "Add the entire Abbey Road album to my playlist"
- "Find me upbeat songs similar to Blinding Lights"
- "Update my Good Vibes playlist with more chill tracks"
