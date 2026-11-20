"""Social media publishing, analytics and inbox tools for Rizamo."""

import json
from os import getenv
from typing import Any, Optional
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error


class RizamoTools(Toolkit):
    """Publish, schedule and measure social posts with Rizamo's REST API.

    Rizamo posts to Instagram, Facebook, TikTok, Threads, LinkedIn and YouTube accounts,
    grouped in profiles. Set RIZAMO_API_KEY or pass api_key; the key's scopes decide what
    each tool may do. Posts are drafts unless the agent gives a time to schedule them.
    Publishing now and replying to people reach the networks at once, so those two tools
    are off unless enabled.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.rizamo.com/v1",
        timeout: float = 30.0,
        enable_list_profiles: bool = True,
        enable_list_accounts: bool = True,
        enable_create_post: bool = True,
        enable_get_post: bool = True,
        enable_add_media: bool = True,
        enable_get_analytics: bool = True,
        enable_list_threads: bool = True,
        enable_publish_post: bool = False,
        enable_reply_to_thread: bool = False,
        all: bool = False,
        **kwargs: Any,
    ):
        """Configure the API key, the API address and which tools the agent gets.

        An explicit api_key overrides RIZAMO_API_KEY. base_url must be HTTPS (HTTP only on
        loopback, for tests). publish_post and reply_to_thread are off by default.
        """
        self.api_key = api_key if api_key is not None else getenv("RIZAMO_API_KEY", "")
        if not self.api_key.strip():
            raise ValueError("Provide api_key or RIZAMO_API_KEY")
        url = urlsplit(base_url)
        if (
            not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.scheme not in {"http", "https"}
            or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1", "::1"})
        ):
            raise ValueError("base_url must be HTTPS, or HTTP on loopback, without credentials or query")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        tools: list[Any] = []
        for enabled, tool in (
            (enable_list_profiles, self.list_profiles),
            (enable_list_accounts, self.list_accounts),
            (enable_create_post, self.create_post),
            (enable_get_post, self.get_post),
            (enable_add_media, self.add_media),
            (enable_get_analytics, self.get_analytics),
            (enable_list_threads, self.list_threads),
            (enable_publish_post, self.publish_post),
            (enable_reply_to_thread, self.reply_to_thread),
        ):
            if all or enabled:
                tools.append(tool)
        super().__init__(name="rizamo_tools", tools=tools, **kwargs)

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        body: Optional[dict[str, Any]] = None,
    ) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if method == "POST":
            # A retried POST with the same key does the work once.
            headers["Idempotency-Key"] = str(uuid4())
        try:
            response = httpx.request(
                method,
                self.base_url + path,
                params={k: v for k, v in (params or {}).items() if v is not None},
                json=body,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            log_error(f"Rizamo {method} {path} failed ({type(exc).__name__})")
            return json.dumps({"error": "Could not reach Rizamo. Try again later."})
        try:
            data = response.json()
        except ValueError:
            data = None
        if response.is_success:
            return json.dumps(data if data is not None else {"ok": True})
        # Rizamo's errors say what to change: pass them on to the model.
        problem = data.get("error") if isinstance(data, dict) else None
        message = problem.get("message") if isinstance(problem, dict) else None
        code = problem.get("code") if isinstance(problem, dict) else None
        log_error(f"Rizamo {method} {path} returned HTTP {response.status_code} ({code})")
        return json.dumps(
            {"error": message or f"HTTP {response.status_code}", "code": code, "status": response.status_code}
        )

    def list_profiles(self) -> str:
        """List the profiles (brands or clients) the team posts for, each with its id and time zone.

        Returns:
            str: JSON with the profiles.
        """
        return self._request("GET", "/profiles")

    def list_accounts(self, profile_id: Optional[str] = None) -> str:
        """List the connected social accounts, with their ids, networks, handles and what each can publish.

        Args:
            profile_id (Optional[str]): Only the accounts of this profile.

        Returns:
            str: JSON with the accounts.
        """
        return self._request("GET", "/accounts", params={"profileId": profile_id})

    def create_post(
        self,
        profile_id: str,
        text: str,
        account_ids: list[str],
        scheduled_at: Optional[str] = None,
        media_ids: Optional[list[str]] = None,
    ) -> str:
        """Create a post for one or more accounts of a profile: a draft, or scheduled when scheduled_at is given.

        Args:
            profile_id (str): The profile the accounts belong to.
            text (str): The post's text.
            account_ids (list[str]): The accounts to post to.
            scheduled_at (Optional[str]): ISO 8601 date and time to publish at, such as 2026-12-01T09:00:00Z.
                Without it the post is saved as a draft.
            media_ids (Optional[list[str]]): Images or videos from add_media.

        Returns:
            str: JSON with the post, its id and each target's status.
        """
        body: dict[str, Any] = {
            "profileId": profile_id,
            "text": text,
            "targets": [{"accountId": account_id} for account_id in account_ids],
            "status": "scheduled" if scheduled_at else "draft",
        }
        if scheduled_at:
            body["scheduledAt"] = scheduled_at
        if media_ids:
            body["mediaIds"] = media_ids
        return self._request("POST", "/posts", body=body)

    def get_post(self, post_id: str) -> str:
        """Get a post and each target's status, link and error.

        Args:
            post_id (str): The post's id.

        Returns:
            str: JSON with the post.
        """
        return self._request("GET", f"/posts/{post_id}")

    def add_media(self, url: str, profile_id: Optional[str] = None) -> str:
        """Add an image or video for a post from a public URL. Rizamo downloads it during the call.

        Args:
            url (str): A public http or https address of the file.
            profile_id (Optional[str]): The profile the media is for.

        Returns:
            str: JSON with the media, whose id goes in create_post's media_ids.
        """
        body: dict[str, Any] = {"url": url}
        if profile_id:
            body["profileId"] = profile_id
        return self._request("POST", "/media", body=body)

    def get_analytics(self, days: int = 28, profile_id: Optional[str] = None) -> str:
        """Get views, reach, engagements and followers over the last days, against the period before.

        Args:
            days (int): How many days back, up to today. Defaults to 28.
            profile_id (Optional[str]): Only this profile's accounts.

        Returns:
            str: JSON with the totals, each day and network, and the top posts.
        """
        return self._request("GET", "/analytics/overview", params={"days": days, "profileId": profile_id})

    def list_threads(self, status: str = "open", profile_id: Optional[str] = None) -> str:
        """List comments and messages, newest first.

        Args:
            status (str): open for what still needs an answer, or done. Defaults to open.
            profile_id (Optional[str]): Only this profile's accounts.

        Returns:
            str: JSON with the threads.
        """
        return self._request("GET", "/inbox/threads", params={"status": status, "profileId": profile_id})

    def publish_post(self, post_id: str) -> str:
        """Publish a post now, on every target that is not live yet. Off unless enabled.

        Args:
            post_id (str): The post's id.

        Returns:
            str: JSON with the post and each target's status.
        """
        return self._request("POST", f"/posts/{post_id}/publish")

    def reply_to_thread(self, thread_id: str, text: str) -> str:
        """Reply to a comment or message on its network. Off unless enabled.

        Args:
            thread_id (str): The thread's id, from list_threads.
            text (str): The reply.

        Returns:
            str: JSON with the reply.
        """
        return self._request("POST", f"/inbox/threads/{thread_id}/messages", body={"text": text})
