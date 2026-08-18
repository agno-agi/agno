import json
from typing import Any, Callable, Dict, List, Optional
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


class YouTubeTools(Toolkit):
    """Toolkit for fetching YouTube video metadata, transcripts, and timestamps.

    Args:
        get_transcript: Enable get_transcript tool. Defaults to True.
        get_metadata: Enable get_metadata tool. Defaults to True.
        get_timestamps: Enable get_timestamps tool. Defaults to True.
        all: Enable all tools. Defaults to False.
        languages: Preferred languages for transcripts.
        proxies: Proxy configuration passed to the transcript API.
        timeout: Request timeout in seconds. Defaults to 30.
    """

    # Agno 2.x kwarg names accepted for backwards compatibility
    _legacy_param_aliases = {
        "enable_get_video_captions": "get_transcript",
        "enable_get_video_data": "get_metadata",
        "enable_get_video_timestamps": "get_timestamps",
    }

    def __init__(
        self,
        get_transcript: bool = True,
        get_metadata: bool = True,
        get_timestamps: bool = True,
        all: bool = False,
        languages: Optional[List[str]] = None,
        proxies: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        **kwargs,
    ):
        self.languages: Optional[List[str]] = languages
        self.proxies: Optional[Dict[str, Any]] = proxies

        tools: List[Callable] = []
        if all or get_transcript:
            tools.append(self.get_transcript)
        if all or get_metadata:
            tools.append(self.get_metadata)
        if all or get_timestamps:
            tools.append(self.get_timestamps)

        super().__init__(name="youtube_tools", tools=tools, timeout=timeout, **kwargs)

    def get_youtube_video_id(self, url: str) -> Optional[str]:
        """Function to get the video ID from a YouTube URL.

        Args:
            url: The URL of the YouTube video.

        Returns:
            str: The video ID of the YouTube video.
        """
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname

        if hostname == "youtu.be":
            return parsed_url.path[1:]
        if hostname in ("www.youtube.com", "youtube.com"):
            if parsed_url.path == "/watch":
                query_params = parse_qs(parsed_url.query)
                return query_params.get("v", [None])[0]
            if parsed_url.path.startswith("/embed/"):
                return parsed_url.path.split("/")[2]
            if parsed_url.path.startswith("/v/"):
                return parsed_url.path.split("/")[2]
        return None

    def get_metadata(self, url: str) -> str:
        """Get video metadata from a YouTube URL.

        Args:
            url: The URL of the YouTube video.

        Returns:
            JSON with title, author, thumbnail, dimensions.
        """
        if not url:
            return json.dumps({"error": "No URL provided"})

        log_debug(f"Getting video data for youtube video: {url}")

        try:
            video_id = self.get_youtube_video_id(url)
        except Exception:
            return json.dumps({"error": "Error getting video ID from URL, please provide a valid YouTube url"})

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
            return json.dumps({"error": f"Error getting video data: {e}"})

    def get_transcript(self, url: str) -> str:
        """Get transcript from a YouTube video.

        Args:
            url: The URL of the YouTube video.

        Returns:
            JSON with full transcript text.
        """
        if not url:
            return json.dumps({"error": "No URL provided"})

        log_debug(f"Getting captions for youtube video: {url}")

        try:
            video_id = self.get_youtube_video_id(url)
        except Exception:
            return json.dumps({"error": "Error getting video ID from URL, please provide a valid YouTube url"})

        try:
            captions = None
            kwargs: Dict = {}
            if self.languages:
                kwargs["languages"] = self.languages or ["en"]
            if self.proxies:
                kwargs["proxies"] = self.proxies
            if video_id is not None:
                captions = YouTubeTranscriptApi().fetch(video_id, **kwargs)
            else:
                return json.dumps({"error": "No video ID found"})
            if captions:
                return json.dumps({"captions": " ".join(line.text for line in captions)})
            return json.dumps({"error": "No captions found for video"})
        except Exception as e:
            return json.dumps({"error": f"Error getting captions for video: {e}"})

    def get_timestamps(self, url: str) -> str:
        """Get transcript with timestamps from a YouTube video.

        Args:
            url: The URL of the YouTube video.

        Returns:
            JSON with timestamped transcript segments.
        """
        if not url:
            return json.dumps({"error": "No URL provided"})

        log_debug(f"Getting timestamps for youtube video: {url}")

        try:
            video_id = self.get_youtube_video_id(url)
        except Exception:
            return json.dumps({"error": "Error getting video ID from URL, please provide a valid YouTube url"})

        if video_id is None:
            return json.dumps({"error": "No video ID found"})

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
                timestamps.append({"time": f"{minutes}:{seconds:02d}", "text": line.text})
            return json.dumps({"timestamps": timestamps})
        except Exception as e:
            return json.dumps({"error": f"Error generating timestamps: {e}"})
