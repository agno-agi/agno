from __future__ import annotations

import asyncio
import contextlib
import html
import time
from functools import partial
from typing import TYPE_CHECKING, Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional, Set

from fastapi import HTTPException

from agno.agent import Agent, RemoteAgent, RunEvent
from agno.agents._hitl import (
    awaiting_decision,
    db_call,
    hitl_state,
    live_native_run,
    pending_ids,
    read_run,
    tail_stored,
)
from agno.agents.base import BaseExternalAgent
from agno.db.base import AsyncBaseDb, BaseDb
from agno.exceptions import InputCheckError, SessionBusyError
from agno.os.interfaces.slack.events import STOPPED_TEXT, WORKFLOW_PAUSED_TEXT, _normalize_event, process_event
from agno.os.interfaces.slack.helpers import (
    build_run_metadata,
    clear_status,
    delete_awaiting_indicator,
    download_event_files_async,
    post_ephemeral,
    run_error_reply,
    send_slack_message_async,
    set_title,
    slack_delivery_kwargs,
    start_status,
    strip_bot_mention,
    update_message,
    upload_response_media_async,
)
from agno.os.interfaces.slack.pause import finalize_pause, pause_labels, post_pause_card
from agno.os.interfaces.slack.security import can_act
from agno.os.interfaces.slack.state import StreamState
from agno.os.interfaces.slack.stream import SlackStream, StreamStopped
from agno.os.interfaces.slack.types import tool_args, tool_name, truncate
from agno.os.job_queue import araise_if_ticket_owns_continue, get_active_queue_worker
from agno.os.services.runs import cancel_component_run
from agno.os.utils import (
    acomplete_continue_stream,
    adeliver_native_decisions,
    await_stored_run,
    queued_run_tail_streamer,
)
from agno.run.authorization import authorization_scope
from agno.run.background import (
    TERMINAL_RUN_EVENT_TYPES,
    map_background_stream_to_run_events,
    terminal_run_event_from_run_output,
)
from agno.run.base import RunStatus
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error
from agno.workflow import RemoteWorkflow, Workflow

if TYPE_CHECKING:
    from agno.os.interfaces.slack.context import EventContext, SlackContext
    from agno.run.requirement import RunRequirement

_ERROR_MESSAGE = "Sorry, there was an error processing your message."
_BUSY_MESSAGE = "Still working on an earlier message in this thread. Send yours again when I reply."
_UNSUPPORTED_FILES_MESSAGE = "This agent can't read that kind of file, such as audio or video; send the text instead."
_SANDBOX_FILES_MESSAGE = "This agent can't take these files ({error}); send fewer or smaller files or the text instead."
_AWAITING_DECISION_MESSAGE = "Waiting for a decision on the approval above. Approve or deny it, then send yours again."
_CANNOT_STOP_MESSAGE = "This agent cannot be stopped."
_NOT_OWNER_STOP_MESSAGE = "Only <@{owner}> can stop this."
_STOPPED_NOTE = "Stopped by user"
APPROVAL_NOT_RECORDED_MESSAGE = "Could not record the decision. Please try again."
NO_LONGER_ACTIVE_MESSAGE = "This approval is no longer active."

# Before a native continuation's own RunContinued, a replay of its first leg shows only these events
_FIRST_LEG_EVENTS = frozenset(
    {RunEvent.run_content.value, RunEvent.run_intermediate_content.value, RunEvent.run_paused.value}
)

_REMOTE_TYPES = (RemoteAgent, RemoteTeam, RemoteWorkflow)

# A stored run in one of these states answered its message, or is answering it elsewhere
_HANDLED_STATUSES = frozenset({RunStatus.completed.value, RunStatus.cancelled.value, RunStatus.running.value})


class DecisionRefused(Exception):
    """A decision was not accepted, so nothing ran and the card stays live; its message, if any, asks to retry."""

    pass


def _slack_dependencies(event_context: "EventContext") -> Dict[str, Any]:
    dependencies: Dict[str, Any] = {
        "Slack channel": f"#{event_context.channel_name}" if event_context.channel_name else event_context.channel,
        "Slack channel_id": event_context.channel,
        "Slack thread_ts": event_context.thread_ts,
    }
    # The sender's id lets the agent mention them (<@id>); the name is their own profile text, not proof of identity
    if event_context.display_name:
        dependencies["Slack user"] = event_context.display_name
    # Only a human sender can be mentioned; a bot sender's id is left out
    if event_context.event.get("user"):
        dependencies["Slack user_id"] = event_context.owner
    return dependencies


