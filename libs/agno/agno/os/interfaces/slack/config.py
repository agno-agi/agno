from __future__ import annotations

from dataclasses import dataclass, field
from os import getenv
from ssl import SSLContext
from typing import Any, List, Literal, Optional, Union

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.slack.prompts import Prompt
from agno.os.interfaces.slack.sessions import SessionApi
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow

EntityType = Literal["agent", "team", "workflow"]


@dataclass
class SlackConfig:
    """Every option the Slack interface accepts, resolved once at mount time.

    Credentials fall back to the ``SLACK_TOKEN`` and ``SLACK_SIGNING_SECRET``
    environment variables so single-app deployments need no constructor arguments.
    """

    agent: Optional[Union[Agent, RemoteAgent]] = None
    team: Optional[Union[Team, RemoteTeam]] = None
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None
    prefix: str = "/slack"
    tags: List[str] = field(default_factory=lambda: ["Slack"])
    reply_to_mentions_only: bool = True
    token: Optional[str] = None
    signing_secret: Optional[str] = None
    streaming: bool = True
    loading_messages: Optional[List[str]] = None
    task_display_mode: str = "plan"
    loading_text: str = "Thinking..."
    # Prompts shown at the top of the Messages tab: plain strings, or {"title", "message"} dicts
    suggested_prompts: Optional[List[Prompt]] = None
    ssl: Optional[SSLContext] = None
    buffer_size: int = 100
    max_file_size: int = 1_073_741_824  # 1GB
    resolve_user_identity: bool = False
    respond_to_other_apps: bool = False
    markdown: bool = True
    unfurl_links: bool = True
    unfurl_media: bool = True
    # Agent messaging: "auto" uses agents.sessions.* and falls back to the assistant API
    session_api: SessionApi = "auto"
    # Posted in the thread when the user presses Slack's stop button
    stop_message: str = "Stopped."
    # Sent once per user the first time they open the Messages tab
    onboarding_message: Optional[str] = None
    # Key sessions per participant in a thread instead of per thread
    per_user_thread_sessions: bool = False
    # Database for onboarding markers. Defaults to the entity's own database.
    db: Optional[Any] = None

    def __post_init__(self) -> None:
        if not (self.agent or self.team or self.workflow):
            raise ValueError("Slack requires an agent, team, or workflow")

    @property
    def entity(self) -> Any:
        return self.agent or self.team or self.workflow

    @property
    def entity_type(self) -> EntityType:
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

    def resolved_db(self) -> Optional[Any]:
        return self.db if self.db is not None else getattr(self.entity, "db", None)

    def resolved_token(self) -> str:
        token = self.token if self.token is not None else getenv("SLACK_TOKEN")
        if not token:
            raise ValueError("Slack bot token is not set. Pass token=... or set SLACK_TOKEN")
        return token

    def resolved_signing_secret(self) -> str:
        secret = self.signing_secret if self.signing_secret is not None else getenv("SLACK_SIGNING_SECRET")
        if not secret:
            raise ValueError("Slack signing secret is not set. Pass signing_secret=... or set SLACK_SIGNING_SECRET")
        return secret
