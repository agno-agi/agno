"""Slack members linked to os.agno.com accounts, resolved by the Agno platform for Super Agent."""

import time
from dataclasses import dataclass
from datetime import datetime
from os import getenv
from typing import Any, Dict, Optional, Tuple

import httpx

DEFAULT_PLATFORM_API_URL = "https://os-api.agno.com/api/v1"
# A linked member's token is reused until this many seconds before it expires
_TOKEN_MARGIN_SECONDS = 60.0


@dataclass
class MemberLink:
    """What the platform knows of a Slack member on this AgentOS.

    status is "linked" (with a per-OS user token and its email), "not_linked" or "no_access"
    (with a link_url where the member links their account, and a reason for no_access).
    """

    status: str
    token: Optional[str] = None
    email: Optional[str] = None
    expires_at: Optional[float] = None
    link_url: Optional[str] = None
    reason: Optional[str] = None


class PlatformUnavailable(Exception):
    """The platform did not answer, or refused this AgentOS's service token."""


class PlatformLinks:
    """Resolves Slack members through the platform, authenticated with the AgentOS's service token.

    A linked member's token is cached until shortly before it expires. Other answers are not cached,
    so a member who just linked, or lost access, is resolved again on their next message.
    """

    def __init__(self, service_token: str, api_url: Optional[str] = None, timeout: float = 10.0):
        self.service_token = service_token
        self.api_url = (api_url or DEFAULT_PLATFORM_API_URL).rstrip("/")
        self.timeout = timeout
        self._linked: Dict[Tuple[str, str], MemberLink] = {}

    @classmethod
    def from_env(cls) -> Optional["PlatformLinks"]:
        """Built from AGNO_OS_SERVICE_TOKEN and AGNO_PLATFORM_API_URL; None without a service token."""
        token = getenv("AGNO_OS_SERVICE_TOKEN")
        if not token:
            return None
        return cls(token, getenv("AGNO_PLATFORM_API_URL"))

    async def resolve_slack_member(
        self,
        team_id: str,
        member_id: str,
        *,
        team_name: Optional[str] = None,
        member_name: Optional[str] = None,
        member_email: Optional[str] = None,
    ) -> MemberLink:
        key = (team_id, member_id)
        cached = self._linked.get(key)
        if cached is not None and (cached.expires_at or 0) - _TOKEN_MARGIN_SECONDS > time.time():
            return cached
        self._linked.pop(key, None)
        body: Dict[str, Any] = {"team_id": team_id, "member_id": member_id}
        for name, value in (("team_name", team_name), ("member_name", member_name), ("member_email", member_email)):
            if value:
                body[name] = value
        url = f"{self.api_url}/identity-links/slack/resolve"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    json=body,
                    headers={"Authorization": f"Bearer {self.service_token}"},
                )
        except httpx.HTTPError as e:
            raise PlatformUnavailable(f"Agno platform unreachable at {url}: {e}") from e
        if response.status_code == 401:
            raise PlatformUnavailable("The Agno platform refused AGNO_OS_SERVICE_TOKEN; it may have been revoked")
        if response.status_code != 200:
            raise PlatformUnavailable(
                f"Agno platform answered {response.status_code} at {url}; check AGNO_PLATFORM_API_URL"
            )
        data = response.json()
        link = MemberLink(
            status=data.get("status") or "",
            token=data.get("token"),
            email=data.get("email"),
            expires_at=_epoch(data.get("expires_at")),
            link_url=data.get("link_url"),
            reason=data.get("reason"),
        )
        if link.status == "linked" and link.token and link.email and link.expires_at:
            self._linked[key] = link
        return link

    def forget(self, team_id: str, member_id: str) -> None:
        """Drop a member's cached token, e.g. after it was refused."""
        self._linked.pop((team_id, member_id), None)


def _epoch(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None