def _run_kwargs(event_context: "EventContext", ctx: "SlackContext", media: tuple) -> Dict[str, Any]:
    files, images, videos, audio = media
    sandboxed = isinstance(ctx.entity, BaseExternalAgent) and ctx.entity.sandbox is not None
    kwargs: Dict[str, Any] = {
        "user_id": event_context.user_id,
        "session_id": event_context.session_id,
        "metadata": build_run_metadata(
            event_context.display_name,
            event_context.user_id,
            {
                "channel_id": event_context.channel,
                "thread_id": event_context.thread_ts,
                "user": event_context.owner,
                "message_text": event_context.text,
                # A sandbox request carries run metadata, which agent code inside the sandbox could read
                "action_token": None if sandboxed else event_context.action_token,
                "message_ts": event_context.message_ts,
            },
        ),
        "dependencies": _slack_dependencies(event_context),
        "add_dependencies_to_context": True,
        "files": files or None,
        "images": images or None,
        "videos": videos or None,
        "audio": audio or None,
    }
    # A remote run gets its id from the remote AgentOS; the event context is re-keyed from its first event
    if not isinstance(ctx.entity, _REMOTE_TYPES):
        kwargs["run_id"] = event_context.run_id
    return kwargs


def _start_run(event_context: "EventContext", ctx: "SlackContext", message_text: str, kwargs: Dict[str, Any]) -> Any:
    """Start the entity's run: a background run for native approvals, else an ordinary one."""
    entity = ctx.entity
    if getattr(entity, "_uses_native_hitl", False):
        # A native permission request outlives a Slack request, so the run is stored and resumable
        kwargs.update(stream=True, stream_events=True, background=True, run_id=event_context.run_id)
        events = entity.arun(message_text, **kwargs)
        return _follow_stored(
            map_background_stream_to_run_events(
                events, entity, run_id=event_context.run_id, session_id=event_context.session_id
            ),
            ctx,
            event_context,
        )
    return entity.arun(message_text, **kwargs)


def _is_terminal(event: Any, run_id: str) -> bool:
    return getattr(event, "run_id", None) == run_id and isinstance(event, TERMINAL_RUN_EVENT_TYPES)


async def _stored_outcome(ctx: "SlackContext", event_context: "EventContext") -> Any:
    """The event for how a native run ended, read from its stored run once it completes, pauses or fails."""
    entity = ctx.entity
    run = await await_stored_run(
        partial(read_run, entity, event_context.run_id, event_context.session_id, event_context.user_id),
        event_context.run_id,
        entity.hitl_timeout,
        getattr(entity.sandbox, "execution_timeout", None),
    )
    if run is None:
        raise ValueError("Native run is no longer available")
    return terminal_run_event_from_run_output(run)


async def _follow_stored(events: Any, ctx: "SlackContext", event_context: "EventContext") -> AsyncIterator[Any]:
    """A native run's events; a stream cut short by stream_expired or error ends with its stored outcome."""
    finished = False
    async for event in events:
        finished = finished or _is_terminal(event, event_context.run_id)
        yield event
    if not finished:
        yield await _stored_outcome(ctx, event_context)


async def _already_handled(ctx: "SlackContext", run_id: str) -> bool:
    """Whether this message's run already ran, so a redelivery or a stopped message is not run again."""
    entity = ctx.entity
    db = getattr(entity, "db", None)
    if not isinstance(entity, (Agent, Team, Workflow, BaseExternalAgent)) or not isinstance(db, (BaseDb, AsyncBaseDb)):
        return False
    try:
        saved = await db_call(db, "get_run", run_id, deserialize=False)
    except Exception:
        # A failed read is "not saved": answering twice beats dropping the message
        return False
    if saved is None:
        return False
    status = saved.get("status") if isinstance(saved, dict) else getattr(saved, "status", None)
    return str(getattr(status, "value", status)) in _HANDLED_STATUSES


async def _reply(client: Any, ctx: "SlackContext", event_context: "EventContext", message: str) -> None:
    await send_slack_message_async(
        client,
        channel=event_context.channel,
        thread_ts=event_context.thread_ts,
        message=message,
        unfurl_links=ctx.unfurl_links,
        unfurl_media=ctx.unfurl_media,
        mrkdwn=ctx.markdown,
    )


async def _blocking_run(ctx: "SlackContext", event_context: "EventContext", error: SessionBusyError) -> Any:
    """The stored run that keeps the session busy, or None when it cannot be read."""
    if not error.run_id or not hasattr(ctx.entity, "aget_run_output"):
        return None
    try:
        return await ctx.entity.aget_run_output(run_id=error.run_id, session_id=event_context.session_id)
    except Exception:
        return None


async def _busy_message(ctx: "SlackContext", event_context: "EventContext", error: SessionBusyError) -> str:
    """Return the reply for a busy session; a run paused on an approval card says so."""
    if getattr(await _blocking_run(ctx, event_context, error), "status", None) == RunStatus.paused:
        return _AWAITING_DECISION_MESSAGE
    return _BUSY_MESSAGE


