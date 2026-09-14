"""Serve an Agent, Team, or Workflow in Slack.

``Slack(...)`` holds the options and builds the handlers; ``router.py`` builds the
Bolt app that verifies and dispatches Slack's requests to them.
"""

from os import getenv
from ssl import SSLContext
from typing import Any, List, Literal, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow

try:
    from agno.os.interfaces.slack.handler import Prompt, SlackEventHandler, make_web_client
    from agno.os.interfaces.slack.hitl import HITLHandler
    from agno.os.interfaces.slack.router import AuthorizeFn, EventDeduplicator, attach_routes, build_bolt_app
    from agno.os.interfaces.slack.utils import SlackSessions, Threads
except ImportError as e:
    raise ImportError("Slack dependencies not installed. Please install using `pip install 'agno[slack]'`") from e


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
        stop_message: str = "Stopped.",
        onboarding_message: Optional[str] = None,
        per_user_thread_sessions: bool = False,
        db: Optional[Any] = None,
    ):
        self.agent = agent
        self.team = team
        self.workflow = workflow
        if not (self.agent or self.team or self.workflow):
            raise ValueError("Slack requires an agent, team, or workflow")
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
        # Posted in the thread when the user presses Slack's stop button
        self.stop_message = stop_message
        # Sent once per user the first time they open the Messages tab
        self.onboarding_message = onboarding_message
        # Key sessions per participant in a thread instead of per thread
        self.per_user_thread_sessions = per_user_thread_sessions
        # Database for onboarding markers; defaults to the entity's own database
        self.db = db

    # ------------------------------------------------------------------
    # Entity facts
    # ------------------------------------------------------------------

    @property
    def entity(self) -> Any:
        return self.agent or self.team or self.workflow

    @property
    def entity_type(self) -> Literal["agent", "team", "workflow"]:
        # Drives event dispatch (agent vs team vs workflow events)
        if self.agent is not None:
            return "agent"
        if self.team is not None:
            return "team"
        return "workflow"

    @property
    def entity_name(self) -> str:
        # Labels task cards; falls back to the kind when unnamed
        raw_name = getattr(self.entity, "name", None)
        return raw_name if isinstance(raw_name, str) and raw_name else self.entity_type

    @property
    def entity_id(self) -> str:
        # Namespaces session IDs so two bots never share history
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
        self.sessions = SlackSessions(client, loading_messages=self.loading_messages)
        self.threads = Threads()
        self.event_handler = SlackEventHandler(self, client, sessions=self.sessions, threads=self.threads)
        self.hitl = HITLHandler(self, client, sessions=self.sessions, threads=self.threads)
        self.dedupe = EventDeduplicator()
        self.bolt_app = build_bolt_app(self, authorize)
        return attach_routes(router, self.bolt_app)
