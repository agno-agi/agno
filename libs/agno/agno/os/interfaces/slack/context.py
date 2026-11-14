import html
from dataclasses import dataclass, field, replace
from ssl import SSLContext
from typing import Any, Dict, List, Literal, Optional, Set

try:
    from slack_sdk.web.async_client import AsyncWebClient
except ImportError as e:
    raise ImportError("Slack dependencies not installed. Please install using `pip install 'agno[slack]'`") from e

from agno.os.interfaces.slack.helpers import (
    BotNameResolver,
    EventDeduplicator,
    LookupCache,
    extract_event_context,
    resolve_session_id,
    slack_run_id,
    strip_bot_mention,
)
from agno.os.interfaces.slack.runs import SlackRuns
from agno.os.interfaces.slack.security import resolve_signing_secret, resolve_token
from agno.team import RemoteTeam
from agno.utils.log import log_warning


@dataclass
class SlackContext:
    """Per-interface configuration and services, built once per Slack instance and shared by every request."""

    entity: Any
    entity_id: str
    entity_name: str
    entity_type: Literal["agent", "team", "workflow"]
    token: str
    signing_secret: str
    runs: SlackRuns
    ssl: Optional[SSLContext] = None
    reply_to_mentions_only: bool = True
    streaming: bool = True
    loading_messages: Optional[List[str]] = None
    task_display_mode: str = "plan"
    loading_text: str = "Thinking..."
    suggested_prompts: Optional[List[Dict[str, str]]] = None
    buffer_size: int = 100
    max_file_size: int = 1_073_741_824
    resolve_user_identity: bool = False
    respond_to_other_apps: bool = False
    markdown: bool = True
    unfurl_links: bool = True
    unfurl_media: bool = True
    approvers: Optional[List[str]] = None
    users: Optional[Dict[str, str]] = None
    company: Any = None
    lookup_cache: LookupCache = field(default_factory=LookupCache)
    bot_names: BotNameResolver = field(default_factory=BotNameResolver)
    dedupe: EventDeduplicator = field(default_factory=EventDeduplicator)
    failing: Set[str] = field(default_factory=set)
    bot_id: Optional[str] = None
    bot_user_id: Optional[str] = None
    bolt_app: Any = None
    app: Any = None

    def web(self) -> AsyncWebClient:
        """A client for Slack calls made outside a request (timers, Stop, delivery)."""
        return AsyncWebClient(token=self.token, ssl=self.ssl)

    def bind(self, app: Any) -> "SlackContext":
        return replace(self, app=app)

    @property
    def resource(self) -> str:
        return f"{self.entity_type}s"


def build_context(
    agent: Any = None,
    team: Any = None,
    workflow: Any = None,
    token: Optional[str] = None,
    signing_secret: Optional[str] = None,
    reply_to_mentions_only: bool = True,
    streaming: bool = True,
    loading_messages: Optional[List[str]] = None,
    task_display_mode: str = "plan",
    loading_text: str = "Thinking...",
    suggested_prompts: Optional[List[Dict[str, str]]] = None,
    ssl: Optional[SSLContext] = None,
    buffer_size: int = 100,
    max_file_size: int = 1_073_741_824,
    resolve_user_identity: bool = False,
    respond_to_other_apps: bool = False,
    markdown: bool = True,
    unfurl_links: bool = True,
    unfurl_media: bool = True,
    approvers: Optional[List[str]] = None,
    users: Optional[Dict[str, str]] = None,
) -> SlackContext:
    """Build the SlackContext from the Slack(...) arguments; see Slack.__init__ for each one.

    Raises when no agent, team or workflow is given, or the token or the signing secret is missing.
    """
    entity = agent or team or workflow
    if entity is None:
        raise ValueError("Slack requires an agent, team, or workflow")
    # entity_type drives event dispatch (agent vs team vs workflow events)
    entity_type: Literal["agent", "team", "workflow"] = "agent" if agent else "team" if team else "workflow"
    # Member HITL needs member runs embedded on Team run (member_responses).
    # Without this, continue_run cannot reliably reload member tool state from DB.
    if team is not None and not isinstance(team, RemoteTeam):
        team.store_member_responses = True
    raw_name = getattr(entity, "name", None)
    # entity_name labels task cards; entity_id namespaces session IDs
    entity_name = raw_name if isinstance(raw_name, str) else entity_type
    return SlackContext(
        entity=entity,
        entity_id=getattr(entity, "id", None) or entity_name,
        entity_name=entity_name,
        entity_type=entity_type,
        token=resolve_token(token),
        signing_secret=resolve_signing_secret(signing_secret),
        runs=SlackRuns(),
        ssl=ssl,
        reply_to_mentions_only=reply_to_mentions_only,
        streaming=streaming,
        loading_messages=loading_messages,
        task_display_mode=task_display_mode,
        loading_text=loading_text,
        suggested_prompts=suggested_prompts,
        buffer_size=buffer_size,
        max_file_size=max_file_size,
        resolve_user_identity=resolve_user_identity,
        respond_to_other_apps=respond_to_other_apps,
        markdown=markdown,
        unfurl_links=unfurl_links,
        unfurl_media=unfurl_media,
        approvers=approvers,
        users=users,
    )


