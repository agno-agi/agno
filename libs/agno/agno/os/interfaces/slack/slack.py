import asyncio
from os import getenv
from ssl import SSLContext
from typing import Dict, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.slack.router import attach_routes, build_handlers
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class Slack(BaseInterface):
    type = "slack"

    # Verifies the Slack request signature (X-Slack-Signature) in its router, so it is
    # excluded from the central auth layer.
    authenticates_own_requests = True

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
        respond_to_other_apps: bool = False,
        markdown: bool = True,
        unfurl_links: bool = True,
        unfurl_media: bool = True,
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
        self.respond_to_other_apps = respond_to_other_apps
        self.markdown = markdown
        self.unfurl_links = unfurl_links
        self.unfurl_media = unfurl_media

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
            respond_to_other_apps=self.respond_to_other_apps,
            markdown=self.markdown,
            unfurl_links=self.unfurl_links,
            unfurl_media=self.unfurl_media,
        )

        return self.router

    async def astart_socket_mode(self, app_token: Optional[str] = None) -> None:
        """Run this interface over Slack Socket Mode until cancelled.

        The app-level token (xapp-...) comes from ``app_token``, then ``SLACK_APP_TOKEN``; the bot
        token and every other setting are the ones this interface already holds.
        """
        app_token = app_token or getenv("SLACK_APP_TOKEN")
        if not app_token:
            raise ValueError(
                "Slack Socket Mode requires an app-level token: pass app_token='xapp-...' or set SLACK_APP_TOKEN"
            )

        try:
            from agno.os.interfaces.slack.socket_mode import run_socket_mode
        except ImportError as e:
            raise ImportError(
                "Slack dependencies not installed. Please install using `pip install 'agno[slack]'`"
            ) from e

        # build_handlers calls auth.test synchronously (the HTTP path pays that at mount time,
        # before any loop exists); off the loop here so an embedding loop is not stalled.
        event_handler, hitl, event_dedupe = await asyncio.to_thread(
            build_handlers,
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            reply_to_mentions_only=self.reply_to_mentions_only,
            token=self.token,
            loading_messages=self.loading_messages,
            task_display_mode=self.task_display_mode,
            loading_text=self.loading_text,
            suggested_prompts=self.suggested_prompts,
            ssl=self.ssl,
            buffer_size=self.buffer_size,
            max_file_size=self.max_file_size,
            resolve_user_identity=self.resolve_user_identity,
            respond_to_other_apps=self.respond_to_other_apps,
            markdown=self.markdown,
            unfurl_links=self.unfurl_links,
            unfurl_media=self.unfurl_media,
        )
        await run_socket_mode(
            app_token,
            event_handler=event_handler,
            hitl=hitl,
            event_dedupe=event_dedupe,
            streaming=self.streaming,
            ssl=self.ssl,
        )

    def start_socket_mode(self, app_token: Optional[str] = None) -> None:
        """Blocking twin of ``astart_socket_mode`` for scripts that have no event loop."""
        # Checked before the coroutine is created so a rejected call leaves nothing unawaited.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "start_socket_mode() cannot be called from a running event loop; await astart_socket_mode() instead"
            )
        asyncio.run(self.astart_socket_mode(app_token))
