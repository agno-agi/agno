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

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


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
            self.create_playlist,
            self.add_tracks_to_playlist,
            self.get_playlist,
            self.update_playlist_details,
            self.remove_tracks_from_playlist,
            self.get_current_user,
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

        body = {}
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