async def _cancel_expired_pause(ctx: "SlackContext", event_context: "EventContext", error: SessionBusyError) -> bool:
    """Cancel the busy session's native run when every request it waits on expired, e.g. across a restart."""
    if not getattr(ctx.entity, "_uses_native_hitl", False):
        return False
    return await cancel_expired_pause(ctx, await _blocking_run(ctx, event_context, error))


async def cancel_expired_pause(ctx: "SlackContext", run: Any) -> bool:
    """Cancel a native run paused on requests that all expired; True when it was cancelled."""
    if not getattr(ctx.entity, "_uses_native_hitl", False) or not awaiting_decision(run):
        return False
    requests = hitl_state(run).get("requests") or {}
    # An expired request can no longer be answered, so its run would keep the session busy forever
    if not all(
        (requests.get(tool_call_id) or {}).get("expires_at", 0) <= time.time() for tool_call_id in pending_ids(run)
    ):
        return False
    await _cancel_run(ctx, run.run_id)
    return True


async def _cancel_run(ctx: "SlackContext", run_id: str) -> None:
    try:
        await cancel_component_run(ctx.entity, run_id)
    except Exception as e:
        log_error(f"Failed to cancel run {run_id}: {str(e)}")


async def _rekey_remote(ctx: "SlackContext", event_context: "EventContext", run_id: str) -> None:
    stopped_before = event_context.stopped and event_context.run_id != run_id
    ctx.runs.rekey(event_context.run_id, run_id)
    # A Stop that came before the remote run named its id cancelled nothing there
    if stopped_before:
        await _cancel_run(ctx, run_id)


async def _render(
    events: Any,
    event_context: "EventContext",
    client: Any,
    ctx: "SlackContext",
    state: StreamState,
    stream: SlackStream,
    *,
    set_thread_title: bool,
) -> None:
    """Render a run's events into the stream until its terminal event, then drain the rest unrendered."""
    first = True
    async for chunk in events:
        if first:
            first = False
            chunk_run_id = getattr(chunk, "run_id", None)
            if isinstance(ctx.entity, _REMOTE_TYPES) and isinstance(chunk_run_id, str):
                await _rekey_remote(ctx, event_context, chunk_run_id)
        ev = getattr(chunk, "event", None)
        if event_context.stopped:
            # Nothing renders after a Stop, but a pause that beat the cancel must still be resolved
            if _normalize_event(str(ev or "")) == RunEvent.run_paused.value:
                state.paused_event = chunk
                state.terminal_status = "paused"
            continue
        state.collect_media(chunk)
        try:
            terminal = await process_event(ev, chunk, state, stream) if ev else False
            if state.has_content():
                # Titles exist only in direct messages
                if set_thread_title and event_context.event.get("channel_type") == "im":
                    set_thread_title = False
                    # Only the first message of a thread names it, so a title the user changed is kept
                    if event_context.message_ts == event_context.thread_ts or ctx.runs.take_thread_started(
                        event_context.channel, event_context.thread_ts
                    ):
                        # The title is the message without the bot's mention, not with the bot's name in its place
                        title = html.unescape(strip_bot_mention(event_context.event.get("text", ""), ctx.bot_user_id))
                        await set_title(client, event_context.channel, event_context.thread_ts, title)
                await stream.append(markdown_text=state.flush())
        except StreamStopped:
            # The user stopped the reply in Slack, possibly on another worker: stop the run, post nothing
            event_context.stopped = True
            await _cancel_run(ctx, event_context.run_id)
            continue
        if terminal:
            ctx.runs.mark_finished(event_context.run_id)
            # Drain without rendering so the run's cleanup after its terminal event still runs
            async for _ in events:
                pass
            return


async def _finish(
    event_context: "EventContext", client: Any, ctx: "SlackContext", state: StreamState, stream: SlackStream
) -> bool:
    """End a streamed reply by how the run ended; returns True when the run paused on a card."""
    paused = state.paused_event
    requirements = list(getattr(paused, "active_requirements", None) or [])
    if event_context.stopped:
        # A Stop handled here already ended the stream and the status
        handled = stream.closed
        # Slack takes no appends after a Stop and renders its own notice; open cards close as complete, not failed
        await stream.stop(chunks=state.resolve_all_pending("complete", suffix="stopped") or None)
        if state.terminal_status == "paused" and requirements:
            # The run paused before the cancel reached it; resolve the pause so it does not wait without a card
            ctx.runs.park_paused(event_context)
            await cancel_paused(event_context, client, ctx)
        elif not handled and not stream.ended:
            await clear_status(client, event_context.channel, event_context.thread_ts)
        return False

    if state.terminal_status == "paused" and getattr(paused, "run_id", None) and requirements:
        awaiting_ts = await finalize_pause(
            client=client,
            stream=stream,
            state=state,
            run_id=event_context.run_id,
            channel=event_context.channel,
            thread_ts=event_context.thread_ts,
            requirements=requirements,
            unfurl_links=ctx.unfurl_links,
            unfurl_media=ctx.unfurl_media,
            mrkdwn=ctx.markdown,
        )
        card_ts = await post_pause_card(
            client,
            paused,
            event_context.channel,
            event_context.thread_ts,
            awaiting_ts,
            owner=event_context.owner,
            unfurl_links=ctx.unfurl_links,
            unfurl_media=ctx.unfurl_media,
            mrkdwn=ctx.markdown,
        )
        if not stream.ended:
            await clear_status(client, event_context.channel, event_context.thread_ts)
        ctx.runs.park_paused(event_context, card_ts=card_ts, awaiting_ts=awaiting_ts)
        return True

    draft = state.take_intermediate()
    if draft:
        state.append_content(draft)
    await stream.stop(
        markdown_text=state.flush() if state.has_content() else None,
        chunks=state.resolve_all_pending(state.card_status()) or None,
    )
    if not stream.ended or state.terminal_status == "workflow_paused":
        await clear_status(client, event_context.channel, event_context.thread_ts)
    if state.terminal_status != "cancelled":
        await upload_response_media_async(client, state, event_context.channel, event_context.thread_ts)
    return False


