from ssl import SSLContext
from typing import Any, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.slack.config import SlackConfig
from agno.os.interfaces.slack.prompts import Prompt
from agno.os.interfaces.slack.sessions import SessionApi
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow


class Slack(BaseInterface):
    """Serve an Agent, Team, or Workflow in Slack."""

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
        self.config = SlackConfig(
            agent=agent,
            team=team,
            workflow=workflow,
            prefix=prefix,
            tags=tags or ["Slack"],
            reply_to_mentions_only=reply_to_mentions_only,
            token=token,
            signing_secret=signing_secret,
            streaming=streaming,
            loading_messages=loading_messages,
            task_display_mode=task_display_mode,
            loading_text=loading_text,
            suggested_prompts=suggested_prompts,
            ssl=ssl,
            buffer_size=buffer_size,
            max_file_size=max_file_size,
            resolve_user_identity=resolve_user_identity,
            respond_to_other_apps=respond_to_other_apps,
            markdown=markdown,
            unfurl_links=unfurl_links,
            unfurl_media=unfurl_media,
            session_api=session_api,
            stop_message=stop_message,
            onboarding_message=onboarding_message,
            per_user_thread_sessions=per_user_thread_sessions,
            db=db,
        )
        # AgentOS reads these to register the entity's database at startup
        self.agent = agent
        self.team = team
        self.workflow = workflow
        self.prefix = prefix
        self.tags = self.config.tags

    def get_router(self) -> APIRouter:
        from agno.os.interfaces.slack.app import mount_slack

        self.mount = mount_slack(APIRouter(prefix=self.prefix, tags=self.tags), self.config)  # type: ignore[arg-type]
        self.router = self.mount.router
        return self.router
