import json
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from agno.tools import Toolkit
from agno.utils.log import log_debug

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    raise ImportError(
        "`youtube_transcript_api` not installed. Please install using `pip install youtube_transcript_api`"
    )

_YOUTUBE_CANONICAL_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }
)


def _is_youtube_host(hostname: str) -> bool:
    """Check if the hostname is a recognized YouTube domain (including localized ccTLDs)."""
    if not hostname:
        return False
    if hostname in _YOUTUBE_CANONICAL_HOSTS:
        return True
    labels = hostname.split(".")
    return "youtube" in labels and labels.index("youtube") < len(labels) - 1


class YouTubeTools(Toolkit):
    def __init__(
        self,
        enable_get_video_captions: bool = True,
        enable_get_video_data: bool = True,
        enable_get_video_timestamps: bool = True,
        all: bool = False,
        languages: Optional[List[str]] = None,
        proxies: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        **kwargs,
    ):
        self.languages: Optional[List[str]] = languages
        self.proxies: Optional[Dict[str, Any]] = proxies

        tools: List[Any] = []
        if all or enable_get_video_captions:
            tools.append(self.get_youtube_video_captions)
        if all or enable_get_video_data:
            tools.append(self.get_youtube_video_data)
        if all or enable_get_video_timestamps:
            tools.append(self.get_video_timestamps)

        super().__init__(name="youtube_tools", tools=tools, timeout=timeout, **kwargs)

    def get_youtube_video_id(self, url: str) -> Optional[str]:
        """Function to get the video ID from a YouTube URL.

        Supports standard watch URLs, short URLs (youtu.be), shorts, live streams,
        embeds, mobile URLs, YouTube Music, and privacy-enhanced (nocookie) domains.

        Args:
            url: The URL of the YouTube video.

        Returns:
            Optional[str]: The video ID of the YouTube video, or None if not found.
        """
        if not url or not isinstance(url, str):
            return None

        clean_url = url.strip()
        if not clean_url:
            return None

        if not clean_url.startswith(("http://", "https://")):
            clean_url = f"https://{clean_url}"

        try:
            parsed_url = urlparse(clean_url)
        except Exception:
            return None

        hostname = (parsed_url.hostname or "").lower()
        path = parsed_url.path or ""

        # Short URLs: youtu.be/<id>
        if hostname == "youtu.be" or hostname.endswith(".youtu.be"):
            parts = [p for p in path.split("/") if p]
            return parts[0] if parts else None

        if not _is_youtube_host(hostname):
            return None

        # Standard watch URL: /watch?v=<id>
        if path == "/watch" or path.startswith("/watch/"):
            query_params = parse_qs(parsed_url.query)
            video_ids = query_params.get("v")
            if video_ids and video_ids[0]:
                return video_ids[0]

        # Path-based IDs: /embed/<id>, /v/<id>, /shorts/<id>, /live/<id>
        for prefix in ("/embed/", "/v/", "/shorts/", "/live/"):
            if path.startswith(prefix):
                remainder = path[len(prefix) :]
                parts = [p for p in remainder.split("/") if p]
                return parts[0] if parts else None

        return None

    def get_youtube_video_data(self, url: str) -> str:
        """Function to get video data from a YouTube URL.
        Data returned includes {title, author_name, author_url, type, height, width, version, provider_name, provider_url, thumbnail_url}

        Args:
            url: The URL of the YouTube video.

        Returns:
            str: JSON data of the YouTube video.
        """
        if not url:
            return "No URL provided"

        log_debug(f"Getting video data for youtube video: {url}")

        try:
            video_id = self.get_youtube_video_id(url)
        except Exception:
            return "Error getting video ID from URL, please provide a valid YouTube url"

        if video_id is None:
            return "No video ID found"

        try:
            params = {"format": "json", "url": f"https://www.youtube.com/watch?v={video_id}"}
            url = "https://www.youtube.com/oembed"
            query_string = urlencode(params)
            url = url + "?" + query_string

            with urlopen(url, timeout=self.timeout) as response:
                response_text = response.read()
                video_data = json.loads(response_text.decode())
                clean_data = {
                    "title": video_data.get("title"),
                    "author_name": video_data.get("author_name"),
                    "author_url": video_data.get("author_url"),
                    "type": video_data.get("type"),
                    "height": video_data.get("height"),
                    "width": video_data.get("width"),
                    "version": video_data.get("version"),
                    "provider_name": video_data.get("provider_name"),
                    "provider_url": video_data.get("provider_url"),
                    "thumbnail_url": video_data.get("thumbnail_url"),
                }
                return json.dumps(clean_data, indent=4)
        except Exception as e:
            return f"Error getting video data: {e}"

    def get_youtube_video_captions(self, url: str) -> str:
        """Use this function to get captions from a YouTube video.

        Args:
            url: The URL of the YouTube video.

        Returns:
            str: The captions of the YouTube video.
        """
        if not url:
            return "No URL provided"

        log_debug(f"Getting captions for youtube video: {url}")

        try:
            video_id = self.get_youtube_video_id(url)
        except Exception:
            return "Error getting video ID from URL, please provide a valid YouTube url"

        if video_id is None:
            return "No video ID found"

        try:
            captions = None
            kwargs: Dict = {}
            if self.languages:
                kwargs["languages"] = self.languages or ["en"]
            if self.proxies:
                kwargs["proxies"] = self.proxies
            captions = YouTubeTranscriptApi().fetch(video_id, **kwargs)
            if captions:
                return " ".join(line.text for line in captions)
            return "No captions found for video"
        except Exception as e:
            # log_info(f"Error getting captions for video {video_id}: {e}")
            return f"Error getting captions for video: {e}"

    def get_video_timestamps(self, url: str) -> str:
        """Generate timestamps for a YouTube video based on captions.

        Args:
            url: The URL of the YouTube video.

        Returns:
            str: Timestamps and summaries for the video.
        """
        if not url:
            return "No URL provided"

        log_debug(f"Getting timestamps for youtube video: {url}")

        try:
            video_id = self.get_youtube_video_id(url)
        except Exception:
            return "Error getting video ID from URL, please provide a valid YouTube url"

        if video_id is None:
            return "No video ID found"

        try:
            kwargs: Dict = {}
            if self.languages:
                kwargs["languages"] = self.languages or ["en"]
            if self.proxies:
                kwargs["proxies"] = self.proxies

            captions = YouTubeTranscriptApi().fetch(video_id, **kwargs)
            timestamps = []
            for line in captions:
                start = int(line.start)
                minutes, seconds = divmod(start, 60)
                timestamps.append(f"{minutes}:{seconds:02d} - {line.text}")
            return "\n".join(timestamps)
        except Exception as e:
            return f"Error generating timestamps: {e}"
