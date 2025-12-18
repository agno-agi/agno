# Spotify Agent

An Agent that can search for songs, manage playlists, get personalized recommendations, and control playback on Spotify.

## Authentication

Set the `SPOTIFY_TOKEN` environment variable with your Spotify access token.

**Quick start:**
Go to https://developer.spotify.com/ and click "See it in action" to get a token. This works for searching, creating playlists, and getting your top tracks.

**Full access (with playback):**
Run `python spotify_auth.py` to get a token with all scopes, including playback control.

## Features

- **Top tracks & artists** - Get your most played songs and artists (last 4 weeks, 6 months, or all time)
- **Search** - Search for tracks, artists, albums, and playlists
- **Playlist management** - Create, update, and manage playlists
- **Recommendations** - Get personalized track recommendations based on seeds and mood (energy, happiness, danceability)
- **Artist top tracks** - Get any artist's most popular songs
- **Album tracks** - Add entire albums to playlists
- **Control playback** - Play, pause, skip, and seek tracks

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

### 3. Login to Spotify Dev Console and create a new application

- Go to https://developer.spotify.com/ and click "See it in action".
- Click "Create an app".
- Enter a name for your app and click "Create".
- Copy the Client ID and Client Secret.
- Set the Redirect URI to `http://127.0.0.1:8888/callback`. You can use any value you want for the callback URL. But make sure to use the same value in the `REDIRECT_URI` variable in the `spotify_auth.py` file.

### 4. Get a Spotify access token

Enter the Client ID and Client Secret you copied from the Spotify Dev Console and run the script.

```shell
python spotify_auth.py
```

Follow the instructions to get a Spotify access token. Make sure to copy the access token and set it in the `SPOTIFY_TOKEN` environment variable.

### 5. Set environment variables

```shell
export ANTHROPIC_API_KEY=xxx
export SPOTIFY_TOKEN=xxx
```

### 6. Install dependencies

```shell
pip install -U anthropic agno sqlalchemy
```

### 7. Run the agent

```shell
python spotify_agent.py
```

### 8. Connect via AgentOS

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

## Note on Playback Control

To control playback via the API, you need an active Spotify session. If you get a "No active device" error, play and pause any song in Spotify first - this registers your device with Spotify's servers and enables remote commands.
