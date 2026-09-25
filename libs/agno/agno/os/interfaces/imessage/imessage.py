from os import getenv
from typing import List, Optional, Union
from urllib.parse import urlsplit

from fastapi import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.imessage.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class IMessage(BaseInterface):
    """Connect an Agent, Team, or Workflow to iMessage through BlueBubbles.

    The initial interface supports incoming text in direct iMessage chats.
    BlueBubbles must run on a Mac signed into Messages. Register its New Message
    webhook at ``<prefix>/webhook?token=<webhook_secret>``.

    ``allowed_senders`` contains exact phone numbers or email addresses as reported
    by BlueBubbles. None allows all senders; an empty list allows none.
    """

    type = "imessage"
    authenticates_own_requests = True

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/imessage",
        tags: Optional[List[str]] = None,
        server_url: Optional[str] = None,
        password: Optional[str] = None,
        webhook_secret: Optional[str] = None,
        allowed_senders: Optional[List[str]] = None,
        timeout: float = 30.0,
    ):
        if sum(entity is not None for entity in (agent, team, workflow)) != 1:
            raise ValueError("IMessage requires exactly one agent, team, or workflow")
        if not prefix.startswith("/") or prefix.endswith("/") or any(c in prefix for c in "*?{}"):
            raise ValueError("IMessage prefix must be a non-root path without a trailing slash or wildcards")
        if timeout <= 0:
            raise ValueError("IMessage timeout must be positive")

        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["iMessage"]
        self.server_url = (server_url or getenv("BLUEBUBBLES_SERVER_URL", "")).rstrip("/")
        self.password = password or getenv("BLUEBUBBLES_PASSWORD", "")
        self.webhook_secret = webhook_secret or getenv("IMESSAGE_WEBHOOK_SECRET", "")
        self.allowed_senders = set(allowed_senders) if allowed_senders is not None else None
        self.timeout = timeout

        parsed_url = urlsplit(self.server_url)
        if (
            parsed_url.scheme not in ("http", "https")
            or not parsed_url.hostname
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
        ):
            raise ValueError(
                "Set BLUEBUBBLES_SERVER_URL to an HTTP(S) base URL without credentials or query parameters"
            )
        if not self.password:
            raise ValueError("Set BLUEBUBBLES_PASSWORD or pass password")
        if not self.webhook_secret:
            raise ValueError("Set IMESSAGE_WEBHOOK_SECRET or pass webhook_secret")

    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        self.router = attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore[arg-type]
            interface=self,
            use_async=use_async,
        )
        return self.router