async def _fail(
    error: BaseException,
    event_context: "EventContext",
    client: Any,
    ctx: "SlackContext",
    state: StreamState,
    stream: Optional[SlackStream],
) -> None:
    log_error(
        f"Error streaming slack response [channel={event_context.channel}, thread={event_context.thread_ts}, "
        f"user={event_context.owner}]: {error}"
    )
    if stream is not None:
        try:
            await stream.stop(chunks=state.resolve_all_pending("error") or None)
        except Exception:
            pass
        if stream.ended:
            # A terminal error event already shows in the stream, e.g. a workflow that raises after its error event
            if state.terminal_status != "error":
                await _reply(
                    client, ctx, event_context, run_error_reply(error, _ERROR_MESSAGE, _UNSUPPORTED_FILES_MESSAGE)
                )
            return
    await reply_error(error, event_context, client, ctx)


async def reply_error(error: BaseException, event_context: "EventContext", client: Any, ctx: "SlackContext") -> None:
    """End the status and post the error reply for a failure with no stream to stop."""
    await clear_status(client, event_context.channel, event_context.thread_ts)
    try:
        await _reply(client, ctx, event_context, run_error_reply(error, _ERROR_MESSAGE, _UNSUPPORTED_FILES_MESSAGE))
    except Exception as e:
        log_error(f"Failed to post Slack error reply: {str(e)}")


async def run_event(event_context: "EventContext", client: Any, ctx: "SlackContext") -> None:
    """Run the entity for one Slack message and render the reply."""
    parked = False
    try:
        if event_context.stopped or await _already_handled(ctx, event_context.run_id):
            return
        scope = (
            authorization_scope(lambda: event_context.authority)
            if event_context.authority is not None
            else contextlib.nullcontext()
        )
        with scope:
            # A message with no user (a bot's own post) in a channel has no human recipient, which a stream needs
            if ctx.streaming and (event_context.event.get("user") or event_context.event.get("channel_type") == "im"):
                parked = await _run_streaming(event_context, client, ctx)
            else:
                parked = await _run_non_streaming(event_context, client, ctx)
    finally:
        if not parked:
            ctx.runs.unregister(event_context.run_id)


async def _prepare(event_context: "EventContext", ctx: "SlackContext") -> tuple:
    files, images, videos, audio, skipped = await download_event_files_async(
        ctx.token, event_context.event, ctx.max_file_size, ctx.ssl
    )
    message_text = event_context.text
    if skipped:
        message_text = f"[Skipped files: {', '.join(skipped)}]\n{message_text}"
    run_kwargs = _run_kwargs(event_context, ctx, (files, images, videos, audio))
    entity = ctx.entity
    if isinstance(entity, BaseExternalAgent) and entity.sandbox is not None:
        from agno.sandbox.media import encode_media

        try:
            encode_media(images=images, files=files)
        except ValueError as error:
            raise InputCheckError(_SANDBOX_FILES_MESSAGE.format(error=error)) from error
    return message_text, run_kwargs


