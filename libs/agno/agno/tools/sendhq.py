import json
from os import getenv
from typing import Any, Dict, List, Optional, Tuple

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

DEFAULT_BASE_URL = "https://sendhq.cc/api/v1"
# Bodies are cut to keep tool results within a model's context; the full message
# stays available through the API.
MAX_BODY_CHARS = 20_000
SNIPPET_CHARS = 200
NO_API_KEY = "No SendHQ API key provided. Set the SENDHQ_API_KEY environment variable."


class SendHQTools(Toolkit):
    """Send, receive, and reply to email from an agent with SendHQ.

    SendHQ (https://sendhq.cc) is an email API for sending from your own verified
    domain and receiving at inbox addresses on it. Received mail is threaded with
    sent mail, so an agent can read its inbox, follow a conversation, and answer
    inside the same thread.

    Get an API key from the SendHQ dashboard and verify a sending domain first
    (https://sendhq.cc/docs/quickstart). New workspaces can only deliver to the
    account email until a plan is active.

    Args:
        api_key: SendHQ API key. Defaults to the `SENDHQ_API_KEY` environment variable.
        from_email: Default sender, e.g. `Support <support@example.com>`. Defaults to
            `SENDHQ_FROM_EMAIL`. Its domain must be verified in the workspace.
        base_url: API base URL. Defaults to `SENDHQ_BASE_URL` or https://sendhq.cc/api/v1.
        enable_send_email: Register the `send_email` tool.
        enable_reply_to_email: Register the `reply_to_email` tool.
        enable_list_emails: Register the `list_emails` tool.
        enable_get_email: Register the `get_email` tool.
        enable_get_thread: Register the `get_thread` tool.
        all: Register every tool regardless of the individual flags.
        timeout: Per-request timeout in seconds.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        from_email: Optional[str] = None,
        base_url: Optional[str] = None,
        enable_send_email: bool = True,
        enable_reply_to_email: bool = True,
        enable_list_emails: bool = True,
        enable_get_email: bool = True,
        enable_get_thread: bool = True,
        all: bool = False,
        timeout: int = 30,
        **kwargs,
    ):
        self.api_key = api_key or getenv("SENDHQ_API_KEY")
        if not self.api_key:
            log_warning(NO_API_KEY)
        self.from_email = from_email or getenv("SENDHQ_FROM_EMAIL")
        self.base_url = (base_url or getenv("SENDHQ_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.request_timeout = timeout

        tools: List[Any] = []
        async_tools: List[Tuple[Any, str]] = []
        if all or enable_send_email:
            tools.append(self.send_email)
            async_tools.append((self.asend_email, "send_email"))
        if all or enable_reply_to_email:
            tools.append(self.reply_to_email)
            async_tools.append((self.areply_to_email, "reply_to_email"))
        if all or enable_list_emails:
            tools.append(self.list_emails)
            async_tools.append((self.alist_emails, "list_emails"))
        if all or enable_get_email:
            tools.append(self.get_email)
            async_tools.append((self.aget_email, "get_email"))
        if all or enable_get_thread:
            tools.append(self.get_thread)
            async_tools.append((self.aget_thread, "get_thread"))

        super().__init__(name="sendhq_tools", tools=tools, async_tools=async_tools, **kwargs)

    # -- HTTP ------------------------------------------------------------------------

    def _headers(self, idempotency_key: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "agno-sendhq-tools",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @staticmethod
    def _parse(response: httpx.Response) -> Tuple[bool, Dict[str, Any]]:
        try:
            data = response.json()
        except ValueError:
            data = {"error": response.text[:500]}
        if response.is_error:
            # SendHQ errors look like {"error": {"message": ..., "status": ...}}, with
            # `code`, `explanation` and `remedy` on some, so the agent can act on the
            # reason instead of retrying blindly.
            error = data.get("error") if isinstance(data, dict) else None
            details = error if isinstance(error, dict) else {}
            message = details.get("message") if details else error
            result: Dict[str, Any] = {
                "error": message or f"HTTP {response.status_code}",
                "status": response.status_code,
            }
            for key in ("code", "explanation", "remedy"):
                if details.get(key):
                    result[key] = details[key]
            return False, result
        return True, data if isinstance(data, dict) else {"data": data}

    def _request(self, method: str, path: str, **kwargs) -> Tuple[bool, Dict[str, Any]]:
        """Returns (ok, data). Emails carry their own `error` field, so success is
        reported separately from the payload rather than inferred from it."""
        if not self.api_key:
            return False, {"error": NO_API_KEY}
        idempotency_key = kwargs.pop("idempotency_key", None)
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(idempotency_key),
                timeout=self.request_timeout,
                **kwargs,
            )
            return self._parse(response)
        except httpx.HTTPError as e:
            log_error(f"SendHQ request failed: {e}")
            return False, {"error": str(e)}

    async def _arequest(self, method: str, path: str, **kwargs) -> Tuple[bool, Dict[str, Any]]:
        if not self.api_key:
            return False, {"error": NO_API_KEY}
        idempotency_key = kwargs.pop("idempotency_key", None)
        try:
            async with httpx.AsyncClient(timeout=self.request_timeout) as client:
                response = await client.request(
                    method,
                    f"{self.base_url}{path}",
                    headers=self._headers(idempotency_key),
                    **kwargs,
                )
            return self._parse(response)
        except httpx.HTTPError as e:
            log_error(f"SendHQ request failed: {e}")
            return False, {"error": str(e)}

    # -- Shaping ---------------------------------------------------------------------

    @staticmethod
    def _summary(email: Dict[str, Any]) -> Dict[str, Any]:
        text = (email.get("text") or "").strip()
        summary: Dict[str, Any] = {
            "id": email.get("id"),
            "thread_id": email.get("threadId"),
            "direction": email.get("direction"),
            "status": email.get("status"),
            "from": email.get("from"),
            "to": email.get("to"),
            "subject": email.get("subject"),
            "snippet": text[:SNIPPET_CHARS],
            "unread": email.get("unread"),
            "category": email.get("category"),
            "attachment_count": email.get("attachmentCount"),
            "created_at": email.get("createdAt"),
        }
        if email.get("error"):
            # Why SendHQ could not deliver this message, e.g. a rejected recipient.
            summary["delivery_error"] = email["error"]
        return summary

    @classmethod
    def _detail(cls, email: Dict[str, Any]) -> Dict[str, Any]:
        detail = cls._summary(email)
        detail.pop("snippet")
        body = email.get("text") or email.get("html") or ""
        detail["cc"] = email.get("cc")
        detail["reply_to"] = email.get("replyTo")
        detail["body"] = body[:MAX_BODY_CHARS]
        if len(body) > MAX_BODY_CHARS:
            detail["body_truncated"] = True
        detail["attachments"] = [
            {"id": item.get("id"), "filename": item.get("filename"), "size_bytes": item.get("sizeBytes")}
            for item in email.get("attachments") or []
        ]
        return detail

    def _send_payload(
        self,
        to: List[str],
        subject: str,
        body: str,
        from_email: Optional[str],
        cc: Optional[List[str]],
        reply_to: Optional[str],
        html: Optional[str],
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"from": from_email, "to": to, "subject": subject, "text": body}
        if html:
            payload["html"] = html
        if cc:
            payload["cc"] = cc
        if reply_to:
            payload["reply_to"] = reply_to
        return payload

    def _send_error(self, to: List[str], body: str, from_email: Optional[str]) -> Optional[str]:
        if not to:
            return "Provide at least one recipient."
        if not body:
            return "Provide a message body."
        if not from_email:
            return "No sender set. Pass from_email or set SENDHQ_FROM_EMAIL."
        return None

    @staticmethod
    def _reply_route(parent: Dict[str, Any], from_email: Optional[str]) -> Tuple[Optional[str], List[str], str]:
        """Sender, recipients and subject for a reply to `parent`.

        A reply to received mail goes back to its sender (or Reply-To); a follow-up to
        sent mail goes to the same recipients. It is sent from the configured sender,
        or else from the address that received (or sent) the original.
        """
        if parent.get("direction") == "in":
            recipients = [parent.get("replyTo") or parent.get("from")]
            sender = from_email or next(iter(parent.get("to") or []), None)
        else:
            recipients = list(parent.get("to") or [])
            sender = from_email or parent.get("from")
        subject = parent.get("subject") or ""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}".strip()
        return sender, [r for r in recipients if r], subject

    @staticmethod
    def _list_params(
        direction: Optional[str], unread: Optional[bool], query: Optional[str], limit: int
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {"limit": max(1, min(int(limit), 100))}
        if direction:
            params["direction"] = direction
        if unread is not None:
            params["unread"] = str(unread).lower()
        if query:
            params["query"] = query
        return params

    # -- Tools -----------------------------------------------------------------------

    def send_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        reply_to: Optional[str] = None,
        html: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """Send an email from the configured sender.

        Args:
            to (List[str]): Recipient addresses.
            subject (str): Subject line.
            body (str): Plain-text body.
            cc (Optional[List[str]]): Carbon-copy addresses.
            reply_to (Optional[str]): Address that replies should go to.
            html (Optional[str]): Optional HTML version of the body.
            idempotency_key (Optional[str]): Stable key for this message; retrying with the same key and identical content never sends twice.

        Returns:
            str: JSON with the new email `id` and `thread_id`, or an `error`.
        """
        error = self._send_error(to, body, self.from_email)
        if error:
            return json.dumps({"error": error})
        log_debug(f"Sending email to {to}")
        payload = self._send_payload(to, subject, body, self.from_email, cc, reply_to, html)
        ok, result = self._request("POST", "/emails", json=payload, idempotency_key=idempotency_key)
        if not ok:
            return json.dumps(result)
        return json.dumps({"id": result.get("id"), "thread_id": result.get("threadId"), "to": to})

    async def asend_email(
        self,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        reply_to: Optional[str] = None,
        html: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> str:
        """Send an email from the configured sender.

        Args:
            to (List[str]): Recipient addresses.
            subject (str): Subject line.
            body (str): Plain-text body.
            cc (Optional[List[str]]): Carbon-copy addresses.
            reply_to (Optional[str]): Address that replies should go to.
            html (Optional[str]): Optional HTML version of the body.
            idempotency_key (Optional[str]): Stable key for this message; retrying with the same key and identical content never sends twice.

        Returns:
            str: JSON with the new email `id` and `thread_id`, or an `error`.
        """
        error = self._send_error(to, body, self.from_email)
        if error:
            return json.dumps({"error": error})
        log_debug(f"Sending email to {to}")
        payload = self._send_payload(to, subject, body, self.from_email, cc, reply_to, html)
        ok, result = await self._arequest("POST", "/emails", json=payload, idempotency_key=idempotency_key)
        if not ok:
            return json.dumps(result)
        return json.dumps({"id": result.get("id"), "thread_id": result.get("threadId"), "to": to})

    def reply_to_email(self, email_id: str, body: str, idempotency_key: Optional[str] = None) -> str:
        """Reply inside an existing conversation.

        A reply to a received email goes to its sender; a follow-up to a sent email goes
        to the same recipients. It is sent from the configured sender, or else from the
        address that received the original. SendHQ threads it (In-Reply-To, References).

        Args:
            email_id (str): ID of the email being answered (starts with `em_`).
            body (str): Plain-text reply.
            idempotency_key (Optional[str]): Stable key for this reply; retrying with the same key never sends twice.

        Returns:
            str: JSON with the reply `id` and `thread_id`, or an `error`.
        """
        if not email_id:
            return json.dumps({"error": "Provide the email_id being answered."})
        ok, parent = self._request("GET", f"/emails/{email_id}")
        if not ok:
            return json.dumps(parent)
        sender, recipients, subject = self._reply_route(parent, self.from_email)
        error = self._send_error(recipients, body, sender)
        if error:
            return json.dumps({"error": error})
        payload = self._send_payload(recipients, subject, body, sender, None, None, None)
        payload["reply_to_email_id"] = email_id
        ok, result = self._request("POST", "/emails", json=payload, idempotency_key=idempotency_key)
        if not ok:
            return json.dumps(result)
        return json.dumps({"id": result.get("id"), "thread_id": result.get("threadId"), "to": recipients})

    async def areply_to_email(self, email_id: str, body: str, idempotency_key: Optional[str] = None) -> str:
        """Reply inside an existing conversation.

        A reply to a received email goes to its sender; a follow-up to a sent email goes
        to the same recipients. It is sent from the configured sender, or else from the
        address that received the original. SendHQ threads it (In-Reply-To, References).

        Args:
            email_id (str): ID of the email being answered (starts with `em_`).
            body (str): Plain-text reply.
            idempotency_key (Optional[str]): Stable key for this reply; retrying with the same key never sends twice.

        Returns:
            str: JSON with the reply `id` and `thread_id`, or an `error`.
        """
        if not email_id:
            return json.dumps({"error": "Provide the email_id being answered."})
        ok, parent = await self._arequest("GET", f"/emails/{email_id}")
        if not ok:
            return json.dumps(parent)
        sender, recipients, subject = self._reply_route(parent, self.from_email)
        error = self._send_error(recipients, body, sender)
        if error:
            return json.dumps({"error": error})
        payload = self._send_payload(recipients, subject, body, sender, None, None, None)
        payload["reply_to_email_id"] = email_id
        ok, result = await self._arequest("POST", "/emails", json=payload, idempotency_key=idempotency_key)
        if not ok:
            return json.dumps(result)
        return json.dumps({"id": result.get("id"), "thread_id": result.get("threadId"), "to": recipients})

    def list_emails(
        self,
        direction: Optional[str] = "in",
        unread: Optional[bool] = None,
        query: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """List emails newest first, without full bodies.

        Args:
            direction (Optional[str]): `in` for received mail (default), `out` for sent mail, or None for both.
            unread (Optional[bool]): True for unread only, False for read only.
            query (Optional[str]): Search subjects, bodies, addresses, and attachment names.
            limit (int): Number of emails to return (1-100). Defaults to 10.

        Returns:
            str: JSON with `emails` (id, thread_id, from, to, subject, snippet, unread, created_at), or an `error`.
        """
        ok, result = self._request("GET", "/emails", params=self._list_params(direction, unread, query, limit))
        if not ok:
            return json.dumps(result)
        emails = [self._summary(email) for email in result.get("data", [])]
        return json.dumps({"emails": emails, "count": len(emails)})

    async def alist_emails(
        self,
        direction: Optional[str] = "in",
        unread: Optional[bool] = None,
        query: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """List emails newest first, without full bodies.

        Args:
            direction (Optional[str]): `in` for received mail (default), `out` for sent mail, or None for both.
            unread (Optional[bool]): True for unread only, False for read only.
            query (Optional[str]): Search subjects, bodies, addresses, and attachment names.
            limit (int): Number of emails to return (1-100). Defaults to 10.

        Returns:
            str: JSON with `emails` (id, thread_id, from, to, subject, snippet, unread, created_at), or an `error`.
        """
        ok, result = await self._arequest("GET", "/emails", params=self._list_params(direction, unread, query, limit))
        if not ok:
            return json.dumps(result)
        emails = [self._summary(email) for email in result.get("data", [])]
        return json.dumps({"emails": emails, "count": len(emails)})

    def get_email(self, email_id: str) -> str:
        """Read one email in full.

        Args:
            email_id (str): Email ID (starts with `em_`).

        Returns:
            str: JSON with the sender, recipients, subject, body, thread_id, and attachment names, or an `error`.
        """
        if not email_id:
            return json.dumps({"error": "Provide an email_id."})
        ok, result = self._request("GET", f"/emails/{email_id}")
        if not ok:
            return json.dumps(result)
        return json.dumps(self._detail(result))

    async def aget_email(self, email_id: str) -> str:
        """Read one email in full.

        Args:
            email_id (str): Email ID (starts with `em_`).

        Returns:
            str: JSON with the sender, recipients, subject, body, thread_id, and attachment names, or an `error`.
        """
        if not email_id:
            return json.dumps({"error": "Provide an email_id."})
        ok, result = await self._arequest("GET", f"/emails/{email_id}")
        if not ok:
            return json.dumps(result)
        return json.dumps(self._detail(result))

    def get_thread(self, thread_id: str) -> str:
        """Read a whole conversation, sent and received messages in order.

        Args:
            thread_id (str): Thread ID (the `thread_id` of any email in the conversation).

        Returns:
            str: JSON with the thread `subject` and its `messages` oldest first, or an `error`.
        """
        if not thread_id:
            return json.dumps({"error": "Provide a thread_id."})
        ok, result = self._request("GET", f"/threads/{thread_id}")
        if not ok:
            return json.dumps(result)
        messages = [self._detail(email) for email in result.get("data", [])]
        return json.dumps({"thread_id": result.get("id"), "subject": result.get("subject"), "messages": messages})

    async def aget_thread(self, thread_id: str) -> str:
        """Read a whole conversation, sent and received messages in order.

        Args:
            thread_id (str): Thread ID (the `thread_id` of any email in the conversation).

        Returns:
            str: JSON with the thread `subject` and its `messages` oldest first, or an `error`.
        """
        if not thread_id:
            return json.dumps({"error": "Provide a thread_id."})
        ok, result = await self._arequest("GET", f"/threads/{thread_id}")
        if not ok:
            return json.dumps(result)
        messages = [self._detail(email) for email in result.get("data", [])]
        return json.dumps({"thread_id": result.get("id"), "subject": result.get("subject"), "messages": messages})
