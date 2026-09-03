import asyncio
import time
from os import getenv
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx

from agno.media import Video
from agno.tools import Toolkit
from agno.tools.function import ToolResult
from agno.utils.log import log_error, log_info

MINIMAX_VIDEO_URLS = {
    "global_en": "https://api.minimax.io/v2/video_generation",
    "cn_zh": "https://api.minimaxi.com/v2/video_generation",
}

# Minimum budget required to start another poll request. Polling stops instead of
# issuing a request that cannot complete before max_wait_time elapses.
MIN_POLL_REQUEST_SECONDS = 1.0


class MiniMaxTools(Toolkit):
    """Tools for generating videos with the MiniMax API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        region: str = "global_en",
        model: str = "MiniMax-H3",
        poll_interval: float = 5,
        max_wait_time: float = 600,
        timeout: int = 30,
        enable_generate_video: bool = True,
        all: bool = False,
        **kwargs,
    ):
        if region not in MINIMAX_VIDEO_URLS:
            raise ValueError(f"Invalid region: {region}. Must be one of: {list(MINIMAX_VIDEO_URLS)}")

        self.api_key = api_key or getenv("MINIMAX_API_KEY")
        self.base_url = (base_url or MINIMAX_VIDEO_URLS[region]).rstrip("/")
        self.model = model
        self.poll_interval = poll_interval
        self.max_wait_time = max_wait_time
        self.request_timeout = timeout

        if not self.api_key:
            log_error("MINIMAX_API_KEY not set. Please set the MINIMAX_API_KEY environment variable.")

        tools: List[Any] = []
        async_tools = []
        if all or enable_generate_video:
            tools.append(self.generate_video)
            async_tools.append((self.agenerate_video, "generate_video"))

        super().__init__(name="minimax_tools", tools=tools, async_tools=async_tools, timeout=timeout, **kwargs)

    @property
    def _query_url(self) -> str:
        return self.base_url.replace("/v2/video_generation", "/v2/query/video_generation")

    @property
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def generate_video(
        self,
        prompt: str,
        resolution: str = "2K",
        duration: int = 5,
        ratio: str = "16:9",
    ) -> ToolResult:
        """Generate a video from a text prompt.

        Args:
            prompt: Text description of the video to generate.
            resolution: Output resolution. MiniMax H3 currently supports 2K.
            duration: Video duration in seconds, from 4 through 15.
            ratio: Output aspect ratio, such as 16:9 or 9:16.
        """
        if not self.api_key:
            return ToolResult(content="Please set the MINIMAX_API_KEY")
        if not prompt:
            return ToolResult(content="Please provide a prompt")

        payload = {
            "model": self.model,
            "content": [{"type": "text", "text": prompt}],
            "resolution": resolution,
            "duration": duration,
            "ratio": ratio,
        }

        try:
            response = httpx.post(
                self.base_url,
                headers=self._headers,
                json=payload,
                timeout=self.request_timeout,
            )
            response.raise_for_status()
            task_id = response.json().get("task_id")
            if not task_id:
                return ToolResult(content="Failed to generate video: No task ID returned")

            deadline = time.monotonic() + self.max_wait_time
            while True:
                remaining = deadline - time.monotonic()
                if remaining < MIN_POLL_REQUEST_SECONDS:
                    break

                task_response = httpx.get(
                    f"{self._query_url}/{task_id}",
                    headers=self._headers,
                    timeout=min(self.request_timeout, remaining),
                )
                task_response.raise_for_status()
                task = task_response.json().get("task", {})
                status = task.get("status")

                if status == "succeeded":
                    video_url = task.get("content", {}).get("url")
                    if not video_url:
                        return ToolResult(content="Failed to generate video: No video URL returned")
                    video = Video(
                        id=str(uuid4()),
                        url=video_url,
                        original_prompt=prompt,
                        mime_type="video/mp4",
                    )
                    return ToolResult(content="Video generated successfully", videos=[video])
                if status in {"failed", "cancelled"}:
                    error = task.get("error", {})
                    message = error.get("message") or status
                    return ToolResult(content=f"Failed to generate video: {message}")

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

                log_info(f"Video generation in progress: {status or 'pending'}")
                time.sleep(min(self.poll_interval, remaining))

            return ToolResult(content=f"Video generation timed out after {self.max_wait_time} seconds")
        except httpx.HTTPError as e:
            log_error(f"MiniMax video generation request failed: {e}")
            return ToolResult(content=f"Error generating video: {e}")
        except Exception as e:
            log_error(f"MiniMax video generation failed: {e}")
            return ToolResult(content=f"Error generating video: {e}")

    async def agenerate_video(
        self,
        prompt: str,
        resolution: str = "2K",
        duration: int = 5,
        ratio: str = "16:9",
    ) -> ToolResult:
        """Generate a video from a text prompt asynchronously."""
        if not self.api_key:
            return ToolResult(content="Please set the MINIMAX_API_KEY")
        if not prompt:
            return ToolResult(content="Please provide a prompt")

        payload = {
            "model": self.model,
            "content": [{"type": "text", "text": prompt}],
            "resolution": resolution,
            "duration": duration,
            "ratio": ratio,
        }

        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.post(self.base_url, headers=self._headers, json=payload)
                response.raise_for_status()
                task_id = response.json().get("task_id")
                if not task_id:
                    return ToolResult(content="Failed to generate video: No task ID returned")

                deadline = time.monotonic() + self.max_wait_time
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining < MIN_POLL_REQUEST_SECONDS:
                        break

                    task_response = await client.get(
                        f"{self._query_url}/{task_id}",
                        headers=self._headers,
                        timeout=min(self.request_timeout, remaining),
                    )
                    task_response.raise_for_status()
                    task = task_response.json().get("task", {})
                    status = task.get("status")

                    if status == "succeeded":
                        video_url = task.get("content", {}).get("url")
                        if not video_url:
                            return ToolResult(content="Failed to generate video: No video URL returned")
                        video = Video(
                            id=str(uuid4()),
                            url=video_url,
                            original_prompt=prompt,
                            mime_type="video/mp4",
                        )
                        return ToolResult(content="Video generated successfully", videos=[video])
                    if status in {"failed", "cancelled"}:
                        error = task.get("error", {})
                        message = error.get("message") or status
                        return ToolResult(content=f"Failed to generate video: {message}")

                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break

                    log_info(f"Video generation in progress: {status or 'pending'}")
                    await asyncio.sleep(min(self.poll_interval, remaining))

            return ToolResult(content=f"Video generation timed out after {self.max_wait_time} seconds")
        except httpx.HTTPError as e:
            log_error(f"MiniMax video generation request failed: {e}")
            return ToolResult(content=f"Error generating video: {e}")
        except Exception as e:
            log_error(f"MiniMax video generation failed: {e}")
            return ToolResult(content=f"Error generating video: {e}")
