"""Serve an Agent, Team, or Workflow in Slack.

Slack sends events and button clicks to two routes. Bolt verifies each request,
acknowledges it, and dispatches to a listener; the listeners hand off to
``SlackEventHandler`` (messages, lifecycle events) and ``HITLHandler`` (approval cards).
"""

import re
from os import getenv
from ssl import SSLContext
from typing import Any, Awaitable, Callable, List, Literal, Optional, Union

from fastapi import Request
from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.slack.sessions import SessionApi
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error
from agno.workflow import RemoteWorkflow, Workflow

try:
    from slack_bolt.adapter.fastapi.async_handler import AsyncSlackRequestHandler
    from slack_bolt.async_app import AsyncApp
    from slack_sdk.web.async_client import AsyncWebClient

    from agno.os.interfaces.slack.dedupe import EventDeduplicator, make_dedupe_middleware
    from agno.os.interfaces.slack.event_handler import Prompt, SlackEventHandler, make_web_client
    from agno.os.interfaces.slack.helpers import BotNameResolver
    from agno.os.interfaces.slack.hitl import HITLHandler
    from agno.os.interfaces.slack.ids import ACTION_CHECK_STATUS, ACTION_ROW_APPROVE, ACTION_ROW_REJECT, ACTION_SUBMIT
except ImportError as e:
    raise ImportError("Slack dependencies not installed. Please install using `pip install 'agno[slack]'`") from e

# Replaces Bolt's auth.test lookup of the bot identity (tests, multi-workspace installs)
AuthorizeFn = Callable[..., Awaitable[Any]]


