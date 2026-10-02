"""
Upload-Post toolkit for publishing videos, photos and text posts to social platforms.

One call publishes to any mix of TikTok, Instagram, YouTube, LinkedIn, Facebook, X,
Threads, Pinterest and Bluesky through the Upload-Post API (https://upload-post.com,
docs at https://docs.upload-post.com). Accounts are connected once in the Upload-Post
dashboard under a profile; the toolkit only needs an API key.
"""

import asyncio
import json
import time
import uuid
from contextlib import ExitStack
from os import getenv
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

# Rejections the API returns before it accepts an upload. Nothing was published, so the
# caller can fix the input and try again. Every other outcome (5xx, a dropped connection,
# a timeout, an empty or non-JSON 2xx) is ambiguous: the upload may already be in flight.
DEFINITIVE_REJECTIONS = (400, 401, 403, 422)
FINAL_STATUSES = {"completed", "failed"}
PUBLISH_TOOLS = ("upload_video", "upload_photos", "upload_text")

UNKNOWN_OUTCOME_MESSAGE = (
    "The upload outcome is unknown: the request may have been received. Do NOT publish again. "
    "Check it with get_upload_status using this request_id."
)

# (form fields, files to open as (field name, path)).
_Request = Tuple[Dict[str, Any], List[Tuple[str, str]]]


