from dataclasses import fields
from ssl import SSLContext
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from fastapi.routing import APIRouter

from agno.agent import Agent, RemoteAgent
from agno.agent.protocol import AgentProtocol
from agno.os.interfaces.base import BaseInterface
from agno.os.interfaces.slack.context import SlackContext, build_context
from agno.os.interfaces.slack.executor import aclose_runs
from agno.os.interfaces.slack.router import attach_routes
from agno.team import RemoteTeam, Team
from agno.workflow import RemoteWorkflow, Workflow

if TYPE_CHECKING:
    from agno.os.interfaces.slack.company import TaskDelivery

# SlackContext fields that hold the interface's state rather than a Slack(...) setting
_RUNTIME_FIELDS = {
    "runs",
    "company",
    "lookup_cache",
    "bot_names",
    "dedupe",
    "failing",
    "bot_id",
    "bot_user_id",
    "bolt_app",
    "app",
}


class Slack(BaseInterface):
    type = "slack"

    # Verifies the Slack request signature (X-Slack-Signature) in its router, so it is
    # excluded from the central auth layer.
    authenticates_own_requests = True

    router: APIRouter

    def __init__(
        self,
        agent: Optional[Union[Agent, RemoteAgent, AgentProtocol]] = None,
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
        approvers: Optional[List[str]] = None,
        users: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the Slack interface.

        Args:
            agent: The agent to expose via Slack (may also be a Claude Code or Codex agent)
            team: The team to expose via Slack
            workflow: The workflow to expose via Slack
            prefix: Custom prefix for the router (e.g., "/slack/v1", defaults to "/slack")
            tags: Custom tags for the router (e.g., ["Slack", "Chat"], defaults to ["Slack"])
            reply_to_mentions_only: In channels, answer only messages that mention the bot; DMs are always answered
            token: The Slack bot token (defaults to SLACK_TOKEN)
            signing_secret: The Slack signing secret (defaults to SLACK_SIGNING_SECRET)
            streaming: Stream the reply as it is generated
            loading_messages: Rotating status texts shown while the run works
            task_display_mode: How tool calls show in a streamed reply, "plan" or "timeline"
            loading_text: Status text shown while the run starts, in the assistant view
            suggested_prompts: Prompts for new threads and the Messages tab (defaults to one "Get started" prompt)
            ssl: SSL context for Slack API calls and file downloads
            buffer_size: Characters buffered before a streamed update is flushed
            max_file_size: Largest attached file downloaded, in bytes
            resolve_user_identity: Use the sender's Slack email as the run's user_id
            respond_to_other_apps: Answer messages posted by other bots
            markdown: Format replies as Slack mrkdwn
            unfurl_links: Let Slack expand link previews in replies
            unfurl_media: Let Slack expand media previews in replies
            approvers: Slack member IDs (e.g., "U0123ABC") who may decide on or stop anyone's run; the owner always can
            users: Slack member ID to AgentOS principal; unmapped users are refused, and runs use the principal's access
        """
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
        self.approvers = approvers
        self.users = users

        if not (self.agent or self.team or self.workflow):
            raise ValueError("Slack requires an agent, team, or workflow")

        self.ctx: SlackContext = self._build_context()
        self._task_delivery: Optional["TaskDelivery"] = None

    @property
    def company(self) -> Any:
        return self.ctx.company

    @company.setter
    def company(self, company: Any) -> None:
        self.ctx.company = company

    def _build_context(self) -> SlackContext:
        return build_context(
            agent=self.agent,
            team=self.team,
            workflow=self.workflow,
            token=self.token,
            signing_secret=self.signing_secret,
            reply_to_mentions_only=self.reply_to_mentions_only,
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
            approvers=self.approvers,
            users=self.users,
        )

    def get_router(self, use_async: bool = True, **kwargs) -> APIRouter:
        # Settings are read when the router is built; the runs, caches and Bolt app are kept
        settings = self._build_context()
        # Bolt and the bot ids were built from the old credentials, so attach_routes rebuilds them
        if any(getattr(settings, name) != getattr(self.ctx, name) for name in ("token", "signing_secret", "ssl")):
            self.ctx.bolt_app = self.ctx.bot_id = self.ctx.bot_user_id = None
        for setting in fields(SlackContext):
            if setting.name not in _RUNTIME_FIELDS:
                setattr(self.ctx, setting.name, getattr(settings, setting.name))
        self.router = attach_routes(
            router=APIRouter(prefix=self.prefix, tags=self.tags),  # type: ignore
            context=self.ctx,
        )
        # Without AgentOS nothing else closes the interface
        self.router.add_event_handler("shutdown", self.aclose)

        return self.router

    async def astart(self) -> None:
        if self.ctx.company is None or not self.ctx.company.deliver or self._task_delivery is not None:
            return
        from agno.os.interfaces.slack.company import TaskDelivery

        self._task_delivery = TaskDelivery(self.ctx)
        await self._task_delivery.start()

    async def aclose(self) -> None:
        if self._task_delivery is not None:
            await self._task_delivery.stop()
            self._task_delivery = None
        await aclose_runs(self.ctx)
