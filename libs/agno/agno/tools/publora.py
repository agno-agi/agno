import json
from os import getenv
from typing import Any, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning


class PubloraTools(Toolkit):
    """
    PubloraTools publishes and schedules social media posts through Publora.

    One call reaches LinkedIn, X, Instagram, Threads, TikTok, YouTube, Facebook,
    Bluesky, Mastodon and Telegram. Get an API key at https://publora.com
    (API in the left menu) and see https://docs.publora.com for the API.

    Args:
        api_key (Optional[str]): Publora API key. If not provided, uses PUBLORA_API_KEY env var.
        timeout (int): Request timeout in seconds. Default is 30.
        list_connections (bool): Enable listing connected social accounts. Default is True.
        create_post (bool): Enable creating posts. Default is True.
        get_post (bool): Enable reading a single post. Default is True.
        list_posts (bool): Enable listing posts. Default is True.
        update_post (bool): Enable editing an existing post. Default is False.
        delete_post (bool): Enable deleting a post. Default is False.
        all (bool): If True, enable every tool regardless of the individual flags.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 30,
        list_connections: bool = True,
        create_post: bool = True,
        get_post: bool = True,
        list_posts: bool = True,
        update_post: bool = False,
        delete_post: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("PUBLORA_API_KEY")
        if not self.api_key:
            log_warning("No Publora API key provided. Set the PUBLORA_API_KEY environment variable.")

        self.timeout = timeout
        self.base_url = "https://api.publora.com/api/v1"

        tools: List[Any] = []
        if all or list_connections:
            tools.append(self.list_connections)
        if all or create_post:
            tools.append(self.create_post)
        if all or get_post:
            tools.append(self.get_post)
        if all or list_posts:
            tools.append(self.list_posts)
        if all or update_post:
            tools.append(self.update_post)
        if all or delete_post:
            tools.append(self.delete_post)

        super().__init__(name="publora_tools", tools=tools, **kwargs)

    def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Makes a request to the Publora API.

        Args:
            method (str): HTTP method, e.g. "GET", "POST", "PUT" or "DELETE".
            endpoint (str): The API endpoint, e.g. "create-post".
            params (Optional[Dict[str, Any]]): Query parameters.
            payload (Optional[Dict[str, Any]]): JSON body.

        Returns:
            Dict[str, Any]: The parsed JSON response or an error dict.
        """
        try:
            if not self.api_key:
                return {"error": "No Publora API key provided. Set the PUBLORA_API_KEY environment variable."}

            headers = {
                "x-publora-key": self.api_key,
                "Accept": "application/json",
                "User-Agent": "agno",
            }

            log_debug(f"Requesting Publora endpoint={endpoint} method={method}")
            response = requests.request(
                method,
                f"{self.base_url}/{endpoint}",
                headers=headers,
                params=params,
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()

            return response.json()  # type: ignore[no-any-return]
        except requests.exceptions.HTTPError as e:
            log_error(f"Publora HTTP error: {e}")
            return {"error": f"HTTP error: {e}"}
        except requests.exceptions.RequestException as e:
            log_error(f"Publora request error: {e}")
            return {"error": str(e)}
        except ValueError as e:
            log_error(f"Publora JSON decode error: {e}")
            return {"error": f"Invalid JSON response: {e}"}

    def list_connections(self) -> str:
        """
        Lists the social accounts connected in Publora.

        Call this before creating a post: every account has a platform id such as
        `linkedin-n20H8w1Omj`, and those ids have to be copied exactly as returned.

        Returns:
            str: JSON with the connected accounts, their platform, username and token status.
        """
        data = self._request("GET", "platform-connections")

        if "error" in data:
            return json.dumps({"error": data["error"]})

        result = {
            "connections": [
                {
                    "platform_id": c.get("platformId"),
                    "platform": c.get("platform"),
                    "username": c.get("username"),
                    "token_status": c.get("tokenStatus"),
                    "last_error": c.get("lastError"),
                }
                for c in data.get("connections", [])
            ]
        }

        return json.dumps(result, indent=2)

    def create_post(
        self,
        content: str,
        platform_ids: List[str],
        scheduled_time: Optional[str] = None,
        media_urls: Optional[List[str]] = None,
    ) -> str:
        """
        Creates a post in Publora.

        Args:
            content (str): The text of the post.
            platform_ids (List[str]): Platform ids from `list_connections`, copied exactly.
            scheduled_time (Optional[str]): When to publish, ISO 8601 in UTC, e.g. "2026-10-20T09:00:00Z".
                Leave it out and the post is saved as a draft instead of going out.
            media_urls (Optional[List[str]]): Public https links to images or video. Publora
                downloads them itself. Instagram, TikTok and YouTube do not accept a post without media.

        Returns:
            str: JSON with the id of the created post group.
        """
        if not content:
            return json.dumps({"error": "Please provide the text of the post"})
        if not platform_ids:
            return json.dumps({"error": "Please provide at least one platform id from list_connections"})

        payload: Dict[str, Any] = {"content": content, "platforms": platform_ids}
        if scheduled_time:
            payload["scheduledTime"] = scheduled_time
        if media_urls:
            payload["mediaUrls"] = media_urls

        data = self._request("POST", "create-post", payload=payload)

        if "error" in data:
            return json.dumps({"error": data["error"]})

        return json.dumps(
            {
                "post_group_id": data.get("postGroupId"),
                "scheduled_time": data.get("scheduledTime"),
                "status": "scheduled" if scheduled_time else "draft",
            },
            indent=2,
        )

    def get_post(self, post_group_id: str) -> str:
        """
        Reads one post and the state of every account it targets.

        Args:
            post_group_id (str): The id returned when the post was created.

        Returns:
            str: JSON with the status, the scheduled time and the per-account results.
        """
        if not post_group_id:
            return json.dumps({"error": "Please provide the post group id"})

        data = self._request("GET", f"get-post/{post_group_id}")

        if "error" in data:
            return json.dumps({"error": data["error"]})

        return json.dumps(
            {
                "post_group_id": data.get("postGroupId"),
                "status": data.get("status"),
                "scheduled_time": data.get("scheduledTime"),
                "posts": [
                    {
                        "platform": p.get("platform"),
                        "platform_id": p.get("platformId"),
                        "status": p.get("status"),
                        "permalink": p.get("permalink"),
                    }
                    for p in data.get("posts", [])
                ],
            },
            indent=2,
        )

    def list_posts(self, status: Optional[str] = None, limit: int = 20) -> str:
        """
        Lists posts in Publora.

        Args:
            status (Optional[str]): Filter by status: "draft", "scheduled", "published" or "failed".
            limit (int): How many posts to return. Default is 20.

        Returns:
            str: JSON with the posts, newest first.
        """
        params: Dict[str, Any] = {"limit": limit}
        if status:
            params["status"] = status

        data = self._request("GET", "list-posts", params=params)

        if "error" in data:
            return json.dumps({"error": data["error"]})

        result = {
            "posts": [
                {
                    "post_group_id": p.get("postGroupId"),
                    "status": p.get("status"),
                    "scheduled_time": p.get("scheduledTime"),
                    "content": p.get("content"),
                    "platforms": [x.get("platform") for x in p.get("platforms", [])],
                }
                for p in data.get("posts", [])
            ]
        }

        return json.dumps(result, indent=2)

    def update_post(
        self,
        post_group_id: str,
        content: Optional[str] = None,
        scheduled_time: Optional[str] = None,
        status: Optional[str] = None,
    ) -> str:
        """
        Edits a draft or a scheduled post.

        Args:
            post_group_id (str): The id of the post group.
            content (Optional[str]): New text.
            scheduled_time (Optional[str]): New time, ISO 8601 in UTC.
            status (Optional[str]): "draft" to take a scheduled post out of the queue,
                "scheduled" to put a draft back in it.

        Returns:
            str: JSON with the id of the updated post group.
        """
        if not post_group_id:
            return json.dumps({"error": "Please provide the post group id"})

        payload: Dict[str, Any] = {}
        if content:
            payload["content"] = content
        if scheduled_time:
            payload["scheduledTime"] = scheduled_time
        if status:
            payload["status"] = status

        if not payload:
            return json.dumps({"error": "Please provide something to change: content, scheduled_time or status"})

        data = self._request("PUT", f"update-post/{post_group_id}", payload=payload)

        if "error" in data:
            return json.dumps({"error": data["error"]})

        return json.dumps({"post_group_id": (data.get("postGroup") or {}).get("_id", post_group_id)}, indent=2)

    def delete_post(self, post_group_id: str) -> str:
        """
        Deletes a post from Publora.

        A post that has already gone out stays on the social network: this removes the
        record in Publora, not the published post.

        Args:
            post_group_id (str): The id of the post group.

        Returns:
            str: JSON with the result of the deletion.
        """
        if not post_group_id:
            return json.dumps({"error": "Please provide the post group id"})

        data = self._request("DELETE", f"delete-post/{post_group_id}")

        if "error" in data:
            return json.dumps({"error": data["error"]})

        return json.dumps({"deleted": bool(data.get("success")), "post_group_id": post_group_id}, indent=2)