class UploadPostTools(Toolkit):
    """
    UploadPostTools publishes content to social platforms through the Upload-Post API.

    Publishing tools require user confirmation by default (``requires_confirmation_tools``),
    since a published post is public and cannot always be undone. Pass
    ``requires_confirmation_tools=[]`` to opt out.

    Each upload carries a client-generated request_id that is also sent as the
    Idempotency-Key header, and uploads are never re-sent after an ambiguous failure:
    the toolkit polls the same request_id instead, so a dropped connection cannot
    produce a duplicate post.

    Args:
        api_key (Optional[str]): Upload-Post API key. Defaults to the UPLOAD_POST_API_KEY env var.
        user (Optional[str]): Upload-Post profile to publish from. Defaults to the UPLOAD_POST_USER env var.
        base_url (str): API base URL.
        timeout (float): Timeout in seconds for each HTTP request. Default is 300 (uploads send the file).
        wait_for_result (bool): Poll until every platform finishes. Default is True.
        max_wait (int): Maximum seconds to poll for results. Default is 300.
        poll_interval (float): Seconds between status polls. Default is 10.
        enable_upload_video (bool): Enable the upload_video tool. Default is True.
        enable_upload_photos (bool): Enable the upload_photos tool. Default is True.
        enable_upload_text (bool): Enable the upload_text tool. Default is True.
        enable_get_upload_status (bool): Enable the get_upload_status tool. Default is True.
        enable_list_profiles (bool): Enable the list_profiles tool. Default is True.
        all (bool): Enable every tool regardless of the individual flags.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        user: Optional[str] = None,
        base_url: str = "https://api.upload-post.com",
        timeout: float = 300.0,
        wait_for_result: bool = True,
        max_wait: int = 300,
        poll_interval: float = 10.0,
        enable_upload_video: bool = True,
        enable_upload_photos: bool = True,
        enable_upload_text: bool = True,
        enable_get_upload_status: bool = True,
        enable_list_profiles: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("UPLOAD_POST_API_KEY")
        if not self.api_key:
            log_warning("No Upload-Post API key provided. Set the UPLOAD_POST_API_KEY environment variable.")
        self.user = user or getenv("UPLOAD_POST_USER")
        self.base_url = base_url.rstrip("/")
        self.request_timeout = httpx.Timeout(timeout)
        self.wait_for_result = wait_for_result
        self.max_wait = max_wait
        self.poll_interval = poll_interval

        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Any] = []
        async_tools: List[tuple] = []
        if all or enable_upload_video:
            tools.append(self.upload_video)
            async_tools.append((self.aupload_video, "upload_video"))
        if all or enable_upload_photos:
            tools.append(self.upload_photos)
            async_tools.append((self.aupload_photos, "upload_photos"))
        if all or enable_upload_text:
            tools.append(self.upload_text)
            async_tools.append((self.aupload_text, "upload_text"))
        if all or enable_get_upload_status:
            tools.append(self.get_upload_status)
            async_tools.append((self.aget_upload_status, "get_upload_status"))
        if all or enable_list_profiles:
            tools.append(self.list_profiles)
            async_tools.append((self.alist_profiles, "list_profiles"))

        # Publishing is public and hard to undo, so it pauses for a human by default;
        # a consumer may replace this list (including with []).
        registered = {t.__name__ for t in tools}
        kwargs.setdefault("requires_confirmation_tools", [n for n in PUBLISH_TOOLS if n in registered])

        name = kwargs.pop("name", "upload_post_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools, **kwargs)

    # ------------------------------------------------------------------
    # Request building (shared by the sync and async variants)
    # ------------------------------------------------------------------

    def _headers(self, idempotency_key: Optional[str] = None) -> Dict[str, str]:
        headers = {"Authorization": f"Apikey {self.api_key}", "User-Agent": "agno"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _config_error(self, user: Optional[str]) -> Optional[str]:
        if not self.api_key:
            return "No Upload-Post API key provided. Set the UPLOAD_POST_API_KEY environment variable."
        if not user:
            return "No Upload-Post profile provided. Pass `user` or set the UPLOAD_POST_USER environment variable."
        return None

    def _base_form(
        self,
        request_id: str,
        user: str,
        title: str,
        platforms: List[str],
        description: Optional[str],
        scheduled_date: Optional[str],
    ) -> Dict[str, Any]:
        # httpx expects repeated fields as a list value, not as repeated tuples.
        form: Dict[str, Any] = {
            "user": user,
            "title": title,
            "platform[]": [p.strip().lower() for p in platforms if p.strip()],
            "request_id": request_id,
            "async_upload": "true",
        }
        if description:
            form["description"] = description
        if scheduled_date:
            form["scheduled_date"] = scheduled_date
        return form

    def _video_request(
        self,
        request_id: str,
        user: str,
        video: str,
        title: str,
        platforms: List[str],
        description: Optional[str],
        scheduled_date: Optional[str],
        youtube_privacy: str,
        tiktok_privacy: Optional[str],
    ) -> _Request:
        form = self._base_form(request_id, user, title, platforms, description, scheduled_date)
        if "youtube" in form["platform[]"]:
            form["privacyStatus"] = youtube_privacy
        if tiktok_privacy and "tiktok" in form["platform[]"]:
            form["privacy_level"] = tiktok_privacy
        files: List[Tuple[str, str]] = []
        if video.startswith(("http://", "https://")):
            form["video"] = video
        else:
            files.append(("video", video))
        return form, files

    def _photos_request(
        self,
        request_id: str,
        user: str,
        photos: List[str],
        title: str,
        platforms: List[str],
        description: Optional[str],
        scheduled_date: Optional[str],
    ) -> _Request:
        form = self._base_form(request_id, user, title, platforms, description, scheduled_date)
        urls = [p for p in photos if p.startswith(("http://", "https://"))]
        if urls:
            form["photos[]"] = urls
        files = [("photos[]", p) for p in photos if not p.startswith(("http://", "https://"))]
        return form, files

    @staticmethod
    def _missing_files(files: List[Tuple[str, str]]) -> Optional[str]:
        for _, path in files:
            if not Path(path).is_file():
                return f"File not found: {path}"
        return None

    # ------------------------------------------------------------------
    # Response handling
    # ------------------------------------------------------------------

    @staticmethod
    def _json_or_none(response: httpx.Response) -> Optional[Dict[str, Any]]:
        try:
            data = response.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _rejection(response: httpx.Response, request_id: str) -> Dict[str, Any]:
        detail: Any = response.text[:300]
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            detail = body.get("message") or body.get("error") or body
        elif body is not None:
            detail = body
        return {
            "status": "rejected",
            "request_id": request_id,
            "http_status": response.status_code,
            "error": str(detail),
            "message": "The API rejected the upload before accepting it. Nothing was published.",
        }

    @staticmethod
    def _summarize(status: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Normalize per-platform results into a compact list for the agent."""
        raw = status.get("results") or []
        if isinstance(raw, dict):
            raw = [{"platform": p, **r} for p, r in raw.items()]
        results = []
        for r in raw:
            if r.get("skipped"):
                state = "skipped"
            elif r.get("status"):
                state = r["status"]
            else:
                state = "completed" if r.get("success") else "failed"
            post_url = r.get("post_url") or r.get("url")
            is_url = isinstance(post_url, str) and post_url.startswith("http")
            results.append(
                {
                    "platform": r.get("platform"),
                    "status": state,
                    "url": post_url if is_url else None,
                    "post_id": r.get("platform_post_id"),
                    # e.g. "Post uploaded as Private. No public URL available."
                    "note": post_url if post_url and not is_url else None,
                    "error": (r.get("error_message") or r.get("error")) if state not in ("completed",) else None,
                }
            )
        return results

    def _outcome(self, status: Dict[str, Any], request_id: str, timed_out: bool = False) -> str:
        results = self._summarize(status)
        counts: Dict[str, int] = {}
        for r in results:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        # "completed" means every platform finished, not that every platform succeeded;
        # the per-state counts make a partial failure obvious to the agent.
        result: Dict[str, Any] = {
            "status": status.get("status"),
            "request_id": request_id,
            "job_id": status.get("job_id"),
            "summary": counts,
            "results": results,
        }
        if timed_out:
            result["message"] = (
                "Still processing. The upload continues server-side; do NOT publish again. "
                "Check it later with get_upload_status."
            )
        return json.dumps(result, indent=2)

    @staticmethod
    def _unknown(request_id: str, reason: str) -> str:
        return json.dumps(
            {"status": "unknown", "request_id": request_id, "reason": reason, "message": UNKNOWN_OUTCOME_MESSAGE},
            indent=2,
        )

    # ------------------------------------------------------------------
    # Sync transport
    # ------------------------------------------------------------------

    def _fetch_status(self, request_id: Optional[str] = None, job_id: Optional[str] = None) -> Dict[str, Any]:
        params = {"request_id": request_id} if request_id else {"job_id": job_id}
        with httpx.Client(timeout=self.request_timeout) as client:
            response = client.get(f"{self.base_url}/api/uploadposts/status", headers=self._headers(), params=params)
        if response.status_code == 404:
            return {"status": "not_found"}
        response.raise_for_status()
        data = self._json_or_none(response)
        if data is None:
            raise ValueError("Non-JSON status response")
        return data

    def _poll(self, request_id: str, max_wait: float) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Poll until the upload is final. Returns (last status or None, timed_out)."""
        deadline = time.monotonic() + max_wait
        last: Optional[Dict[str, Any]] = None
        while True:
            try:
                last = self._fetch_status(request_id=request_id)
            except (httpx.HTTPError, ValueError) as e:
                log_warning(f"Upload-Post status check failed: {e}")
            if last and last.get("status") in FINAL_STATUSES:
                return last, False
            if time.monotonic() >= deadline:
                return last, True
            time.sleep(self.poll_interval)

    def _publish(self, endpoint: str, request: _Request, request_id: str) -> str:
        form, files = request
        missing = self._missing_files(files)
        if missing:
            return json.dumps({"status": "rejected", "error": missing})

        log_debug(f"Upload-Post {endpoint} request_id={request_id} platforms={form['platform[]']}")
        try:
            with ExitStack() as stack:
                opened = [(field, (Path(p).name, stack.enter_context(open(p, "rb")))) for field, p in files]
                with httpx.Client(timeout=self.request_timeout) as client:
                    response = client.post(
                        f"{self.base_url}{endpoint}",
                        headers=self._headers(idempotency_key=request_id),
                        data=form,
                        files=opened or None,
                    )
        except httpx.HTTPError as e:
            # The upload may have arrived. Never re-send: find out by polling the same id.
            log_warning(f"Upload-Post transport error, checking request {request_id}: {e}")
            return self._resolve_ambiguous(request_id, reason=f"transport error: {e}")

        if response.status_code in DEFINITIVE_REJECTIONS:
            log_error(f"Upload-Post rejected the upload: HTTP {response.status_code}")
            return json.dumps(self._rejection(response, request_id), indent=2)

        body = self._json_or_none(response)
        if not response.is_success or body is None:
            return self._resolve_ambiguous(request_id, reason=f"HTTP {response.status_code}, unreadable response")

        if form.get("scheduled_date"):
            return json.dumps(
                {
                    "status": "scheduled",
                    "request_id": request_id,
                    "job_id": body.get("job_id"),
                    "scheduled_date": body.get("scheduled_date") or form["scheduled_date"],
                },
                indent=2,
            )
        if not self.wait_for_result:
            return json.dumps({"status": "submitted", "request_id": request_id}, indent=2)

        status, timed_out = self._poll(request_id, self.max_wait)
        if status is None:
            return self._unknown(request_id, reason="accepted, but the status endpoint could not be reached")
        return self._outcome(status, request_id, timed_out=timed_out)

    def _resolve_ambiguous(self, request_id: str, reason: str) -> str:
        status, timed_out = self._poll(request_id, min(self.max_wait, 3 * self.poll_interval))
        if status is None or status.get("status") == "not_found":
            return self._unknown(request_id, reason=reason)
        return self._outcome(status, request_id, timed_out=timed_out)

    # ------------------------------------------------------------------
    # Async transport
    # ------------------------------------------------------------------

    async def _afetch_status(self, request_id: Optional[str] = None, job_id: Optional[str] = None) -> Dict[str, Any]:
        params = {"request_id": request_id} if request_id else {"job_id": job_id}
        async with httpx.AsyncClient(timeout=self.request_timeout) as client:
            response = await client.get(
                f"{self.base_url}/api/uploadposts/status", headers=self._headers(), params=params
            )
        if response.status_code == 404:
            return {"status": "not_found"}
        response.raise_for_status()
        data = self._json_or_none(response)
        if data is None:
            raise ValueError("Non-JSON status response")
        return data

    async def _apoll(self, request_id: str, max_wait: float) -> Tuple[Optional[Dict[str, Any]], bool]:
        deadline = time.monotonic() + max_wait
        last: Optional[Dict[str, Any]] = None
        while True:
            try:
                last = await self._afetch_status(request_id=request_id)
            except (httpx.HTTPError, ValueError) as e:
                log_warning(f"Upload-Post status check failed: {e}")
            if last and last.get("status") in FINAL_STATUSES:
                return last, False
            if time.monotonic() >= deadline:
                return last, True
            await asyncio.sleep(self.poll_interval)

    async def _apublish(self, endpoint: str, request: _Request, request_id: str) -> str:
        form, files = request
        missing = self._missing_files(files)
        if missing:
            return json.dumps({"status": "rejected", "error": missing})

        log_debug(f"Upload-Post {endpoint} request_id={request_id} platforms={form['platform[]']}")
        try:
            with ExitStack() as stack:
                opened = [(field, (Path(p).name, stack.enter_context(open(p, "rb")))) for field, p in files]
                async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                    response = await client.post(
                        f"{self.base_url}{endpoint}",
                        headers=self._headers(idempotency_key=request_id),
                        data=form,
                        files=opened or None,
                    )
        except httpx.HTTPError as e:
            log_warning(f"Upload-Post transport error, checking request {request_id}: {e}")
            return await self._aresolve_ambiguous(request_id, reason=f"transport error: {e}")

        if response.status_code in DEFINITIVE_REJECTIONS:
            log_error(f"Upload-Post rejected the upload: HTTP {response.status_code}")
            return json.dumps(self._rejection(response, request_id), indent=2)

        body = self._json_or_none(response)
        if not response.is_success or body is None:
            return await self._aresolve_ambiguous(
                request_id, reason=f"HTTP {response.status_code}, unreadable response"
            )

        if form.get("scheduled_date"):
            return json.dumps(
                {
                    "status": "scheduled",
                    "request_id": request_id,
                    "job_id": body.get("job_id"),
                    "scheduled_date": body.get("scheduled_date") or form["scheduled_date"],
                },
                indent=2,
            )
        if not self.wait_for_result:
            return json.dumps({"status": "submitted", "request_id": request_id}, indent=2)

        status, timed_out = await self._apoll(request_id, self.max_wait)
        if status is None:
            return self._unknown(request_id, reason="accepted, but the status endpoint could not be reached")
        return self._outcome(status, request_id, timed_out=timed_out)

    async def _aresolve_ambiguous(self, request_id: str, reason: str) -> str:
        status, timed_out = await self._apoll(request_id, min(self.max_wait, 3 * self.poll_interval))
        if status is None or status.get("status") == "not_found":
            return self._unknown(request_id, reason=reason)
        return self._outcome(status, request_id, timed_out=timed_out)

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def upload_video(
        self,
        video: str,
        title: str,
        platforms: List[str],
        description: Optional[str] = None,
        user: Optional[str] = None,
        scheduled_date: Optional[str] = None,
        youtube_privacy: str = "private",
        tiktok_privacy: Optional[str] = None,
    ) -> str:
        """
        Publish a video to one or more social platforms.

        Args:
            video (str): Local file path or public URL of the video.
            title (str): Caption/title used on every platform (YouTube allows 100 characters).
            platforms (List[str]): Any of tiktok, instagram, youtube, linkedin, facebook, x, threads, pinterest, bluesky.
            description (Optional[str]): Longer text for YouTube, LinkedIn, Facebook and Pinterest.
            user (Optional[str]): Upload-Post profile to publish from. Defaults to the toolkit setting.
            scheduled_date (Optional[str]): ISO-8601 time to publish later, e.g. 2026-10-01T09:00:00Z.
            youtube_privacy (str): private, unlisted or public. Default is private.
            tiktok_privacy (Optional[str]): PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, FOLLOWER_OF_CREATOR or SELF_ONLY.

        Returns:
            str: JSON with the overall status, the request_id and one result per platform.
        """
        user = user or self.user
        error = self._config_error(user)
        if error or user is None:
            return json.dumps({"status": "rejected", "error": error})
        request_id = uuid.uuid4().hex
        request = self._video_request(
            request_id, user, video, title, platforms, description, scheduled_date, youtube_privacy, tiktok_privacy
        )
        return self._publish("/api/upload", request, request_id)

    async def aupload_video(
        self,
        video: str,
        title: str,
        platforms: List[str],
        description: Optional[str] = None,
        user: Optional[str] = None,
        scheduled_date: Optional[str] = None,
        youtube_privacy: str = "private",
        tiktok_privacy: Optional[str] = None,
    ) -> str:
        """
        Publish a video to one or more social platforms.

        Args:
            video (str): Local file path or public URL of the video.
            title (str): Caption/title used on every platform (YouTube allows 100 characters).
            platforms (List[str]): Any of tiktok, instagram, youtube, linkedin, facebook, x, threads, pinterest, bluesky.
            description (Optional[str]): Longer text for YouTube, LinkedIn, Facebook and Pinterest.
            user (Optional[str]): Upload-Post profile to publish from. Defaults to the toolkit setting.
            scheduled_date (Optional[str]): ISO-8601 time to publish later, e.g. 2026-10-01T09:00:00Z.
            youtube_privacy (str): private, unlisted or public. Default is private.
            tiktok_privacy (Optional[str]): PUBLIC_TO_EVERYONE, MUTUAL_FOLLOW_FRIENDS, FOLLOWER_OF_CREATOR or SELF_ONLY.

        Returns:
            str: JSON with the overall status, the request_id and one result per platform.
        """
        user = user or self.user
        error = self._config_error(user)
        if error or user is None:
            return json.dumps({"status": "rejected", "error": error})
        request_id = uuid.uuid4().hex
        request = self._video_request(
            request_id, user, video, title, platforms, description, scheduled_date, youtube_privacy, tiktok_privacy
        )
        return await self._apublish("/api/upload", request, request_id)

    def upload_photos(
        self,
        photos: List[str],
        title: str,
        platforms: List[str],
        description: Optional[str] = None,
        user: Optional[str] = None,
        scheduled_date: Optional[str] = None,
    ) -> str:
        """
        Publish one or more photos (a carousel when there are several) to social platforms.

        Args:
            photos (List[str]): Local file paths or public URLs of the images.
            title (str): Caption used on every platform.
            platforms (List[str]): Any of instagram, tiktok, linkedin, facebook, x, threads, pinterest, bluesky.
            description (Optional[str]): Longer text where the platform supports it.
            user (Optional[str]): Upload-Post profile to publish from. Defaults to the toolkit setting.
            scheduled_date (Optional[str]): ISO-8601 time to publish later.

        Returns:
            str: JSON with the overall status, the request_id and one result per platform.
        """
        user = user or self.user
        error = self._config_error(user)
        if error or user is None:
            return json.dumps({"status": "rejected", "error": error})
        request_id = uuid.uuid4().hex
        request = self._photos_request(request_id, user, photos, title, platforms, description, scheduled_date)
        return self._publish("/api/upload_photos", request, request_id)

    async def aupload_photos(
        self,
        photos: List[str],
        title: str,
        platforms: List[str],
        description: Optional[str] = None,
        user: Optional[str] = None,
        scheduled_date: Optional[str] = None,
    ) -> str:
        """
        Publish one or more photos (a carousel when there are several) to social platforms.

        Args:
            photos (List[str]): Local file paths or public URLs of the images.
            title (str): Caption used on every platform.
            platforms (List[str]): Any of instagram, tiktok, linkedin, facebook, x, threads, pinterest, bluesky.
            description (Optional[str]): Longer text where the platform supports it.
            user (Optional[str]): Upload-Post profile to publish from. Defaults to the toolkit setting.
            scheduled_date (Optional[str]): ISO-8601 time to publish later.

        Returns:
            str: JSON with the overall status, the request_id and one result per platform.
        """
        user = user or self.user
        error = self._config_error(user)
        if error or user is None:
            return json.dumps({"status": "rejected", "error": error})
        request_id = uuid.uuid4().hex
        request = self._photos_request(request_id, user, photos, title, platforms, description, scheduled_date)
        return await self._apublish("/api/upload_photos", request, request_id)

    def upload_text(
        self,
        text: str,
        platforms: List[str],
        user: Optional[str] = None,
        scheduled_date: Optional[str] = None,
    ) -> str:
        """
        Publish a text-only post to social platforms.

        Args:
            text (str): The post text.
            platforms (List[str]): Any of linkedin, x, facebook, threads, bluesky.
            user (Optional[str]): Upload-Post profile to publish from. Defaults to the toolkit setting.
            scheduled_date (Optional[str]): ISO-8601 time to publish later.

        Returns:
            str: JSON with the overall status, the request_id and one result per platform.
        """
        user = user or self.user
        error = self._config_error(user)
        if error or user is None:
            return json.dumps({"status": "rejected", "error": error})
        request_id = uuid.uuid4().hex
        form = self._base_form(request_id, user, text, platforms, None, scheduled_date)
        return self._publish("/api/upload_text", (form, []), request_id)

    async def aupload_text(
        self,
        text: str,
        platforms: List[str],
        user: Optional[str] = None,
        scheduled_date: Optional[str] = None,
    ) -> str:
        """
        Publish a text-only post to social platforms.

        Args:
            text (str): The post text.
            platforms (List[str]): Any of linkedin, x, facebook, threads, bluesky.
            user (Optional[str]): Upload-Post profile to publish from. Defaults to the toolkit setting.
            scheduled_date (Optional[str]): ISO-8601 time to publish later.

        Returns:
            str: JSON with the overall status, the request_id and one result per platform.
        """
        user = user or self.user
        error = self._config_error(user)
        if error or user is None:
            return json.dumps({"status": "rejected", "error": error})
        request_id = uuid.uuid4().hex
        form = self._base_form(request_id, user, text, platforms, None, scheduled_date)
        return await self._apublish("/api/upload_text", (form, []), request_id)

    def get_upload_status(self, request_id: Optional[str] = None, job_id: Optional[str] = None) -> str:
        """
        Check the result of an earlier upload. Use this instead of publishing again.

        Args:
            request_id (Optional[str]): The request_id returned by an upload tool.
            job_id (Optional[str]): The job_id returned for a scheduled post.

        Returns:
            str: JSON with the overall status and one result per platform.
        """
        if not self.api_key:
            return json.dumps({"error": "No Upload-Post API key provided."})
        if not request_id and not job_id:
            return json.dumps({"error": "Provide request_id or job_id."})
        try:
            status = self._fetch_status(request_id=request_id, job_id=job_id)
        except (httpx.HTTPError, ValueError) as e:
            return json.dumps({"error": f"Status check failed: {e}"})
        return self._outcome(status, request_id or "")

    async def aget_upload_status(self, request_id: Optional[str] = None, job_id: Optional[str] = None) -> str:
        """
        Check the result of an earlier upload. Use this instead of publishing again.

        Args:
            request_id (Optional[str]): The request_id returned by an upload tool.
            job_id (Optional[str]): The job_id returned for a scheduled post.

        Returns:
            str: JSON with the overall status and one result per platform.
        """
        if not self.api_key:
            return json.dumps({"error": "No Upload-Post API key provided."})
        if not request_id and not job_id:
            return json.dumps({"error": "Provide request_id or job_id."})
        try:
            status = await self._afetch_status(request_id=request_id, job_id=job_id)
        except (httpx.HTTPError, ValueError) as e:
            return json.dumps({"error": f"Status check failed: {e}"})
        return self._outcome(status, request_id or "")

    @staticmethod
    def _profiles(data: Dict[str, Any]) -> str:
        profiles = [
            {
                "user": p.get("username"),
                "connected_platforms": sorted(k for k, v in (p.get("social_accounts") or {}).items() if v),
            }
            for p in data.get("profiles", [])
        ]
        return json.dumps({"profiles": profiles}, indent=2)

    def list_profiles(self) -> str:
        """
        List the Upload-Post profiles and the platforms connected to each one.

        Returns:
            str: JSON list of profiles with their connected platforms.
        """
        if not self.api_key:
            return json.dumps({"error": "No Upload-Post API key provided."})
        try:
            with httpx.Client(timeout=self.request_timeout) as client:
                response = client.get(f"{self.base_url}/api/uploadposts/users", headers=self._headers())
            response.raise_for_status()
            return self._profiles(response.json())
        except (httpx.HTTPError, ValueError) as e:
            return json.dumps({"error": f"Could not list profiles: {e}"})

    async def alist_profiles(self) -> str:
        """
        List the Upload-Post profiles and the platforms connected to each one.

        Returns:
            str: JSON list of profiles with their connected platforms.
        """
        if not self.api_key:
            return json.dumps({"error": "No Upload-Post API key provided."})
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.get(f"{self.base_url}/api/uploadposts/users", headers=self._headers())
            response.raise_for_status()
            return self._profiles(response.json())
        except (httpx.HTTPError, ValueError) as e:
            return json.dumps({"error": f"Could not list profiles: {e}"})