async def _run_streaming(
    event_context: "EventContext", client: Any, ctx: "SlackContext", retried: bool = False
) -> bool:
    state = StreamState(entity_type=ctx.entity_type, entity_name=ctx.entity_name)
    stream: Optional[SlackStream] = None
    await start_status(client, event_context.channel, event_context.thread_ts, ctx.loading_text, ctx.loading_messages)
    try:
        message_text, run_kwargs = await _prepare(event_context, ctx)
        run_kwargs.update(stream=True, stream_events=True)
        if event_context.stopped:
            await clear_status(client, event_context.channel, event_context.thread_ts)
            return False
        stream = SlackStream(client, event_context, ctx)
        ctx.runs.set_stream(event_context.run_id, stream)
        ctx.runs.mark_started(event_context.run_id)
        events = _start_run(event_context, ctx, message_text, run_kwargs)
        await _render(events, event_context, client, ctx, state, stream, set_thread_title=True)
        return await _finish(event_context, client, ctx, state, stream)
    except SessionBusyError as e:
        # A native approval that expired unanswered is cancelled, and the message runs once more
        if not retried and await _cancel_expired_pause(ctx, event_context, e):
            return await _run_streaming(event_context, client, ctx, retried=True)
        await clear_status(client, event_context.channel, event_context.thread_ts)
        await _reply(client, ctx, event_context, await _busy_message(ctx, event_context, e))
        return False
    except asyncio.CancelledError:
        if stream is not None:
            with contextlib.suppress(Exception):
                await stream.stop(
                    markdown_text=f"\n{STOPPED_TEXT}",
                    chunks=state.resolve_all_pending("complete", suffix="stopped") or None,
                )
        if stream is None or not stream.ended:
            await clear_status(client, event_context.channel, event_context.thread_ts)
        raise
    except Exception as e:
        await _fail(e, event_context, client, ctx, state, stream)
        return False
    finally:
        if stream is not None:
            stream.close()


async def _run_non_streaming(
    event_context: "EventContext", client: Any, ctx: "SlackContext", retried: bool = False
) -> bool:
    await start_status(client, event_context.channel, event_context.thread_ts, ctx.loading_text, ctx.loading_messages)
    status_cleared = False
    try:
        message_text, run_kwargs = await _prepare(event_context, ctx)
        if event_context.stopped:
            return False
        ctx.runs.mark_started(event_context.run_id)
        if getattr(ctx.entity, "_uses_native_hitl", False):
            async for _ in _start_run(event_context, ctx, message_text, run_kwargs):
                pass
            response = await ctx.entity.aget_run_output(
                run_id=event_context.run_id, session_id=event_context.session_id
            )
        else:
            response = await _start_run(event_context, ctx, message_text, run_kwargs)
        ctx.runs.mark_finished(event_context.run_id)
        if not response:
            return False
        if isinstance(ctx.entity, _REMOTE_TYPES) and isinstance(getattr(response, "run_id", None), str):
            await _rekey_remote(ctx, event_context, response.run_id)
        if event_context.stopped:
            if response.status == RunStatus.paused and getattr(response, "active_requirements", None):
                # The run paused before the cancel reached it; resolve the pause so it does not wait without a card
                ctx.runs.park_paused(event_context)
                await cancel_paused(event_context, client, ctx)
                status_cleared = True
            else:
                await _reply(client, ctx, event_context, STOPPED_TEXT)
            return False
        return await _post_response(event_context, client, ctx, response)
    except SessionBusyError as e:
        # A native approval that expired unanswered is cancelled, and the message runs once more
        if not retried and await _cancel_expired_pause(ctx, event_context, e):
            return await _run_non_streaming(event_context, client, ctx, retried=True)
        await _reply(client, ctx, event_context, await _busy_message(ctx, event_context, e))
        return False
    except Exception as e:
        log_error(f"Error processing slack event: {str(e)}")
        await _reply(client, ctx, event_context, run_error_reply(e, _ERROR_MESSAGE, _UNSUPPORTED_FILES_MESSAGE))
        return False
    finally:
        # No stopStream ends a non-streamed reply's status
        if not status_cleared:
            await clear_status(client, event_context.channel, event_context.thread_ts)


async def _post_response(event_context: "EventContext", client: Any, ctx: "SlackContext", response: Any) -> bool:
    status = response.status
    if status == RunStatus.error:
        log_error(f"Error processing message: {response.content}")
        await _reply(client, ctx, event_context, f"{_ERROR_MESSAGE} Please try again later.")
        return False
    if status == RunStatus.cancelled:
        await _reply(client, ctx, event_context, STOPPED_TEXT)
        return False

    content = str(response.content) if response.content else ""
    requirements = list(getattr(response, "active_requirements", None) or []) if status == RunStatus.paused else []
    if requirements and response.run_id:
        await _reply(client, ctx, event_context, content)
        awaiting_ts = None
        try:
            awaiting = await client.chat_postMessage(
                channel=event_context.channel,
                thread_ts=event_context.thread_ts,
                text="\n".join(pause_labels(requirements)),
                **slack_delivery_kwargs(ctx.unfurl_links, ctx.unfurl_media, ctx.markdown),
            )
            awaiting_ts = awaiting.get("ts")
        except Exception as exc:
            log_error(f"[HITL] Non-streaming awaiting indicator failed: {exc}")
        card_ts = await post_pause_card(
            client,
            response,
            event_context.channel,
            event_context.thread_ts,
            awaiting_ts,
            owner=event_context.owner,
            unfurl_links=ctx.unfurl_links,
            unfurl_media=ctx.unfurl_media,
            mrkdwn=ctx.markdown,
        )
        ctx.runs.park_paused(event_context, card_ts=card_ts, awaiting_ts=awaiting_ts)
        return True
    if status == RunStatus.paused:
        # A paused workflow has no Slack card
        await _reply(client, ctx, event_context, f"{content}\n\n{WORKFLOW_PAUSED_TEXT}".strip())
        return False

    if getattr(response, "reasoning_content", None):
        rc = str(response.reasoning_content)
        await _reply(client, ctx, event_context, "*Reasoning:*\n> " + rc.replace("\n", "\n> "))
    await _reply(client, ctx, event_context, content)
    await upload_response_media_async(client, response, event_context.channel, event_context.thread_ts)
    return False


