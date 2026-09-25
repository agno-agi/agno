"""Lark (Feishu) chat interface for Agno.

Exposes an :class:`~agno.agent.Agent`, :class:`~agno.team.Team`, or
:class:`~agno.workflow.Workflow` as a Lark bot reachable via webhook event
subscription. Mounts a FastAPI router under ``/lark`` (configurable) that
receives ``im.message.receive_v1`` events and replies via the Lark IM API.

Example::

    from agno.os.interfaces.lark import Lark

    lark_interface = Lark(agent=my_agent)
    agent_os = AgentOS(interfaces=[lark_interface])

Required credentials (pass as kwargs or set as env vars ``LARK_APP_ID`` /
``LARK_APP_SECRET``):

  * ``app_id`` / ``app_secret`` — from the Lark Developer Console app page.
  * ``verification_token`` — Events & Callbacks → Encryption Strategy (optional
    but recommended; checked against ``header.token`` on every event).
  * ``encrypt_key`` — optional; when set, event payloads are AES-encrypted and
    webhook requests carry an ``X-Lark-Signature`` to verify.

Requires the ``cryptography`` package only when ``encrypt_key`` is used
(``pip install 'agno[lark-crypto]'``). Sending/receiving uses ``httpx`` which
is a core agno dependency.
"""

from __future__ import annotations

from typing import List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.lark.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class Lark(BaseInterface):
    """Lark (Feishu) bot interface.

    See module docstring for credential setup. The interface is a thin config
    holder — all logic lives in :mod:`agno.os.interfaces.lark.router`.
    """

    type = "lark"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/lark",
        tags: Optional[List[str]] = None,
        # Credentials (fall back to env vars LARK_APP_ID / LARK_APP_SECRET / ...)
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        verification_token: Optional[str] = None,
        encrypt_key: Optional[str] = None,
        # "https://open.feishu.cn" (default) for Feishu, "https://open.larksuite.com" for Lark.
        domain: Optional[str] = None,
        # Timeout in seconds for media downloads/uploads.
        media_timeout: int = 30,
        # Stream responses token-by-token (PATCHing an interactive card in place).
        streaming: bool = True,
        # Send the agent's reasoning_content as a separate message before the answer.
        show_reasoning: bool = False,
        # In group chats, only respond when the bot is @mentioned (default True).
        reply_to_mentions_only: bool = True,
        # Reply to the user's message (threaded) instead of sending a standalone message.
        quoted_responses: bool = False,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        # Tags group endpoints in OpenAPI docs.
        self.tags = tags or ["Lark"]
        self.app_id = app_id
        self.app_secret = app_secret
        self.verification_token = verification_token
        self.encrypt_key = encrypt_key
        self.domain = domain
        self.media_timeout = media_timeout
        self.streaming = streaming
        self.show_reasoning = show_reasoning
        self.reply_to_mentions_only = reply_to_mentions_only
        self.quoted_responses = quoted_responses

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Lark requires an agent, team, or workflow")

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore

        self.router = attach_routes(
            router=self.router,
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            prefix=self.prefix,
            tags=self.tags,
            app_id=self.app_id,
            app_secret=self.app_secret,
            verification_token=self.verification_token,
            encrypt_key=self.encrypt_key,
            domain=self.domain,
            media_timeout=self.media_timeout,
            streaming=self.streaming,
            show_reasoning=self.show_reasoning,
            reply_to_mentions_only=self.reply_to_mentions_only,
            quoted_responses=self.quoted_responses,
        )

        return self.router
