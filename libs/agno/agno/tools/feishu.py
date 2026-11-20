"""Feishu / Lark toolkit for outbound messaging and chat operations."""

import json
import time
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import logger

FEISHU_BASE_URL = "https://open.feishu.cn"
LARK_BASE_URL = "https://open.larksuite.com"

# Refresh the tenant access token this many seconds before Feishu says it expires.
_TOKEN_REFRESH_MARGIN_SECONDS = 60


class FeishuAPIError(Exception):
    """Feishu returned a business error (``code != 0``) in an otherwise successful HTTP response."""

    def __init__(self, code: Any, msg: Any):
        self.code = code
        self.msg = msg
        super().__init__(f"Feishu API error {code}: {msg}")


class FeishuTools(Toolkit):
    """Toolkit for sending messages and reading chat/user info via the Feishu (Lark) Open API.

    Authenticates as a bot app with ``FEISHU_APP_ID`` + ``FEISHU_APP_SECRET`` and caches the
    resulting ``tenant_access_token`` until shortly before it expires.

    Args:
        app_id: Feishu app ID. Falls back to the FEISHU_APP_ID env var.
        app_secret: Feishu app secret. Falls back to the FEISHU_APP_SECRET env var.
        base_url: API host. Defaults to https://open.feishu.cn; use https://open.larksuite.com for Lark.
        receive_id_type: Default id type for send_message (chat_id, open_id, user_id, union_id, email).
        enable_send_message: Enable send_message tool. Defaults to True.
        enable_get_chat: Enable get_chat tool. Defaults to True.
        enable_list_chats: Enable list_chats tool. Defaults to True.
        enable_get_user: Enable get_user tool. Defaults to True.
        enable_reply_message: Enable reply_message tool. Defaults to False.
        enable_delete_message: Enable delete_message tool. Defaults to False.
        all: Enable all tools. Overrides individual flags when True.
        timeout: HTTP timeout in seconds for every Feishu API call.
    """

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        base_url: Optional[str] = None,
        receive_id_type: str = "chat_id",
        enable_send_message: bool = True,
        enable_get_chat: bool = True,
        enable_list_chats: bool = True,
        enable_get_user: bool = True,
        enable_reply_message: bool = False,
        enable_delete_message: bool = False,
        all: bool = False,
        timeout: int = 30,
        **kwargs: Any,
    ):
        self.app_id = app_id or getenv("FEISHU_APP_ID")
        if not self.app_id:
            raise ValueError("FEISHU_APP_ID not set. Set the environment variable or pass app_id.")

        self.app_secret = app_secret or getenv("FEISHU_APP_SECRET")
        if not self.app_secret:
            raise ValueError("FEISHU_APP_SECRET not set. Set the environment variable or pass app_secret.")

        self.base_url = (base_url or getenv("FEISHU_BASE_URL") or FEISHU_BASE_URL).rstrip("/")
        self.receive_id_type = receive_id_type

        # Cached tenant access token and the epoch second it should be refreshed at.
        self._tenant_access_token: Optional[str] = None
        self._token_refresh_at: float = 0.0

        tools: List[Any] = []
        if enable_send_message or all:
            tools.append(self.send_message)
        if enable_get_chat or all:
            tools.append(self.get_chat)
        if enable_list_chats or all:
            tools.append(self.list_chats)
        if enable_get_user or all:
            tools.append(self.get_user)
        if enable_reply_message or all:
            tools.append(self.reply_message)
        if enable_delete_message or all:
            tools.append(self.delete_message)

        super().__init__(name="feishu", tools=tools, timeout=timeout, **kwargs)

    # ------------------------------------------------------------------
    # Auth and transport
    # ------------------------------------------------------------------

    def _get_tenant_access_token(self) -> str:
        """Return a cached tenant access token, fetching a new one when missing or about to expire."""
        if self._tenant_access_token and time.time() < self._token_refresh_at:
            return self._tenant_access_token

        response = httpx.post(
            f"{self.base_url}/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        # Unlike the business APIs, the token endpoint puts its fields at the top level, not under "data".
        if payload.get("code") != 0:
            raise FeishuAPIError(payload.get("code"), payload.get("msg"))
        token = payload.get("tenant_access_token")
        if not token:
            raise FeishuAPIError(payload.get("code"), "response did not include tenant_access_token")

        expire = int(payload.get("expire") or 0)
        self._tenant_access_token = token
        self._token_refresh_at = time.time() + max(expire - _TOKEN_REFRESH_MARGIN_SECONDS, 0)
        return token

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Call the Feishu API with a bearer token and return the parsed ``data`` object.

        Raises on HTTP errors and on Feishu business errors (``code != 0``).
        """
        token = self._get_tenant_access_token()
        response = httpx.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=json_body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise FeishuAPIError(payload.get("code"), payload.get("msg"))
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _error(message: str) -> str:
        return json.dumps({"status": "error", "message": message})

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def send_message(self, receive_id: str, text: str, receive_id_type: Optional[str] = None) -> str:
        """Send a plain text message to a chat or user.

        Args:
            receive_id: The chat_id, open_id, user_id, union_id or email to send to.
            text: The message text.
            receive_id_type: Which kind of id receive_id is. Defaults to the toolkit's receive_id_type.

        Returns:
            JSON string with status and message_id.
        """
        try:
            data = self._request(
                method="POST",
                path="/open-apis/im/v1/messages",
                params={"receive_id_type": receive_id_type or self.receive_id_type},
                json_body={"receive_id": receive_id, "msg_type": "text", "content": json.dumps({"text": text})},
            )
            return json.dumps(
                {"status": "success", "message_id": data.get("message_id"), "chat_id": data.get("chat_id")}
            )
        except Exception as e:
            logger.exception("Error sending Feishu message")
            return self._error(str(e))

    def reply_message(self, message_id: str, text: str) -> str:
        """Reply to an existing message in its thread.

        Args:
            message_id: The id of the message to reply to.
            text: The reply text.

        Returns:
            JSON string with status and message_id.
        """
        try:
            data = self._request(
                method="POST",
                path=f"/open-apis/im/v1/messages/{message_id}/reply",
                json_body={"msg_type": "text", "content": json.dumps({"text": text})},
            )
            return json.dumps({"status": "success", "message_id": data.get("message_id")})
        except Exception as e:
            logger.exception("Error replying to Feishu message")
            return self._error(str(e))

    def delete_message(self, message_id: str) -> str:
        """Recall (delete) a message that this bot sent.

        Args:
            message_id: The id of the message to delete.

        Returns:
            JSON string with status and deleted flag.
        """
        try:
            self._request(method="DELETE", path=f"/open-apis/im/v1/messages/{message_id}")
            return json.dumps({"status": "success", "deleted": True, "message_id": message_id})
        except Exception as e:
            logger.exception("Error deleting Feishu message")
            return self._error(str(e))

    def get_chat(self, chat_id: str) -> str:
        """Get information about a chat (group) the bot is in.

        Args:
            chat_id: The chat id, e.g. oc_xxx.

        Returns:
            JSON string with status and chat info.
        """
        try:
            data = self._request(method="GET", path=f"/open-apis/im/v1/chats/{chat_id}")
            return json.dumps({"status": "success", **data})
        except Exception as e:
            logger.exception("Error getting Feishu chat")
            return self._error(str(e))

    def list_chats(self, page_size: int = 20, page_token: Optional[str] = None) -> str:
        """List chats (groups) the bot is a member of.

        Args:
            page_size: Number of chats to return, max 100.
            page_token: Pagination token from a previous call.

        Returns:
            JSON string with status, items, has_more and page_token.
        """
        try:
            data = self._request(
                method="GET", path="/open-apis/im/v1/chats", params={"page_size": page_size, "page_token": page_token}
            )
            return json.dumps(
                {
                    "status": "success",
                    "items": data.get("items"),
                    "has_more": data.get("has_more"),
                    "page_token": data.get("page_token"),
                }
            )
        except Exception as e:
            logger.exception("Error listing Feishu chats")
            return self._error(str(e))

    def get_user(self, user_id: str, user_id_type: str = "open_id") -> str:
        """Get basic profile information for a user.

        Args:
            user_id: The user's id.
            user_id_type: Which kind of id user_id is (open_id, union_id, user_id).

        Returns:
            JSON string with status and user info.
        """
        try:
            data = self._request(
                method="GET", path=f"/open-apis/contact/v3/users/{user_id}", params={"user_id_type": user_id_type}
            )
            return json.dumps({"status": "success", "user": data.get("user")})
        except Exception as e:
            logger.exception("Error getting Feishu user")
            return self._error(str(e))