class Slack(BaseInterface):
    type = "slack"

    # Bolt verifies the Slack request signature (X-Slack-Signature) inside the
    # mounted routes, so the interface is excluded from the central auth layer.
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
        suggested_prompts: Optional[List[Prompt]] = None,
        ssl: Optional[SSLContext] = None,
        buffer_size: int = 100,
        max_file_size: int = 1_073_741_824,  # 1GB
        resolve_user_identity: bool = False,
        respond_to_other_apps: bool = False,
        markdown: bool = True,
        unfurl_links: bool = True,
        unfurl_media: bool = True,
        session_api: SessionApi = "auto",
        stop_message: str = "Stopped.",
        onboarding_message: Optional[str] = None,
        per_user_thread_sessions: bool = False,
        db: Optional[Any] = None,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = tags or ["Slack"]
        self.reply_to_mentions_only = reply_to_mentions_only
        # Credentials fall back to the environment so single-app deployments need no arguments
        self.token = token if token is not None else getenv("SLACK_TOKEN")
        self.signing_secret = signing_secret if signing_secret is not None else getenv("SLACK_SIGNING_SECRET")
        self.streaming = streaming
        self.loading_messages = loading_messages
        self.task_display_mode = task_display_mode
        self.loading_text = loading_text
        # Prompts shown at the top of the Messages tab: plain strings, or {"title", "message"} dicts
        self.suggested_prompts = suggested_prompts
        self.ssl = ssl
        self.buffer_size = buffer_size
        self.max_file_size = max_file_size
        self.resolve_user_identity = resolve_user_identity
        self.respond_to_other_apps = respond_to_other_apps
        self.markdown = markdown
        self.unfurl_links = unfurl_links
        self.unfurl_media = unfurl_media
        # "auto" uses agents.sessions.* and falls back to the assistant API
        self.session_api = session_api
        # Posted in the thread when the user presses Slack's stop button
        self.stop_message = stop_message
        # Sent once per user the first time they open the Messages tab
        self.onboarding_message = onboarding_message
        # Key sessions per participant in a thread instead of per thread
        self.per_user_thread_sessions = per_user_thread_sessions
        # Database for onboarding markers; defaults to the entity's own database
        self.db = db

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Slack requires an agent, team, or workflow")

    # ------------------------------------------------------------------
    # Entity facts
    # ------------------------------------------------------------------

    @property
    def entity(self) -> Any:
        return self.agent or self.team or self.workflow

    @property
    def entity_type(self) -> Literal["agent", "team", "workflow"]:
        # entity_type drives event dispatch (agent vs team vs workflow events)
        if self.agent is not None:
            return "agent"
        if self.team is not None:
            return "team"
        return "workflow"

    @property
    def entity_name(self) -> str:
        # entity_name labels task cards; falls back to the kind when unnamed
        raw_name = getattr(self.entity, "name", None)
        return raw_name if isinstance(raw_name, str) and raw_name else self.entity_type

    @property
    def entity_id(self) -> str:
        # entity_id namespaces session IDs so two bots never share history
        return getattr(self.entity, "id", None) or self.entity_name

    @property
    def entity_description(self) -> Optional[str]:
        description = getattr(self.entity, "description", None)
        return description if isinstance(description, str) and description else None

    # ------------------------------------------------------------------
    # Mounting
    # ------------------------------------------------------------------

    def get_router(self) -> APIRouter:
        self.router = APIRouter(prefix=self.prefix, tags=self.tags)  # type: ignore[arg-type]
        self.attach(self.router)
        return self.router

    def attach(self, router: APIRouter, *, authorize: Optional[AuthorizeFn] = None) -> APIRouter:
        """Build the handlers and the Bolt app and add the two webhook routes to ``router``."""
        if not self.token:
            raise ValueError("Slack bot token is not set. Pass token=... or set SLACK_TOKEN")
        if not self.signing_secret:
            raise ValueError("Slack signing secret is not set. Pass signing_secret=... or set SLACK_SIGNING_SECRET")

        # Member HITL needs member runs embedded on the Team run (member_responses).
        # Without this, continue_run cannot reliably reload member tool state from DB.
        if self.team is not None and not isinstance(self.team, RemoteTeam):
            self.team.store_member_responses = True

        client = make_web_client(self.token, self.ssl)
        self.event_handler = SlackEventHandler(
            token=self.token,
            ssl=self.ssl,
            client=client,
            entity=self.entity,
            entity_id=self.entity_id,
            entity_name=self.entity_name,
            entity_type=self.entity_type,
            entity_description=self.entity_description,
            bot_name_resolver=BotNameResolver(),
            reply_to_mentions_only=self.reply_to_mentions_only,
            resolve_user_identity=self.resolve_user_identity,
            respond_to_other_apps=self.respond_to_other_apps,
            loading_text=self.loading_text,
            loading_messages=self.loading_messages,
            task_display_mode=self.task_display_mode,
            buffer_size=self.buffer_size,
            suggested_prompts=self.suggested_prompts,
            unfurl_links=self.unfurl_links,
            unfurl_media=self.unfurl_media,
            markdown=self.markdown,
            max_file_size=self.max_file_size,
            streaming=self.streaming,
            session_api=self.session_api,
            stop_message=self.stop_message,
            onboarding_message=self.onboarding_message,
            per_user_thread_sessions=self.per_user_thread_sessions,
            db=self.db if self.db is not None else getattr(self.entity, "db", None),
        )
        self.hitl = HITLHandler(
            token=self.token,
            ssl=self.ssl,
            entity=self.entity,
            entity_id=self.entity_id,
            entity_name=self.entity_name,
            entity_type=self.entity_type,
            task_display_mode=self.task_display_mode,
            buffer_size=self.buffer_size,
            unfurl_links=self.unfurl_links,
            unfurl_media=self.unfurl_media,
            markdown=self.markdown,
            client=client,
            sessions=self.event_handler.sessions,
            active_runs=self.event_handler.active_runs,
            per_user_thread_sessions=self.per_user_thread_sessions,
        )

        self.bolt_app = self._build_bolt_app(authorize)
        handler = AsyncSlackRequestHandler(self.bolt_app)

        # Multiple Slack instances can be mounted on one FastAPI app (e.g. /research
        # and /analyst). The prefix makes each operation_id unique to avoid collisions.
        op_suffix = router.prefix.strip("/").replace("/", "_") or "slack"

        @router.post(
            "/events",
            operation_id=f"slack_events_{op_suffix}",
            name="slack_events",
            description="Process incoming Slack events",
            responses={200: {"description": "Event accepted"}, 401: {"description": "Invalid Slack signature"}},
        )
        async def slack_events(request: Request) -> Any:
            return await handler.handle(request)

        @router.post(
            "/interactions",
            operation_id=f"slack_interactions_{op_suffix}",
            name="slack_interactions",
            description="Handle Slack interactive components (HITL buttons / form submit)",
            responses={200: {"description": "Interaction accepted"}, 401: {"description": "Invalid Slack signature"}},
        )
        async def slack_interactions(request: Request) -> Any:
            return await handler.handle(request)

        return router

    def _build_bolt_app(self, authorize: Optional[AuthorizeFn]) -> AsyncApp:
        # Bolt refuses a fixed token together with ``authorize``, so the two are exclusive
        kwargs: dict = {
            "signing_secret": self.signing_secret,
            "process_before_response": False,
            "request_verification_enabled": True,
            "ignoring_self_events_enabled": True,
            "url_verification_enabled": True,
            "ssl_check_enabled": True,
            "raise_error_for_unhandled_request": False,
        }
        if authorize is not None:
            kwargs["authorize"] = authorize
        else:
            kwargs["client"] = AsyncWebClient(token=self.token, ssl=self.ssl)

        app = AsyncApp(**kwargs)
        # Bolt processes retries; the dedupe keeps a retried event to one run per process
        self.dedupe = EventDeduplicator()
        app.use(make_dedupe_middleware(self.dedupe))

        events = self.event_handler
        hitl = self.hitl

        # Bolt injects arguments by name, so listener signatures stay explicit
        @app.event("assistant_thread_started")
        async def _on_thread_started(event: dict) -> None:
            await events.handle_thread_started(event)

        @app.event("app_mention")
        async def _on_app_mention(body: dict) -> None:
            await events.handle_message(body)

        @app.event("message")
        async def _on_message(body: dict) -> None:
            await events.handle_message(body)

        @app.event("app_home_opened")
        async def _on_home_opened(event: dict) -> None:
            await events.handle_home_opened(event)

        @app.event("agent_session_stopped")
        async def _on_session_stopped(event: dict) -> None:
            await events.handle_session_stopped(event)

        @app.event("agent_session_title_changed")
        async def _on_title_changed(event: dict) -> None:
            await events.handle_title_changed(event)

        @app.event("app_context_changed")
        async def _on_context_changed(event: dict) -> None:
            await events.handle_context_changed(event)

        @app.event("assistant_thread_context_changed")
        async def _on_assistant_context_changed(event: dict) -> None:
            await events.handle_context_changed(event)

        # Events without a handler still get a 200 so Slack does not retry them
        @app.event(re.compile(".*"))
        async def _on_other_event() -> None:
            return None

        @app.action(ACTION_ROW_APPROVE)
        async def _on_row_approve(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
            await ack()
            await hitl.handle_row_approve(body)

        @app.action(ACTION_ROW_REJECT)
        async def _on_row_reject(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
            await ack()
            await hitl.handle_row_reject(body)

        @app.action(ACTION_CHECK_STATUS)
        async def _on_check_status(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
            await ack()
            await hitl.handle_check_status(body)

        @app.action(ACTION_SUBMIT)
        async def _on_submit(ack: Callable[..., Awaitable[Any]], body: dict) -> None:
            await ack()
            await hitl.handle_submit(body)

        # Unknown action ids are acknowledged and ignored: another Slack app sharing the
        # endpoint, or a card from a newer build, must not produce an error for the user
        @app.action(re.compile(".*"))
        async def _on_other_action(ack: Callable[..., Awaitable[Any]]) -> None:
            await ack()

        @app.error
        async def _on_error(error: Exception) -> None:
            log_error(f"Slack listener error: {error}")

        return app
