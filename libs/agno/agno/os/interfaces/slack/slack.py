import asyncio
import os
from ssl import SSLContext
from typing import Dict, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.slack.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class Slack(BaseInterface):
    type = "slack"

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent]] = None,
        team: Optional[Union[Team, RemoteTeam]] = None,
        workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
        prefix: str = "/slack",
        tags: Optional[List[str]] = None,
        reply_to_mentions_only: bool = True,
        token: Optional[str] = None,
        signing_secret: Optional[str] = None,
        streaming: bool = True,
        loading_messages: Optional[List[str]] = None,
        task_display_mode: str = "plan",
        loading_text: str = "Thinking...",
        suggested_prompts: Optional[List[Dict[str, str]]] = None,
        ssl: Optional[SSLContext] = None,
        buffer_size: int = 100,
        max_file_size: int = 1_073_741_824,  # 1GB
        resolve_user_identity: bool = False,
        # Socket Mode
        socket_mode: bool = False,
        app_token: Optional[str] = None,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Slack"]
        self.reply_to_mentions_only = reply_to_mentions_only
        self.token = token
        self.signing_secret = signing_secret
        self.streaming = streaming
        self.loading_messages = loading_messages
        self.task_display_mode = task_display_mode
        self.loading_text = loading_text
        self.suggested_prompts = suggested_prompts
        self.ssl = ssl
        self.buffer_size = buffer_size
        self.max_file_size = max_file_size
        self.resolve_user_identity = resolve_user_identity
        self.socket_mode = socket_mode
        self.app_token = app_token

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Slack requires an agent, team, or workflow")

    def get_router(self) -> APIRouter:
        self.router = attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            reply_to_mentions_only=self.reply_to_mentions_only,
            token=self.token,
            signing_secret=self.signing_secret,
            streaming=self.streaming,
            loading_messages=self.loading_messages,
            task_display_mode=self.task_display_mode,
            loading_text=self.loading_text,
            suggested_prompts=self.suggested_prompts,
            ssl=self.ssl,
            buffer_size=self.buffer_size,
            max_file_size=self.max_file_size,
            resolve_user_identity=self.resolve_user_identity,
        )

        return self.router

    async def astart(self) -> None:
        """Start the Slack bot using Socket Mode.

        Connects to Slack over a persistent WebSocket so no public HTTP endpoint
        is required.  Blocks until the connection is closed or the task is
        cancelled (e.g. via Ctrl-C).

        Requires ``socket_mode=True`` and either ``app_token`` set on this
        instance or the ``SLACK_APP_TOKEN`` environment variable.

        Raises:
            RuntimeError: If called without ``socket_mode=True``.
            ValueError: If no App-Level Token is available.
        """
        if not self.socket_mode:
            raise RuntimeError(
                "astart() is only available in Socket Mode. "
                "Set socket_mode=True when creating the Slack interface."
            )

        app_token = self.app_token or os.environ.get("SLACK_APP_TOKEN")
        if not app_token:
            raise ValueError(
                "Socket Mode requires an App-Level Token. "
                "Pass app_token='xapp-...' or set the SLACK_APP_TOKEN environment variable."
            )

        from agno.os.interfaces.slack._processing import build_processing_config
        from agno.os.interfaces.slack.socket_mode import start_socket_mode

        config = build_processing_config(
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            reply_to_mentions_only=self.reply_to_mentions_only,
            token=self.token,
            streaming=self.streaming,
            loading_messages=self.loading_messages,
            task_display_mode=self.task_display_mode,
            loading_text=self.loading_text,
            suggested_prompts=self.suggested_prompts,
            ssl=self.ssl,
            buffer_size=self.buffer_size,
            max_file_size=self.max_file_size,
            resolve_user_identity=self.resolve_user_identity,
        )

        await start_socket_mode(config, app_token)

    def start(self) -> None:
        """Start the Slack bot using Socket Mode (synchronous wrapper).

        Calls :meth:`astart` inside a new event loop via ``asyncio.run()``.
        Use this as the entry point in scripts that do not already have a
        running event loop.

        Example::

            slack = Slack(agent=my_agent, socket_mode=True)
            slack.start()
        """
        asyncio.run(self.astart())