async def _native_events(
    ctx: "SlackContext", event_context: "EventContext", submitted: Any, tail_from: Optional[int], answered: Set[str]
) -> AsyncIterator[Any]:
    """Follow a native run after its decision was delivered, without replaying what the thread already shows."""
    entity = ctx.entity
    if tail_from is not None:
        source = map_background_stream_to_run_events(
            queued_run_tail_streamer(event_context.run_id, from_index=tail_from),
            entity,
            run_id=event_context.run_id,
            session_id=event_context.session_id,
        )
    else:
        source = tail_stored(
            entity,
            event_context.run_id,
            event_context.session_id,
            event_context.user_id,
            len(submitted.events or []),
            answered,
        )
    continued = False
    finished = False
    async for event in source:
        name = _normalize_event(str(getattr(event, "event", "") or ""))
        if name == RunEvent.run_continued.value and (
            not answered or getattr(event, "external_agent_request_id", None) in answered
        ):
            continued = True
        # A stored run replays its first leg first; its text and its old pause card are already in the thread
        if not continued and name in _FIRST_LEG_EVENTS:
            continue
        finished = finished or _is_terminal(event, event_context.run_id)
        yield event
    if tail_from is not None and not finished:
        yield await _stored_outcome(ctx, event_context)


async def _post_denial_cards(
    stream: SlackStream, state: StreamState, decisions: Optional[List[Any]], requirements: List["RunRequirement"]
) -> None:
    requirements_by_id = {r.id: r for r in requirements if r.id}
    for decision in decisions or []:
        req = requirements_by_id.get(decision.requirement_id)
        if req is None or decision.pause_type != "confirmation" or decision.approved is True:
            continue
        # A native harness reports the denied tool call as failed; its card closes as denied, not as an error
        if req.tool_execution is not None and req.tool_execution.tool_call_id:
            state.denied_tool_call_ids.add(req.tool_execution.tool_call_id)
        args_str = ", ".join(f"{k}={truncate(str(v), 40)}" for k, v in tool_args(req).items())
        title = truncate(f"Denied: {tool_name(req)}({args_str})" if args_str else f"Denied: {tool_name(req)}", 120)
        await stream.append(
            chunks=[
                {
                    "type": "task_update",
                    "id": f"approval:{decision.requirement_id}",
                    "title": title,
                    "status": "complete",
                }
            ]
        )


