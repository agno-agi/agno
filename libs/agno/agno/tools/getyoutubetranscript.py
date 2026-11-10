import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

SearchType = Literal["video", "channel"]

_PreparedRequest = Tuple[str, Dict[str, Any]]


class GetYouTubeTranscriptTools(Toolkit):
    """Tools for fetching YouTube transcripts, searching YouTube, and listing a channel's videos
    through the GetYouTubeTranscript REST API.

    Get an API key at https://getyoutubetranscript.com and see
    https://getyoutubetranscript.com/openapi.json for the API reference.

    Args:
        api_key (Optional[str]): API key. If not provided, uses the GETYOUTUBETRANSCRIPT_API_KEY env var.
        base_url (str): API base URL. Default is https://getyoutubetranscript.com/api/v1.
        timeout (float): Per-request timeout in seconds. Default is 60.
        enable_get_transcript (bool): Enable fetching a video transcript. Default is True.
        enable_search (bool): Enable searching YouTube for videos or channels. Default is False.
        enable_list_channel_videos (bool): Enable listing the videos of a channel. Default is False.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://getyoutubetranscript.com/api/v1",
        timeout: float = 60.0,
        enable_get_transcript: bool = True,
        enable_search: bool = False,
        enable_list_channel_videos: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("GETYOUTUBETRANSCRIPT_API_KEY")
        if not self.api_key:
            log_error(
                "GETYOUTUBETRANSCRIPT_API_KEY not set. Please set the GETYOUTUBETRANSCRIPT_API_KEY environment variable."
            )

        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout)

        tools: List[Any] = []
        async_tools: List[tuple] = []
        if all or enable_get_transcript:
            tools.append(self.get_youtube_transcript)
            async_tools.append((self.aget_youtube_transcript, "get_youtube_transcript"))
        if all or enable_search:
            tools.append(self.search_youtube)
            async_tools.append((self.asearch_youtube, "search_youtube"))
        if all or enable_list_channel_videos:
            tools.append(self.list_channel_videos)
            async_tools.append((self.alist_channel_videos, "list_channel_videos"))

        name = kwargs.pop("name", "getyoutubetranscript_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools, **kwargs)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    def _headers(self) -> Optional[Dict[str, str]]:
        if not self.api_key:
            return None
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    @staticmethod
    def _error(message: str, status_code: Optional[int] = None, code: Optional[str] = None) -> str:
        error: Dict[str, Any] = {"error": message}
        if status_code is not None:
            error["status_code"] = status_code
        if code is not None:
            error["code"] = code
        return json.dumps(error)

    @classmethod
    def _handle_response(cls, response: httpx.Response) -> str:
        """Turn an API response into a JSON string: the `data` payload on success, an error object otherwise."""
        try:
            body = response.json()
        except ValueError:
            return cls._error(f"Invalid JSON response: {response.text[:200]}", status_code=response.status_code)

        if response.status_code >= 400 or not isinstance(body, dict) or not body.get("success"):
            message = body.get("message") if isinstance(body, dict) else None
            code = body.get("code") if isinstance(body, dict) else None
            return cls._error(message or "GetYouTubeTranscript API request failed", response.status_code, code)

        return json.dumps(body.get("data"), indent=2)

    def _request(self, path: str, params: Dict[str, Any]) -> str:
        headers = self._headers()
        if headers is None:
            return self._error("No API key provided. Set the GETYOUTUBETRANSCRIPT_API_KEY environment variable.")
        log_debug(f"GetYouTubeTranscript request: {path}")
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/{path}", headers=headers, params=params)
            return self._handle_response(response)
        except httpx.RequestError as e:
            log_error(f"GetYouTubeTranscript request error: {e}")
            return self._error(f"Request failed: {e}")

    async def _arequest(self, path: str, params: Dict[str, Any]) -> str:
        headers = self._headers()
        if headers is None:
            return self._error("No API key provided. Set the GETYOUTUBETRANSCRIPT_API_KEY environment variable.")
        log_debug(f"GetYouTubeTranscript request: {path}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/{path}", headers=headers, params=params)
            return self._handle_response(response)
        except httpx.RequestError as e:
            log_error(f"GetYouTubeTranscript request error: {e}")
            return self._error(f"Request failed: {e}")

    # ------------------------------------------------------------------
    # Request builders (shared by the sync and async tools)
    # ------------------------------------------------------------------
    @classmethod
    def _prepare_transcript(cls, video: str, language: Optional[str], timestamps: bool) -> Union[_PreparedRequest, str]:
        if not video or not video.strip():
            return cls._error("Please provide a YouTube video URL or video ID.")
        params: Dict[str, Any] = {"v": video.strip()}
        if language:
            params["language"] = language
        if timestamps:
            params["timestamps"] = "true"
        return "transcript", params

    @classmethod
    def _prepare_search(
        cls, query: Optional[str], type: str, page_token: Optional[str]
    ) -> Union[_PreparedRequest, str]:
        if type not in ("video", "channel"):
            return cls._error("type must be 'video' or 'channel'.")
        if page_token:
            return "search", {"page_token": page_token}
        if not query or len(query.strip()) < 2:
            return cls._error("Please provide a search query of at least 2 characters, or a page_token.")
        return "search", {"q": query.strip(), "type": type}

    @classmethod
    def _prepare_channel_videos(
        cls, channel: Optional[str], continuation: Optional[str]
    ) -> Union[_PreparedRequest, str]:
        if continuation:
            return "channel/videos", {"continuation": continuation}
        if not channel or not channel.strip():
            return cls._error("Please provide a channel (@handle, URL or UC... id) or a continuation token.")
        return "channel/videos", {"channel": channel.strip()}

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------
    def get_youtube_transcript(self, video: str, language: Optional[str] = None, timestamps: bool = False) -> str:
        """Get the full transcript of a YouTube video, plus its title and channel.

        Args:
            video (str): A YouTube video URL (youtube.com or youtu.be) or an 11-character video ID.
            language (Optional[str]): Caption language code such as 'en' or 'es'. If omitted, the API default (English) is used.
            timestamps (bool): Set True to also get 'segments', a list of {start, duration, text} in seconds, so
                you can cite a moment in the video. Default False returns only the plain transcript text. Segments
                make the response much larger, so only request them when timing matters.

        Returns:
            str: JSON with video_id, title, author_name, language_code, word_count and transcript (and segments when
                requested), or a JSON object with an 'error' key.
        """
        prepared = self._prepare_transcript(video, language, timestamps)
        if isinstance(prepared, str):
            return prepared
        return self._request(*prepared)

    async def aget_youtube_transcript(
        self, video: str, language: Optional[str] = None, timestamps: bool = False
    ) -> str:
        """Get the full transcript of a YouTube video, plus its title and channel.

        Args:
            video (str): A YouTube video URL (youtube.com or youtu.be) or an 11-character video ID.
            language (Optional[str]): Caption language code such as 'en' or 'es'. If omitted, the API default (English) is used.
            timestamps (bool): Set True to also get 'segments', a list of {start, duration, text} in seconds, so
                you can cite a moment in the video. Default False returns only the plain transcript text. Segments
                make the response much larger, so only request them when timing matters.

        Returns:
            str: JSON with video_id, title, author_name, language_code, word_count and transcript (and segments when
                requested), or a JSON object with an 'error' key.
        """
        prepared = self._prepare_transcript(video, language, timestamps)
        if isinstance(prepared, str):
            return prepared
        return await self._arequest(*prepared)

    def search_youtube(
        self, query: Optional[str] = None, type: SearchType = "video", page_token: Optional[str] = None
    ) -> str:
        """Search YouTube for videos or channels.

        Args:
            query (Optional[str]): The search text, at least 2 characters. Required unless page_token is given.
            type (str): 'video' (default) to find videos, or 'channel' to find channels.
            page_token (Optional[str]): The 'continuation_token' from a previous search response, to fetch the next
                page of the same search. Do not construct it yourself. When set, query is ignored.

        Returns:
            str: JSON with 'video_results' (type 'video') or 'channel_results' (type 'channel') and a
                'continuation_token' for the next page, or a JSON object with an 'error' key.
        """
        prepared = self._prepare_search(query, type, page_token)
        if isinstance(prepared, str):
            return prepared
        return self._request(*prepared)

    async def asearch_youtube(
        self, query: Optional[str] = None, type: SearchType = "video", page_token: Optional[str] = None
    ) -> str:
        """Search YouTube for videos or channels.

        Args:
            query (Optional[str]): The search text, at least 2 characters. Required unless page_token is given.
            type (str): 'video' (default) to find videos, or 'channel' to find channels.
            page_token (Optional[str]): The 'continuation_token' from a previous search response, to fetch the next
                page of the same search. Do not construct it yourself. When set, query is ignored.

        Returns:
            str: JSON with 'video_results' (type 'video') or 'channel_results' (type 'channel') and a
                'continuation_token' for the next page, or a JSON object with an 'error' key.
        """
        prepared = self._prepare_search(query, type, page_token)
        if isinstance(prepared, str):
            return prepared
        return await self._arequest(*prepared)

    def list_channel_videos(self, channel: Optional[str] = None, continuation: Optional[str] = None) -> str:
        """List the videos a YouTube channel has uploaded, newest first, one page at a time.

        Args:
            channel (Optional[str]): The channel as an @handle (for example '@mkbhd'), a channel URL, or a 'UC...'
                channel ID. Required unless continuation is given.
            continuation (Optional[str]): The 'continuation_token' from a previous response, to fetch the next page.
                Do not construct it yourself. When set, channel is ignored.

        Returns:
            str: JSON with 'videos', 'has_more' and a 'continuation_token' to pass back for the next page, or a JSON
                object with an 'error' key.
        """
        prepared = self._prepare_channel_videos(channel, continuation)
        if isinstance(prepared, str):
            return prepared
        return self._request(*prepared)

    async def alist_channel_videos(self, channel: Optional[str] = None, continuation: Optional[str] = None) -> str:
        """List the videos a YouTube channel has uploaded, newest first, one page at a time.

        Args:
            channel (Optional[str]): The channel as an @handle (for example '@mkbhd'), a channel URL, or a 'UC...'
                channel ID. Required unless continuation is given.
            continuation (Optional[str]): The 'continuation_token' from a previous response, to fetch the next page.
                Do not construct it yourself. When set, channel is ignored.

        Returns:
            str: JSON with 'videos', 'has_more' and a 'continuation_token' to pass back for the next page, or a JSON
                object with an 'error' key.
        """
        prepared = self._prepare_channel_videos(channel, continuation)
        if isinstance(prepared, str):
            return prepared
        return await self._arequest(*prepared)