@dataclass
class EventContext:
    """The Slack coordinates and owner of one run."""

    run_id: str
    session_id: str
    channel: str
    thread_ts: str
    message_ts: str
    # Slack user or bot id that sent the message
    owner: str
    # agno user id: mapped principal, email or Slack id
    user_id: str
    entity_id: str
    team_id: Optional[str] = None
    text: str = ""
    event: Dict[str, Any] = field(default_factory=dict)
    display_name: Optional[str] = None
    channel_name: Optional[str] = None
    action_token: Optional[str] = None
    authority: Any = None
    streaming_message_ts: List[str] = field(default_factory=list)
    stopped: bool = False


def new_event_context(body: Dict[str, Any], ctx: SlackContext) -> EventContext:
    """The event context of a message, built without awaiting so it can register at once."""
    event = body.get("event") or {}
    raw = extract_event_context(event)
    team_id = body.get("team_id") or event.get("team") or ""
    channel = raw["channel_id"]
    message_ts = event.get("ts", "")
    owner = raw["user"] or raw["bot_id"]
    return EventContext(
        run_id=slack_run_id(team_id, ctx.entity_id, channel, message_ts),
        session_id="",
        channel=channel,
        thread_ts=raw["thread_id"],
        message_ts=message_ts,
        owner=owner,
        user_id=owner,
        entity_id=ctx.entity_id,
        team_id=team_id or None,
        text=raw["message_text"],
        event=event,
        action_token=raw.get("action_token"),
    )


async def resolve_context(
    event_context: EventContext, body: Dict[str, Any], client: Any, ctx: SlackContext
) -> EventContext:
    """Fill the text, session, user identity and channel name of a registered event context."""
    event = event_context.event
    bot_user_id = (body.get("authorizations") or [{}])[0].get("user_id") or ctx.bot_user_id
    bot_name = await ctx.bot_names.resolve(client, bot_user_id) if bot_user_id else None
    # Slack escapes &, < and > in message text; identity comes from event["user"], never from the text
    event_context.text = html.unescape(strip_bot_mention(event_context.text, bot_user_id, bot_name))
    event_context.session_id = await resolve_session_id(
        ctx.entity, ctx.entity_id, event_context.channel, event_context.thread_ts, ctx.lookup_cache
    )

    sender_user = event.get("user") or ""
    sender_bot_id = event.get("bot_id") or ""
    if ctx.resolve_user_identity:
        # A user-token post carries both ids; the human is the sender, as for the run's owner
        if sender_user:
            event_context.user_id, event_context.display_name = await ctx.lookup_cache.user_identity(
                client, sender_user
            )
        elif sender_bot_id:
            event_context.user_id, event_context.display_name = await ctx.lookup_cache.bot_identity(
                client, sender_bot_id
            )
    else:
        # Only the name, for the agent's context: the run's user_id stays the Slack id or mapped principal
        event_context.display_name = await ctx.lookup_cache.sender_name(client, sender_user, sender_bot_id)

    # Direct messages have no channel name
    if event.get("channel_type") not in ("im", "mpim"):
        event_context.channel_name = await ctx.lookup_cache.channel_name(client, event_context.channel)
    return event_context


async def event_context_from_run(
    ctx: SlackContext,
    run_output: Any,
    *,
    owner: Optional[str] = None,
    client: Any = None,
    channel: Optional[str] = None,
    team_id: Optional[str] = None,
) -> EventContext:
    """An event context for a stored run with no parked one, e.g. after a restart.

    The owner is the Slack id written on the card, else the Slack user mapped to the run's user,
    else the Slack user whose email is the run's user.
    """
    session_id = getattr(run_output, "session_id", None) or ""
    user_id = getattr(run_output, "user_id", None) or ""
    # "{entity_id}:{channel}:{thread_ts}", or the legacy "{entity_id}:{thread_ts}"
    prefix = f"{ctx.entity_id}:"
    session_channel, _, thread_ts = session_id.removeprefix(prefix).rpartition(":")
    if not owner and user_id and ctx.users is not None:
        owner = next((slack_id for slack_id, principal in ctx.users.items() if principal == user_id), None)
    if not owner and "@" in user_id:
        try:
            response = await (client or ctx.web()).users_lookupByEmail(email=user_id)
            owner = (response.get("user") or {}).get("id")
        except Exception as e:
            log_warning(f"Failed to look up the Slack user of a run: {str(e)}")
    if not owner and ctx.users is None and not ctx.resolve_user_identity:
        # Without identity resolution the run's user is the Slack id itself
        owner = user_id
    return EventContext(
        run_id=getattr(run_output, "run_id", None) or "",
        session_id=session_id,
        channel=channel or session_channel,
        thread_ts=thread_ts,
        message_ts=thread_ts,
        owner=owner or "",
        user_id=user_id,
        entity_id=ctx.entity_id,
        team_id=team_id,
    )
