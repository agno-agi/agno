"""
Spotify Toolkit for Agno SDK

A toolkit for searching songs, creating playlists, and updating playlists on Spotify.
Requires a valid Spotify access token with appropriate scopes.

Required scopes:
- user-read-private (for getting user ID)
- playlist-modify-public (for public playlists)
- playlist-modify-private (for private playlists)
"""

import json
from typing import Any, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug


class SpotifyTools(Toolkit):
    """
    Spotify toolkit for searching songs and managing playlists.

    Args:
        access_token: Spotify OAuth access token with required scopes.
        default_market: Default market/country code for search results (e.g., 'US', 'GB').
        timeout: Request timeout in seconds.
    """

    def __init__(
        self,
        access_token: str,
        default_market: Optional[str] = "US",
        timeout: int = 30,
        **kwargs,
    ):
        self.access_token = access_token
        self.default_market = default_market
        self.timeout = timeout
        self.base_url = "https://api.spotify.com/v1"

        tools: List[Any] = [
            self.search_tracks,
            self.search_playlists,
            self.search_artists,
            self.search_albums,
            self.get_user_playlists,
            self.get_track_recommendations,
            self.get_artist_top_tracks,
            self.get_album_tracks,
            self.get_my_top_tracks,
            self.get_my_top_artists,
            self.create_playlist,
            self.add_tracks_to_playlist,
            self.get_playlist,
            self.update_playlist_details,
            self.remove_tracks_from_playlist,
            self.get_current_user,
            self.play_track,
            self.get_currently_playing,
        ]

        super().__init__(name="spotify", tools=tools, **kwargs)

    def _make_request(
        self,
        endpoint: str,
        method: str = "GET",
        body: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """Make an authenticated request to the Spotify API."""
        url = f"{self.base_url}/{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.timeout) as client:
            response = client.request(
                method=method,
                url=url,
                headers=headers,
                json=body,
                params=params,
            )

            if response.status_code == 204:
                return {"success": True}

            try:
                return response.json()
            except json.JSONDecodeError:
                return {"error": f"Failed to parse response: {response.text}"}

    def get_current_user(self) -> str:
        """Get the current authenticated user's profile.

        Returns:
            JSON string containing user profile with id, display_name, and email.
        """
        log_debug("Fetching current Spotify user profile")
        result = self._make_request("me")
        return json.dumps(result, indent=2)

    def get_my_top_tracks(
        self,
        time_range: str = "medium_term",
        limit: int = 20,
    ) -> str:
        """Get the current user's most played tracks.

        Requires the 'user-top-read' scope.

        Args:
            time_range: Time period for top tracks:
                - "short_term": Last 4 weeks
                - "medium_term": Last 6 months (default)
                - "long_term": All time (several years)
            limit: Number of tracks to return (default 20, max 50).

        Returns:
            JSON string containing list of user's top tracks with id, name, artists, album, and uri.
        """
        log_debug(f"Fetching user's top tracks: {time_range}")

        params = {
            "time_range": time_range,
            "limit": min(limit, 50),
        }

        result = self._make_request("me/top/tracks", params=params)

        if "error" in result:
            return json.dumps(result, indent=2)

        tracks = result.get("items", [])
        simplified_tracks = [
            {
                "rank": i + 1,
                "id": track["id"],
                "name": track["name"],
                "artists": [artist["name"] for artist in track["artists"]],
                "album": track["album"]["name"],
                "uri": track["uri"],
                "popularity": track.get("popularity"),
            }
            for i, track in enumerate(tracks)
        ]

        return json.dumps(simplified_tracks, indent=2)

    def get_my_top_artists(
        self,
        time_range: str = "medium_term",
        limit: int = 20,
    ) -> str:
        """Get the current user's most played artists.

        Requires the 'user-top-read' scope.

        Args:
            time_range: Time period for top artists:
                - "short_term": Last 4 weeks
                - "medium_term": Last 6 months (default)
                - "long_term": All time (several years)
            limit: Number of artists to return (default 20, max 50).

        Returns:
            JSON string containing list of user's top artists with id, name, genres, and uri.
        """
        log_debug(f"Fetching user's top artists: {time_range}")

        params = {
            "time_range": time_range,
            "limit": min(limit, 50),
        }

        result = self._make_request("me/top/artists", params=params)

        if "error" in result:
            return json.dumps(result, indent=2)

        artists = result.get("items", [])
        simplified_artists = [
            {
                "rank": i + 1,
                "id": artist["id"],
                "name": artist["name"],
                "genres": artist.get("genres", []),
                "uri": artist["uri"],
                "popularity": artist.get("popularity"),
                "followers": artist.get("followers", {}).get("total"),
            }
            for i, artist in enumerate(artists)
        ]

        return json.dumps(simplified_artists, indent=2)

    def search_playlists(
        self,
        query: str,
        max_results: int = 10,
    ) -> str:
        """Search for playlists on Spotify by name.

        Use this to find playlists by name before updating them.
        Example: "Good Vibes", "Workout Mix", "Chill Beats"

        Args:
            query: Search query - playlist name or keywords.
            max_results: Maximum number of playlists to return (default 10, max 50).

        Returns:
            JSON string containing list of playlists with id, name, owner, track_count, and url.
        """
        log_debug(f"Searching Spotify for playlists: {query}")

        params = {
            "q": query,
            "type": "playlist",
            "limit": min(max_results, 50),
        }

        result = self._make_request("search", params=params)

        if "error" in result:
            return json.dumps(result, indent=2)

        playlists = result.get("playlists", {}).get("items", [])
        simplified_playlists = [
            {
                "id": playlist["id"],
                "name": playlist["name"],
                "owner": playlist["owner"]["display_name"],
                "track_count": playlist["tracks"]["total"],
                "url": playlist["external_urls"]["spotify"],
                "uri": playlist["uri"],
                "public": playlist.get("public"),
            }
            for playlist in playlists
            if playlist is not None
        ]

        return json.dumps(simplified_playlists, indent=2)

    def get_user_playlists(
        self,
        max_results: int = 20,
    ) -> str:
        """Get the current user's playlists.

        Use this to find playlists owned by or followed by the current user.
        This is more reliable than search when looking for the user's own playlists.

        Args:
            max_results: Maximum number of playlists to return (default 20, max 50).

        Returns:
            JSON string containing list of user's playlists with id, name, owner, track_count, and url.
        """
        log_debug("Fetching current user's playlists")

        params = {
            "limit": min(max_results, 50),
        }

        result = self._make_request("me/playlists", params=params)

        if "error" in result:
            return json.dumps(result, indent=2)

        playlists = result.get("items", [])
        simplified_playlists = [
            {
                "id": playlist["id"],
                "name": playlist["name"],
                "owner": playlist["owner"]["display_name"],
                "track_count": playlist["tracks"]["total"],
                "url": playlist["external_urls"]["spotify"],
                "uri": playlist["uri"],
                "public": playlist.get("public"),
            }
            for playlist in playlists
            if playlist is not None
        ]

        return json.dumps(simplified_playlists, indent=2)

    def search_artists(
        self,
        query: str,
        max_results: int = 5,
    ) -> str:
        """Search for artists on Spotify.

        Use this to find an artist's ID before getting their top tracks.

        Args:
            query: Artist name to search for.
            max_results: Maximum number of artists to return (default 5, max 50).

        Returns:
            JSON string containing list of artists with id, name, genres, popularity, and uri.
        """
        log_debug(f"Searching Spotify for artists: {query}")

        params = {
            "q": query,
            "type": "artist",
            "limit": min(max_results, 50),
        }

        result = self._make_request("search", params=params)

        if "error" in result:
            return json.dumps(result, indent=2)

        artists = result.get("artists", {}).get("items", [])
        simplified_artists = [
            {
                "id": artist["id"],
                "name": artist["name"],
                "genres": artist.get("genres", []),
                "popularity": artist.get("popularity"),
                "uri": artist["uri"],
                "followers": artist.get("followers", {}).get("total"),
            }
            for artist in artists
        ]

        return json.dumps(simplified_artists, indent=2)

    def search_albums(
        self,
        query: str,
        max_results: int = 10,
        market: Optional[str] = None,
    ) -> str:
        """Search for albums on Spotify.

        Use this to find an album's ID before getting its tracks.

        Args:
            query: Album name or artist + album name to search for.
            max_results: Maximum number of albums to return (default 10, max 50).
            market: Country code for market (e.g., 'US'). Uses default if not specified.

        Returns:
            JSON string containing list of albums with id, name, artists, release_date, total_tracks, and uri.
        """
        log_debug(f"Searching Spotify for albums: {query}")

        params = {
            "q": query,
            "type": "album",
            "limit": min(max_results, 50),
            "market": market or self.default_market,
        }

        result = self._make_request("search", params=params)

        if "error" in result:
            return json.dumps(result, indent=2)

        albums = result.get("albums", {}).get("items", [])
        simplified_albums = [
            {
                "id": album["id"],
                "name": album["name"],
                "artists": [artist["name"] for artist in album["artists"]],
                "release_date": album.get("release_date"),
                "total_tracks": album.get("total_tracks"),
                "uri": album["uri"],
                "album_type": album.get("album_type"),
            }
            for album in albums
        ]

        return json.dumps(simplified_albums, indent=2)

    def get_album_tracks(
        self,
        album_id: str,
        market: Optional[str] = None,
    ) -> str:
        """Get all tracks from an album.

        Use search_albums first to get the album_id if you don't have it.
        Useful for adding entire albums to a playlist.

        Args:
            album_id: The Spotify ID of the album.
            market: Country code for market (e.g., 'US'). Uses default if not specified.

        Returns:
            JSON string containing album info and list of tracks with id, name, track_number, duration, and uri.
        """
        log_debug(f"Fetching tracks for album: {album_id}")

        # First get album details
        album_result = self._make_request(f"albums/{album_id}", params={"market": market or self.default_market})

        if "error" in album_result:
            return json.dumps(album_result, indent=2)

        tracks = album_result.get("tracks", {}).get("items", [])
        simplified_tracks = [
            {
                "id": track["id"],
                "name": track["name"],
                "track_number": track["track_number"],
                "duration_ms": track["duration_ms"],
                "uri": track["uri"],
                "artists": [artist["name"] for artist in track["artists"]],
            }
            for track in tracks
        ]

        response = {
            "album": {
                "id": album_result["id"],
                "name": album_result["name"],
                "artists": [artist["name"] for artist in album_result["artists"]],
                "release_date": album_result.get("release_date"),
                "total_tracks": album_result.get("total_tracks"),
                "uri": album_result["uri"],
            },
            "tracks": simplified_tracks,
        }

        return json.dumps(response, indent=2)

    def get_artist_top_tracks(
        self,
        artist_id: str,
        market: Optional[str] = None,
    ) -> str:
        """Get an artist's top tracks on Spotify.

        Use search_artists first to get the artist_id if you don't have it.

        Args:
            artist_id: The Spotify ID of the artist.
            market: Country code for market (e.g., 'US'). Uses default if not specified.

        Returns:
            JSON string containing list of top tracks with id, name, album, popularity, and uri.
        """
        log_debug(f"Fetching top tracks for artist: {artist_id}")

        params = {
            "market": market or self.default_market,
        }

        result = self._make_request(f"artists/{artist_id}/top-tracks", params=params)

        if "error" in result:
            return json.dumps(result, indent=2)

        tracks = result.get("tracks", [])
        simplified_tracks = [
            {
                "id": track["id"],
                "name": track["name"],
                "artists": [artist["name"] for artist in track["artists"]],
                "album": track["album"]["name"],
                "uri": track["uri"],
                "popularity": track.get("popularity"),
                "preview_url": track.get("preview_url"),
            }
            for track in tracks
        ]

        return json.dumps(simplified_tracks, indent=2)

    def get_track_recommendations(
        self,
        seed_tracks: Optional[List[str]] = None,
        seed_artists: Optional[List[str]] = None,
        seed_genres: Optional[List[str]] = None,
        limit: int = 20,
        target_energy: Optional[float] = None,
        target_valence: Optional[float] = None,
        target_danceability: Optional[float] = None,
        target_tempo: Optional[float] = None,
    ) -> str:
        """Get track recommendations based on seed tracks, artists, or genres.

        Must provide at least one seed (track, artist, or genre). Maximum 5 seeds total.

        For mood-based playlists, use these audio features (0.0 to 1.0 scale):
        - valence: happiness (0=sad, 1=happy)
        - energy: intensity (0=calm, 1=energetic)
        - danceability: how danceable (0=least, 1=most)
        - tempo: BPM (e.g., 120 for upbeat)

        Args:
            seed_tracks: List of Spotify track IDs (not URIs) to use as seeds.
            seed_artists: List of Spotify artist IDs to use as seeds.
            seed_genres: List of genres (e.g., "pop", "hip-hop", "rock", "electronic").
            limit: Number of recommendations to return (default 20, max 100).
            target_energy: Target energy level 0.0-1.0 (higher = more energetic).
            target_valence: Target happiness level 0.0-1.0 (higher = happier).
            target_danceability: Target danceability 0.0-1.0 (higher = more danceable).
            target_tempo: Target tempo in BPM (e.g., 120).

        Returns:
            JSON string containing list of recommended tracks.
        """
        log_debug("Fetching track recommendations")

        params: dict[str, Any] = {
            "limit": min(limit, 100),
        }

        if seed_tracks:
            params["seed_tracks"] = ",".join(seed_tracks[:5])
        if seed_artists:
            params["seed_artists"] = ",".join(seed_artists[:5])
        if seed_genres:
            params["seed_genres"] = ",".join(seed_genres[:5])

        # Audio feature targets
        if target_energy is not None:
            params["target_energy"] = target_energy
        if target_valence is not None:
            params["target_valence"] = target_valence
        if target_danceability is not None:
            params["target_danceability"] = target_danceability
        if target_tempo is not None:
            params["target_tempo"] = target_tempo

        # Validate at least one seed
        if not any([seed_tracks, seed_artists, seed_genres]):
            return json.dumps({"error": "At least one seed (tracks, artists, or genres) is required"}, indent=2)

        result = self._make_request("recommendations", params=params)

        if "error" in result:
            return json.dumps(result, indent=2)

        tracks = result.get("tracks", [])
        simplified_tracks = [
            {
                "id": track["id"],
                "name": track["name"],
                "artists": [artist["name"] for artist in track["artists"]],
                "album": track["album"]["name"],
                "uri": track["uri"],
                "popularity": track.get("popularity"),
                "preview_url": track.get("preview_url"),
            }
            for track in tracks
        ]

        return json.dumps(simplified_tracks, indent=2)

    def play_track(
        self,
        track_uri: Optional[str] = None,
        context_uri: Optional[str] = None,
        device_id: Optional[str] = None,
        position_ms: int = 0,
    ) -> str:
        """Start or resume playback on the user's Spotify.

        Requires an active Spotify session (open Spotify app on any device).
        Requires the 'user-modify-playback-state' scope.

        Args:
            track_uri: Spotify URI of track to play (e.g., "spotify:track:xxx").
                      If not provided, resumes current playback.
            context_uri: Spotify URI of context to play (album, artist, playlist).
                        e.g., "spotify:playlist:xxx" or "spotify:album:xxx"
            device_id: Optional device ID to play on. Uses active device if not specified.
            position_ms: Position in milliseconds to start from (default 0).

        Returns:
            JSON string with success status or error.
        """
        log_debug(f"Starting playback: track={track_uri}, context={context_uri}")

        params = {}
        if device_id:
            params["device_id"] = device_id

        body: dict[str, Any] = {}
        if track_uri:
            body["uris"] = [track_uri]
        if context_uri:
            body["context_uri"] = context_uri
        if position_ms:
            body["position_ms"] = position_ms

        result = self._make_request(
            "me/player/play", method="PUT", body=body if body else None, params=params if params else None
        )

        if result.get("success") or not result.get("error"):
            return json.dumps({"success": True, "message": "Playback started"}, indent=2)

        # Common error: no active device
        if result.get("error", {}).get("reason") == "NO_ACTIVE_DEVICE":
            return json.dumps(
                {
                    "error": "No active Spotify device found. Please open Spotify on any device first.",
                    "reason": "NO_ACTIVE_DEVICE",
                },
                indent=2,
            )

        return json.dumps(result, indent=2)

    def get_currently_playing(self) -> str:
        """Get information about the user's current playback state.

        Returns:
            JSON string containing current track, device, progress, and playback state.
        """
        log_debug("Fetching currently playing track")

        result = self._make_request("me/player/currently-playing")

        if not result or result.get("success"):
            return json.dumps({"message": "Nothing currently playing"}, indent=2)

        if "error" in result:
            return json.dumps(result, indent=2)

        track = result.get("item", {})
        response = {
            "is_playing": result.get("is_playing"),
            "progress_ms": result.get("progress_ms"),
            "track": {
                "id": track.get("id"),
                "name": track.get("name"),
                "artists": [a["name"] for a in track.get("artists", [])],
                "album": track.get("album", {}).get("name"),
                "uri": track.get("uri"),
                "duration_ms": track.get("duration_ms"),
            }
            if track
            else None,
            "device": result.get("device", {}).get("name"),
        }

        return json.dumps(response, indent=2)

    def search_tracks(
        self,
        query: str,
        max_results: int = 10,
        market: Optional[str] = None,
    ) -> str:
        """Search for tracks on Spotify.

        Use this to find songs by name, artist, album, or any combination.
        Examples: "happy Eminem", "Coldplay Paradise", "upbeat pop songs"

        Args:
            query: Search query - can include track name, artist, genre, mood, etc.
            max_results: Maximum number of tracks to return (default 10, max 50).
            market: Country code for market (e.g., 'US'). Uses default if not specified.

        Returns:
            JSON string containing list of tracks with id, name, artists, album, uri, and preview_url.
        """
        log_debug(f"Searching Spotify for tracks: {query}")

        params = {
            "q": query,
            "type": "track",
            "limit": min(max_results, 50),
            "market": market or self.default_market,
        }

        result = self._make_request("search", params=params)

        if "error" in result:
            return json.dumps(result, indent=2)

        tracks = result.get("tracks", {}).get("items", [])
        simplified_tracks = [
            {
                "id": track["id"],
                "name": track["name"],
                "artists": [artist["name"] for artist in track["artists"]],
                "album": track["album"]["name"],
                "uri": track["uri"],
                "preview_url": track.get("preview_url"),
                "popularity": track.get("popularity"),
            }
            for track in tracks
        ]

        return json.dumps(simplified_tracks, indent=2)

    def create_playlist(
        self,
        name: str,
        description: Optional[str] = None,
        public: bool = False,
        track_uris: Optional[List[str]] = None,
    ) -> str:
        """Create a new playlist for the current user.

        Args:
            name: Name of the playlist.
            description: Optional description for the playlist.
            public: Whether the playlist should be public (default False).
            track_uris: Optional list of Spotify track URIs to add initially.
                       Format: ["spotify:track:xxx", "spotify:track:yyy"]

        Returns:
            JSON string containing the created playlist details including id, name, and url.
        """
        log_debug(f"Creating Spotify playlist: {name}")

        # First get the current user's ID
        user_response = self._make_request("me")
        if "error" in user_response:
            return json.dumps(user_response, indent=2)

        user_id = user_response["id"]

        # Create the playlist
        body = {
            "name": name,
            "description": description or "",
            "public": public,
        }

        playlist = self._make_request(f"users/{user_id}/playlists", method="POST", body=body)

        if "error" in playlist:
            return json.dumps(playlist, indent=2)

        # Add tracks if provided
        if track_uris and len(track_uris) > 0:
            add_result = self._make_request(
                f"playlists/{playlist['id']}/tracks",
                method="POST",
                body={"uris": track_uris[:100]},  # Spotify allows max 100 per request
            )

            if "error" in add_result:
                playlist["track_add_error"] = add_result["error"]
            else:
                playlist["tracks_added"] = len(track_uris[:100])

        result = {
            "id": playlist["id"],
            "name": playlist["name"],
            "description": playlist.get("description"),
            "url": playlist["external_urls"]["spotify"],
            "uri": playlist["uri"],
            "tracks_added": playlist.get("tracks_added", 0),
        }

        return json.dumps(result, indent=2)

    def add_tracks_to_playlist(
        self,
        playlist_id: str,
        track_uris: List[str],
        position: Optional[int] = None,
    ) -> str:
        """Add tracks to an existing playlist.

        Args:
            playlist_id: The Spotify ID of the playlist.
            track_uris: List of Spotify track URIs to add.
                       Format: ["spotify:track:xxx", "spotify:track:yyy"]
            position: Optional position to insert tracks (0-indexed). Appends to end if not specified.

        Returns:
            JSON string with success status and snapshot_id.
        """
        log_debug(f"Adding {len(track_uris)} tracks to playlist {playlist_id}")

        body: dict[str, Any] = {"uris": track_uris[:100]}
        if position is not None:
            body["position"] = position

        result = self._make_request(f"playlists/{playlist_id}/tracks", method="POST", body=body)

        if "snapshot_id" in result:
            return json.dumps(
                {
                    "success": True,
                    "tracks_added": len(track_uris[:100]),
                    "snapshot_id": result["snapshot_id"],
                },
                indent=2,
            )

        return json.dumps(result, indent=2)

    def remove_tracks_from_playlist(
        self,
        playlist_id: str,
        track_uris: List[str],
    ) -> str:
        """Remove tracks from a playlist.

        Args:
            playlist_id: The Spotify ID of the playlist.
            track_uris: List of Spotify track URIs to remove.
                       Format: ["spotify:track:xxx", "spotify:track:yyy"]

        Returns:
            JSON string with success status and snapshot_id.
        """
        log_debug(f"Removing {len(track_uris)} tracks from playlist {playlist_id}")

        body = {"tracks": [{"uri": uri} for uri in track_uris]}

        result = self._make_request(f"playlists/{playlist_id}/tracks", method="DELETE", body=body)

        if "snapshot_id" in result:
            return json.dumps(
                {
                    "success": True,
                    "tracks_removed": len(track_uris),
                    "snapshot_id": result["snapshot_id"],
                },
                indent=2,
            )

        return json.dumps(result, indent=2)

    def get_playlist(
        self,
        playlist_id: str,
        include_tracks: bool = True,
    ) -> str:
        """Get details of a playlist.

        Args:
            playlist_id: The Spotify ID of the playlist.
            include_tracks: Whether to include track listing (default True).

        Returns:
            JSON string containing playlist details and optionally its tracks.
        """
        log_debug(f"Fetching playlist: {playlist_id}")

        fields = "id,name,description,public,owner(display_name),external_urls"
        if include_tracks:
            fields += ",tracks.items(track(id,name,artists(name),uri))"

        result = self._make_request(f"playlists/{playlist_id}", params={"fields": fields})

        if "error" in result:
            return json.dumps(result, indent=2)

        playlist_info = {
            "id": result["id"],
            "name": result["name"],
            "description": result.get("description"),
            "public": result.get("public"),
            "owner": result.get("owner", {}).get("display_name"),
            "url": result.get("external_urls", {}).get("spotify"),
        }

        if include_tracks and "tracks" in result:
            playlist_info["tracks"] = [
                {
                    "id": item["track"]["id"],
                    "name": item["track"]["name"],
                    "artists": [a["name"] for a in item["track"]["artists"]],
                    "uri": item["track"]["uri"],
                }
                for item in result["tracks"]["items"]
                if item.get("track")
            ]

        return json.dumps(playlist_info, indent=2)

    def update_playlist_details(
        self,
        playlist_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        public: Optional[bool] = None,
    ) -> str:
        """Update a playlist's name, description, or visibility.

        Args:
            playlist_id: The Spotify ID of the playlist.
            name: New name for the playlist (optional).
            description: New description for the playlist (optional).
            public: New visibility setting (optional).

        Returns:
            JSON string with success status.
        """
        log_debug(f"Updating playlist details: {playlist_id}")

        body: dict[str, Any] = {}
        if name is not None:
            body["name"] = name
        if description is not None:
            body["description"] = description
        if public is not None:
            body["public"] = public

        if not body:
            return json.dumps({"error": "No updates provided"}, indent=2)

        result = self._make_request(f"playlists/{playlist_id}", method="PUT", body=body)

        if result.get("success") or "error" not in result:
            return json.dumps({"success": True, "updated_fields": list(body.keys())}, indent=2)

        return json.dumps(result, indent=2)