async def continue_run(
    event_context: "EventContext",
    client: Any,
    ctx: "SlackContext",
    requirements: List["RunRequirement"],
    *,
    decisions: Optional[List[Any]] = None,
    before_continue: Optional[Callable[[], Awaitable[None]]] = None,
    on_accepted: Optional[Callable[[], Awaitable[None]]] = None,
    clicker: Optional[str] = None,
) -> bool:
    """Continue a paused run with its resolved requirements and render the rest of the reply.

    The reply streams to ``clicker``, the user who decided, as the run's owner may be unknown after a restart.
    ``before_continue`` runs once the run may be continued and before anything resumes it; raising
    DecisionRefused there refuses the decision. Returns False when the continuation was accepted but could not
    be resumed; raises DecisionRefused when the run refuses the decision (a live native run, or a durable
    ticket owning it), in which case the run was not resumed.
    """
    entity = ctx.entity
    state = StreamState(entity_type=ctx.entity_type, entity_name=ctx.entity_name)
    native = False
    submitted: Any = None
    tail_from: Optional[int] = None
    answered: Set[str] = set()
    try:
        run_output = None
        if hasattr(entity, "aget_run_output"):
            run_output = await entity.aget_run_output(run_id=event_context.run_id, session_id=event_context.session_id)
        state.paused_content = str(getattr(run_output, "content", None) or "")
        native = bool(getattr(entity, "_uses_native_hitl", False)) and live_native_run(run_output)
        if native:
            # Only the requests this click answers; earlier decisions of the run are history
            answered = set(hitl_state(run_output).get("pending") or [])
            tools = [r.tool_execution for r in requirements if r.tool_execution]
            if before_continue is not None:
                await before_continue()
            try:
                submitted, tail_from = await adeliver_native_decisions(
                    entity, run_output, tools, event_context.session_id, event_context.user_id
                )
            except (ValueError, TypeError, KeyError) as e:
                raise DecisionRefused() from e
        else:
            # A durable ticket for this run owns its continuation; Slack never runs it a second time
            try:
                await araise_if_ticket_owns_continue(
                    get_active_queue_worker(),
                    event_context.run_id,
                    component_type=ctx.entity_type,
                    component_id=getattr(entity, "id", None),
                )
            except HTTPException as e:
                # 409: the ticket owns the continuation; anything else could not check it, so the user retries
                if e.status_code == 409:
                    raise DecisionRefused() from e
                raise DecisionRefused(APPROVAL_NOT_RECORDED_MESSAGE) from e
            if before_continue is not None:
                await before_continue()
    except DecisionRefused:
        await _stopped_while_deciding(event_context, client, ctx)
        raise
    except Exception as e:
        # Nothing was accepted, so the card stays live
        log_error(f"[HITL] decision not recorded for run={event_context.run_id}: {e}")
        await _stopped_while_deciding(event_context, client, ctx)
        raise DecisionRefused(APPROVAL_NOT_RECORDED_MESSAGE) from e
    if on_accepted is not None:
        await on_accepted()

    ctx.runs.register(event_context)
    ctx.runs.mark_started(event_context.run_id)
    await start_status(client, event_context.channel, event_context.thread_ts, ctx.loading_text, ctx.loading_messages)
    stream = SlackStream(client, event_context, ctx, recipient_user_id=clicker)
    ctx.runs.set_stream(event_context.run_id, stream)
    parked = False
    scope = (
        authorization_scope(lambda: event_context.authority)
        if event_context.authority is not None
        else contextlib.nullcontext()
    )
    try:
        with scope:
            try:
                if native:
                    events: Any = _native_events(ctx, event_context, submitted, tail_from, answered)
                else:
                    events = entity.acontinue_run(
                        run_id=event_context.run_id,
                        requirements=requirements,
                        session_id=event_context.session_id,
                        user_id=event_context.user_id,
                        stream=True,
                        stream_events=True,
                    )
                await _post_denial_cards(stream, state, decisions, requirements)
                await _render(events, event_context, client, ctx, state, stream, set_thread_title=False)
                parked = await _finish(event_context, client, ctx, state, stream)
            except asyncio.CancelledError:
                with contextlib.suppress(Exception):
                    await stream.stop(
                        markdown_text=f"\n{STOPPED_TEXT}",
                        chunks=state.resolve_all_pending("complete", suffix="stopped") or None,
                    )
                if not stream.ended:
                    await clear_status(client, event_context.channel, event_context.thread_ts)
                raise
            except Exception as e:
                await _fail(e, event_context, client, ctx, state, stream)
                if not stream.opened:
                    return False
            if not native:
                # Status-only stream sync, as the REST continue doors do; a stream-backend failure keeps the reply
                try:
                    await acomplete_continue_stream(
                        entity, event_context.run_id, event_context.session_id, only_if_tracked=True
                    )
                except Exception as e:
                    log_error(f"[HITL] continue stream sync failed for run={event_context.run_id}: {e}")
        return True
    finally:
        stream.close()
        if not parked:
            ctx.runs.unregister(event_context.run_id)


async def _stopped_while_deciding(event_context: "EventContext", client: Any, ctx: "SlackContext") -> None:
    # A Stop that came while a decision was being submitted wins once the decision is refused: the card reads Stopped
    if not event_context.stopped:
        return
    card_ts, awaiting_ts = ctx.runs.parked_cards(event_context.run_id)
    await _freeze_card(client, event_context, card_ts, awaiting_ts)
    ctx.runs.unregister(event_context.run_id)


async def _freeze_card(
    client: Any,
    event_context: "EventContext",
    card_ts: Optional[str],
    awaiting_ts: Optional[str],
    text: str = "Stopped",
    notice: str = STOPPED_TEXT,
) -> None:
    await delete_awaiting_indicator(client, event_context.channel, awaiting_ts)
    if card_ts:
        blocks = [{"type": "context", "elements": [{"type": "mrkdwn", "text": notice}]}]
        await update_message(client, event_context.channel, card_ts, text, blocks)


