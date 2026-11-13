from typing import Any, Dict

from agno.os.interfaces.slack import executor
from agno.os.interfaces.slack.context import EventContext, SlackContext, new_event_context, resolve_context
from agno.os.interfaces.slack.helpers import (
    DEFAULT_SUGGESTED_PROMPTS,
    extract_event_context,
    post_ephemeral,
    set_suggested_prompts,
    should_respond,
)
from agno.os.interfaces.slack.security import authorize_run
from agno.utils.log import log_debug, log_warning

_NOT_LINKED_MESSAGE = "Your Slack account is not linked to an account on this AgentOS."

# Subtypes that indicate lifecycle events, not user messages
_IGNORED_SUBTYPES = frozenset(
    {
        "message_changed",
        "message_deleted",
        "message_replied",
        "channel_join",
        "channel_leave",
        "channel_topic",
        "channel_purpose",
    }
)


def should_process(event: Dict[str, Any], ctx: SlackContext) -> bool:
    """Return True if event should be processed, False to skip."""
    raw = extract_event_context(event)
    subtype = event.get("subtype")
    is_bot = raw["bot_id"] or subtype == "bot_message"

    if subtype in _IGNORED_SUBTYPES:
        log_debug(f"Slack event skipped: ignored subtype {subtype}")
        return False

    # Skip own messages (bot_id for bot posts, user for as_user posts)
    if ctx.bot_id and raw["bot_id"] == ctx.bot_id:
        log_debug("Slack event skipped: own message")
        return False
    if ctx.bot_user_id and raw["user"] == ctx.bot_user_id:
        log_debug("Slack event skipped: own message")
        return False

    # Skip bot messages unless opted in; without the bot's own ids its replies look like another app's
    if is_bot and (not ctx.respond_to_other_apps or not (ctx.bot_id or ctx.bot_user_id)):
        log_debug("Slack event skipped: another app's message")
        return False

    return True


async def _authorize_event(event_context: EventContext, client: Any, ctx: SlackContext) -> bool:
    """Run a mapped user's message under their platform authority; an unmapped or refused user gets an ephemeral."""
    from agno.os.auth import _authorization_enforced

    # Super Agent under authorization needs a mapped user; the middleware may be added after get_app()
    if ctx.users is None and (ctx.company is None or not _authorization_enforced(ctx.app)):
        return True
    principal = ctx.users.get(event_context.owner) if ctx.users is not None else None
    if principal is None:
        await post_ephemeral(
            client, event_context.channel, event_context.owner, _NOT_LINKED_MESSAGE, event_context.thread_ts
        )
        return False
    if not await authorize_run(ctx, event_context, principal, client, event_context.owner, event_context.thread_ts):
        return False
    event_context.user_id = principal
    return True


async def handle_message(payload: Dict[str, Any], client: Any, ctx: SlackContext) -> None:
    event = payload.get("event") or {}
    if not should_process(event, ctx) or not should_respond(event, ctx.reply_to_mentions_only):
        return
    event_context = new_event_context(payload, ctx)
    # The same message is already being answered (app_mention + message, or a redelivery),
    # or was stopped before its other delivery arrived
    if ctx.runs.find_run(event_context.run_id) is not None or ctx.runs.was_stopped(event_context.run_id):
        return
    # Registered before the first await, so an early Stop finds the run
    ctx.runs.register(event_context)
    try:
        await resolve_context(event_context, payload, client, ctx)
        authorized = await _authorize_event(event_context, client, ctx)
    except BaseException:
        ctx.runs.unregister(event_context.run_id)
        raise
    if not authorized:
        ctx.runs.unregister(event_context.run_id)
        return
    await executor.run_event(event_context, client, ctx)


async def handle_app_home_opened(payload: Dict[str, Any], client: Any, ctx: SlackContext) -> None:
    event = payload.get("event") or {}
    # The agent view's Messages tab; a thread gets its prompts from assistant_thread_started
    if event.get("tab") != "messages" or event.get("thread_ts") or not event.get("channel"):
        return
    try:
        await client.assistant_threads_setSuggestedPrompts(
            channel_id=event["channel"], prompts=ctx.suggested_prompts or DEFAULT_SUGGESTED_PROMPTS
        )
    except Exception as e:
        # An assistant-view app gets not_agent_app here; warned once, not per open
        if "messages_tab_prompts" not in ctx.failing:
            log_warning(f"Failed to set Messages-tab suggested prompts: {str(e)}")
        ctx.failing.add("messages_tab_prompts")
        return
    ctx.failing.discard("messages_tab_prompts")


async def handle_assistant_thread_started(payload: Dict[str, Any], client: Any, ctx: SlackContext) -> None:
    thread = (payload.get("event") or {}).get("assistant_thread") or {}
    channel = thread.get("channel_id", "")
    thread_ts = thread.get("thread_ts", "")
    if not (channel and thread_ts):
        return
    # The first message of this thread is a reply under Slack's root, so mark the thread for its title
    ctx.runs.mark_thread_started(channel, thread_ts)
    await set_suggested_prompts(client, channel, thread_ts, ctx.suggested_prompts)


async def handle_session_stopped(payload: Dict[str, Any], client: Any, ctx: SlackContext) -> None:
    event = payload.get("event") or {}
    streaming_message_ts = event.get("streaming_message_ts") or []
    if isinstance(streaming_message_ts, str):
        streaming_message_ts = [streaming_message_ts]
    await executor.stop_runs(
        ctx,
        client,
        event.get("user", ""),
        event.get("channel", ""),
        event.get("thread_ts", ""),
        streaming_message_ts,
    )
