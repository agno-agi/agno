"""
YouTube Music Toolkit for Agno SDK

A toolkit for searching songs, browsing albums and artists, and getting recommendations on
YouTube Music. Uses the ytmusicapi library with unauthenticated access.

Note: This toolkit only supports public features that don't require authentication.
      Features like library management and playlist creation are not available.
"""

import json
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from ytmusicapi import YTMusic
except ImportError:
    raise ImportError("`ytmusicapi` not installed. Please install using `pip install ytmusicapi`")


class YTMusicTools(Toolkit):
    """
    YouTube Music toolkit for searching songs and browsing music content.

    Args:
        language: Language for the API responses (e.g., 'en', 'de', 'fr').
        location: Location for the API responses (e.g., 'US', 'DE', 'GB').
    """

    def __init__(
        self,
        language: str = "en",
        location: str = "US",
        **kwargs,
    ):
        self.language = language
        self.location = location
        
        # Initialize YTMusic client (unauthenticated)
        try:
            self.ytmusic = YTMusic(language=language, location=location)
        except Exception as e:
            raise RuntimeError(f"Failed to initialize YTMusic client: {e}")

        tools: List[Any] = [
            self.search,
            self.search_songs,
            self.search_albums,
            self.search_artists,
            self.search_playlists,
            self.get_song,
            self.get_album,
            self.get_artist,
            self.get_artist_albums,
            self.get_playlist,
            self.get_watch_playlist,
            self.get_lyrics,
        ]

        super().__init__(name="ytmusic", tools=tools, **kwargs)

    def search(
        self,
        query: str,
        filter: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """Search YouTube Music for songs, albums, artists, playlists, or videos.

        Use this for general search when you don't know the exact type of content.
        For specific searches, use the dedicated search methods.

        Args:
            query: Search query (e.g., "Bohemian Rhapsody Queen", "Drake", "chill playlist").
            filter: Filter results by type. Options: 'songs', 'videos', 'albums', 'artists',
                   'playlists', 'community_playlists', 'featured_playlists', 'uploads'.
                   If not specified, returns mixed results.
            limit: Number of results to return (default 20, max 50).

        Returns:
            JSON string containing search results with videoId, title, artists, album, and more.
        """
        log_debug(f"Searching YouTube Music: {query} (filter: {filter})")
        
        try:
            results = self.ytmusic.search(query=query, filter=filter, limit=min(limit, 50))
            
            # Simplify results based on type
            simplified_results = []
            for item in results:
                result_type = item.get("resultType", "unknown")
                
                if result_type in ["song", "video"]:
                    simplified_results.append({
                        "type": result_type,
                        "videoId": item.get("videoId"),
                        "title": item.get("title"),
                        "artists": [a.get("name") for a in item.get("artists", [])],
                        "album": item.get("album", {}).get("name") if item.get("album") else None,
                        "duration": item.get("duration"),
                        "thumbnails": item.get("thumbnails", []),
                    })
                elif result_type == "album":
                    simplified_results.append({
                        "type": "album",
                        "browseId": item.get("browseId"),
                        "playlistId": item.get("playlistId"),
                        "title": item.get("title"),
                        "artists": item.get("artist") if isinstance(item.get("artist"), str) else item.get("artists"),
                        "year": item.get("year"),
                        "thumbnails": item.get("thumbnails", []),
                    })
                elif result_type == "artist":
                    simplified_results.append({
                        "type": "artist",
                        "browseId": item.get("browseId"),
                        "artist": item.get("artist"),
                        "thumbnails": item.get("thumbnails", []),
                    })
                elif result_type == "playlist":
                    simplified_results.append({
                        "type": "playlist",
                        "browseId": item.get("browseId"),
                        "playlistId": item.get("playlistId"),
                        "title": item.get("title"),
                        "author": item.get("author"),
                        "itemCount": item.get("itemCount"),
                        "thumbnails": item.get("thumbnails", []),
                    })
                else:
                    simplified_results.append(item)
            
            return json.dumps(simplified_results, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    def search_songs(
        self,
        query: str,
        limit: int = 10,
    ) -> str:
        """Search specifically for songs on YouTube Music.

        Args:
            query: Search query (e.g., "Wonderwall Oasis", "happy songs", "rock 2020s").
            limit: Number of songs to return (default 10, max 50).

        Returns:
            JSON string containing list of songs with videoId, title, artists, album, duration.
        """
        log_debug(f"Searching for songs: {query}")
        return self.search(query=query, filter="songs", limit=limit)

    def search_albums(
        self,
        query: str,
        limit: int = 10,
    ) -> str:
        """Search for albums on YouTube Music.

        Args:
            query: Album name or artist + album (e.g., "Abbey Road", "Beatles Abbey Road").
            limit: Number of albums to return (default 10, max 50).

        Returns:
            JSON string containing list of albums with browseId, title, artist, year.
        """
        log_debug(f"Searching for albums: {query}")
        return self.search(query=query, filter="albums", limit=limit)

    def search_artists(
        self,
        query: str,
        limit: int = 5,
    ) -> str:
        """Search for artists on YouTube Music.

        Use this to find an artist's ID before getting their albums or top songs.

        Args:
            query: Artist name (e.g., "Taylor Swift", "The Beatles").
            limit: Number of artists to return (default 5, max 50).

        Returns:
            JSON string containing list of artists with browseId, name, thumbnails.
        """
        log_debug(f"Searching for artists: {query}")
        return self.search(query=query, filter="artists", limit=limit)

    def search_playlists(
        self,
        query: str,
        limit: int = 10,
    ) -> str:
        """Search for playlists on YouTube Music.

        Args:
            query: Playlist name or keywords (e.g., "Chill Vibes", "Workout Mix").
            limit: Number of playlists to return (default 10, max 50).

        Returns:
            JSON string containing list of playlists with playlistId, title, author, itemCount.
        """
        log_debug(f"Searching for playlists: {query}")
        return self.search(query=query, filter="playlists", limit=limit)

    def get_song(
        self,
        videoId: str,
    ) -> str:
        """Get detailed information about a specific song.

        Args:
            videoId: The YouTube Music video ID of the song.

        Returns:
            JSON string containing detailed song information including videoDetails and streamingData.
        """
        log_debug(f"Fetching song details: {videoId}")
        
        try:
            result = self.ytmusic.get_song(videoId=videoId)
            
            # Extract relevant information
            video_details = result.get("videoDetails", {})
            
            simplified = {
                "videoId": video_details.get("videoId"),
                "browseId":video_details.get("browseId"),
                "title": video_details.get("title"),
                "lengthSeconds": video_details.get("lengthSeconds"),
                "channelId": video_details.get("channelId"),
                "isOwnerViewing": video_details.get("isOwnerViewing"),
                "shortDescription": video_details.get("shortDescription"),
                "isCrawlable": video_details.get("isCrawlable"),
                "thumbnails": video_details.get("thumbnail", {}).get("thumbnails", []),
                "viewCount": video_details.get("viewCount"),
                "author": video_details.get("author"),
            }
            
            return json.dumps(simplified, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    def get_album(
        self,
        browseId: str,
    ) -> str:
        """Get all tracks and information about an album.

        Use search_albums first to get the browseId if you don't have it.

        Args:
            browseId: The album's browse ID from search results.

        Returns:
            JSON string containing album info and list of tracks with videoId, title, duration.
        """
        log_debug(f"Fetching album: {browseId}")
        
        try:
            result = self.ytmusic.get_album(browseId=browseId)
            
            simplified = {
                "title": result.get("title"),
                "type": result.get("type"),
                "thumbnails": result.get("thumbnails", []),
                "description": result.get("description"),
                "artists": [{"name": a.get("name"), "id": a.get("id")} for a in result.get("artists", [])],
                "year": result.get("year"),
                "trackCount": result.get("trackCount"),
                "duration": result.get("duration"),
                "audioPlaylistId": result.get("audioPlaylistId"),
                "tracks": [
                    {
                        "videoId": track.get("videoId"),
                        "title": track.get("title"),
                        "artists": [a.get("name") for a in track.get("artists", [])],
                        "duration": track.get("duration"),
                        "likeStatus": track.get("likeStatus"),
                        "isExplicit": track.get("isExplicit"),
                    }
                    for track in result.get("tracks", [])
                ],
            }
            
            return json.dumps(simplified, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    def get_artist(
        self,
        channelId: str,
    ) -> str:
        """Get information about an artist including their songs, albums, and singles.

        Use search_artists first to get the channelId/browseId if you don't have it.

        Args:
            channelId: The artist's channel ID or browse ID from search results.

        Returns:
            JSON string containing artist info, top songs, albums, singles, and related artists.
        """
        log_debug(f"Fetching artist: {channelId}")
        
        try:
            result = self.ytmusic.get_artist(channelId=channelId)
            
            simplified = {
                "name": result.get("name"),
                "description": result.get("description"),
                "views": result.get("views"),
                "channelId": result.get("channelId"),
                "shuffleId": result.get("shuffleId"),
                "radioId": result.get("radioId"),
                "subscribers": result.get("subscribers"),
                "thumbnails": result.get("thumbnails", []),
                "songs": {
                    "browseId": result.get("songs", {}).get("browseId"),
                    "results": [
                        {
                            "videoId": song.get("videoId"),
                            "title": song.get("title"),
                            "thumbnails": song.get("thumbnails", []),
                            "artists": [a.get("name") for a in song.get("artists", [])],
                        }
                        for song in result.get("songs", {}).get("results", [])
                    ],
                },
                "albums": {
                    "browseId": result.get("albums", {}).get("browseId"),
                    "results": [
                        {
                            "browseId": album.get("browseId"),
                            "title": album.get("title"),
                            "year": album.get("year"),
                            "thumbnails": album.get("thumbnails", []),
                        }
                        for album in result.get("albums", {}).get("results", [])
                    ],
                },
                "singles": {
                    "browseId": result.get("singles", {}).get("browseId"),
                    "results": [
                        {
                            "browseId": single.get("browseId"),
                            "title": single.get("title"),
                            "year": single.get("year"),
                            "thumbnails": single.get("thumbnails", []),
                        }
                        for single in result.get("singles", {}).get("results", [])
                    ],
                },
            }
            
            return json.dumps(simplified, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    def get_artist_albums(
        self,
        channelId: str,
        params: str,
    ) -> str:
        """Get the full list of an artist's albums or singles.

        Use get_artist first to get the params from albums.browseId or singles.browseId.

        Args:
            channelId: The artist's channel ID.
            params: Params obtained from get_artist()['albums']['params'] or ['singles']['params'].

        Returns:
            JSON string containing list of all albums/singles.
        """
        log_debug(f"Fetching artist albums: {channelId}")
        
        try:
            result = self.ytmusic.get_artist_albums(channelId=channelId, params=params)
            
            simplified_albums = [
                {
                    "browseId": album.get("browseId"),
                    "title": album.get("title"),
                    "year": album.get("year"),
                    "thumbnails": album.get("thumbnails", []),
                }
                for album in result
            ]
            
            return json.dumps(simplified_albums, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    def get_playlist(
        self,
        playlistId: str,
        limit: Optional[int] = 100,
    ) -> str:
        """Get all tracks and information from a playlist.

        Args:
            playlistId: The playlist's ID. Can be obtained from search or library.
            limit: Number of tracks to return. None retrieves all. Default: 100.

        Returns:
            JSON string containing playlist info and list of tracks.
        """
        log_debug(f"Fetching playlist: {playlistId}")
        
        try:
            result = self.ytmusic.get_playlist(playlistId=playlistId, limit=limit)
            
            simplified = {
                "id": result.get("id"),
                "privacy": result.get("privacy"),
                "title": result.get("title"),
                "thumbnails": result.get("thumbnails", []),
                "description": result.get("description"),
                "author": result.get("author"),
                "year": result.get("year"),
                "duration": result.get("duration"),
                "trackCount": result.get("trackCount"),
                "tracks": [
                    {
                        "videoId": track.get("videoId"),
                        "title": track.get("title"),
                        "artists": [a.get("name") for a in track.get("artists", [])],
                        "album": track.get("album", {}).get("name") if track.get("album") else None,
                        "duration": track.get("duration"),
                        "thumbnails": track.get("thumbnails", []),
                        "isAvailable": track.get("isAvailable"),
                        "isExplicit": track.get("isExplicit"),
                        "setVideoId": track.get("setVideoId"),
                    }
                    for track in result.get("tracks", [])
                ],
            }
            
            return json.dumps(simplified, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    def get_watch_playlist(
        self,
        videoId: Optional[str] = None,
        playlistId: Optional[str] = None,
        limit: int = 25,
    ) -> str:
        """Get the watch/radio playlist for a song, video, or playlist.

        This returns a mix of related songs similar to what plays when you start a radio.

        Args:
            videoId: Video ID to get radio playlist for.
            playlistId: Playlist ID to get radio playlist for (starts with 'RDAMPL' for albums).
            limit: Number of tracks to return (default 25).

        Returns:
            JSON string containing radio playlist tracks.
        """
        log_debug(f"Fetching watch playlist: videoId={videoId}, playlistId={playlistId}")
        
        try:
            result = self.ytmusic.get_watch_playlist(
                videoId=videoId,
                playlistId=playlistId,
                limit=limit,
            )
            
            simplified = {
                "tracks": [
                    {
                        "videoId": track.get("videoId"),
                        "title": track.get("title"),
                        "artists": [a.get("name") for a in track.get("artists", [])] if track.get("artists") else [],
                        "album": track.get("album", {}).get("name") if track.get("album") else None,
                        "duration": track.get("duration"),
                        "thumbnails": track.get("thumbnails", []),
                    }
                    for track in result.get("tracks", [])
                ],
                "playlistId": result.get("playlistId"),
            }
            
            return json.dumps(simplified, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)

    def get_lyrics(
        self,
        browseId: str,
    ) -> str:
        """Get lyrics for a song.

        Use get_song() first to get the browseId from the lyrics section.

        Args:
            browseId: The browse ID for the lyrics, typically starts with 'MPLYt_'.

        Returns:
            JSON string containing lyrics text and source.
        """
        log_debug(f"Fetching lyrics: {browseId}")
        
        try:
            result = self.ytmusic.get_lyrics(browseId=browseId)
            
            simplified = {
                "lyrics": result.get("lyrics"),
                "source": result.get("source"),
            }
            
            return json.dumps(simplified, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)}, indent=2)