async def aclose_runs(ctx: "SlackContext") -> None:
    """Finish or stop the in-flight runs, then freeze the cards of native approvals that ended with them."""
    await ctx.runs.aclose()
    # A native approval waits inside this process, so its run ends here and its card must not stay live
    if getattr(ctx.entity, "_uses_native_hitl", False):
        client = ctx.web()
        for event_context in ctx.runs.parked():
            try:
                run = await read_run(ctx.entity, event_context.run_id, event_context.session_id, event_context.user_id)
            except Exception as e:
                # Unreadable: the native run ends with this process either way, so the card is frozen
                log_error(f"[HITL] aget_run_output failed for run={event_context.run_id}: {e}")
                run = None
            # A run decided elsewhere (the AgentOS continue route) or already ended keeps its card
            if run is None or awaiting_decision(run):
                # The run is cancelled with its card, so a new message does not find it waiting for a decision
                await _cancel_run(ctx, event_context.run_id)
                card_ts, awaiting_ts = ctx.runs.parked_cards(event_context.run_id)
                await _freeze_card(client, event_context, card_ts, awaiting_ts)
            # FastAPI can run a router's shutdown handler twice, so a frozen card is not frozen again
            ctx.runs.unregister(event_context.run_id)


async def cancel_paused(event_context: "EventContext", client: Any, ctx: "SlackContext") -> None:
    """Cancel a run paused on a card through core's own continue: no model call, and the tool never runs."""
    entity = ctx.entity
    card_ts, awaiting_ts = ctx.runs.parked_cards(event_context.run_id)
    if hasattr(entity, "aget_run_output") and hasattr(entity, "acontinue_run"):
        run_output = await entity.aget_run_output(run_id=event_context.run_id, session_id=event_context.session_id)
        status = getattr(run_output, "status", None)
        if status != RunStatus.paused:
            # Decided elsewhere (the AgentOS continue route): a continue here would start a new run
            await _freeze_card(
                client, event_context, card_ts, awaiting_ts, NO_LONGER_ACTIVE_MESSAGE, NO_LONGER_ACTIVE_MESSAGE
            )
            return
        requirements = list(getattr(run_output, "active_requirements", None) or [])
        for requirement in requirements:
            if requirement.needs_confirmation:
                requirement.reject(_STOPPED_NOTE)
            elif requirement.needs_external_execution:
                requirement.set_external_execution_result(_STOPPED_NOTE)
        await _cancel_run(ctx, event_context.run_id)
        try:
            async for _ in entity.acontinue_run(
                run_id=event_context.run_id,
                requirements=requirements,
                session_id=event_context.session_id,
                user_id=event_context.user_id,
                stream=True,
                stream_events=True,
            ):
                pass
        except Exception:
            # A Team with a pending admin approval refuses the continue; its run stays paused
            pass
    else:
        await _cancel_run(ctx, event_context.run_id)
    await _freeze_card(client, event_context, card_ts, awaiting_ts)
    await clear_status(client, event_context.channel, event_context.thread_ts)
    ctx.runs.unregister(event_context.run_id)


async def stop_runs(
    ctx: "SlackContext", client: Any, user: str, channel: str, thread_ts: str, streaming_message_ts: List[str]
) -> None:
    """Stop the runs a Slack Stop names: the one owning the stopped message, else every running one in the thread."""
    for event_context in ctx.runs.find(channel, thread_ts, streaming_message_ts):
        if not await can_act(ctx, user, event_context, client):
            # A Stop on the whole thread passes over other people's runs; only a Stop on this one says why
            if streaming_message_ts:
                message = _NOT_OWNER_STOP_MESSAGE.format(owner=event_context.owner)
                await post_ephemeral(client, channel, user, message, thread_ts)
            continue
        if not hasattr(ctx.entity, "acancel_run"):
            await post_ephemeral(client, channel, user, _CANNOT_STOP_MESSAGE, thread_ts)
            continue
        ctx.runs.record_stop(event_context.run_id)
        if ctx.runs.is_parked(event_context.run_id):
            # A Stop can land after the run paused; while a decision holds the claim, it stops as a live run
            if ctx.runs.claim_run(event_context.run_id):
                try:
                    await cancel_paused(event_context, client, ctx)
                finally:
                    ctx.runs.release_run(event_context.run_id)
                continue
        # Slack draws its own notice on the message whose Stop was pressed; any other reply says it stopped
        own_message = bool(set(streaming_message_ts).intersection(event_context.streaming_message_ts))
        await _stop_live(event_context, client, ctx, own_message)


async def _stop_live(event_context: "EventContext", client: Any, ctx: "SlackContext", own_message: bool) -> None:
    event_context.stopped = True
    # Only a run that started is cancelled: a cancel for an id that never ran would block its later rerun
    if ctx.runs.is_started(event_context.run_id) or ctx.runs.is_parked(event_context.run_id):
        await _cancel_run(ctx, event_context.run_id)
    stream = ctx.runs.stream_for(event_context.run_id)
    # A run without a stream ends its own status: the executor clears it before or after the entity run
    if stream is not None:
        try:
            await stream.stop(markdown_text=None if own_message else f"\n{STOPPED_TEXT}")
        except Exception as e:
            # The message is ended either way; the other runs of a thread-wide Stop still stop
            log_error(f"Failed to stop Slack stream for run {event_context.run_id}: {str(e)}")
        if not stream.ended:
            await clear_status(client, event_context.channel, event_context.thread_ts)
