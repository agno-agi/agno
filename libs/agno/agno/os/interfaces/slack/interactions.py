"""Slack interactive payload handlers.

Processes block_actions (button clicks) and view_submission (modal forms)
from Slack's /interactions endpoint. Maps interactive events back to
paused agent runs for HITL continuation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Literal, Optional

from agno.os.interfaces.slack.blocks import approved_blocks
from agno.os.interfaces.slack.helpers import send_slack_message_async, upload_response_media_async
from agno.os.interfaces.slack.state import StreamState
from agno.utils.log import log_debug, log_error

if TYPE_CHECKING:
    from ssl import SSLContext

    from agno.run.agent import RunOutput


@dataclass
class PausedRun:
    """State of a paused agent run, stored until user resolves via Slack interaction."""

    entity: Any  # Agent | Team | Workflow
    entity_type: Literal["agent", "team", "workflow"]
    entity_name: str
    run_response: RunOutput
    # Context needed to resume the run
    user_id: str
    session_id: str
    channel_id: str
    thread_ts: str
    team_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    dependencies: Optional[Dict[str, Any]] = None
    # Slack message ts for the approval card (for updating it after resolution)
    approval_message_ts: Optional[str] = None


# In-memory store for paused runs. Keyed by approval_id.
# Prototype only — production would use DB via approval.py
_paused_runs: Dict[str, PausedRun] = {}


def store_paused_run(approval_id: str, paused_run: PausedRun) -> None:
    _paused_runs[approval_id] = paused_run
    log_debug(f"Stored paused run: approval_id={approval_id}, run_id={paused_run.run_response.run_id}")


def get_paused_run(approval_id: str) -> Optional[PausedRun]:
    return _paused_runs.get(approval_id)


def remove_paused_run(approval_id: str) -> Optional[PausedRun]:
    return _paused_runs.pop(approval_id, None)


async def handle_block_action(
    action: Dict[str, Any],
    body: Dict[str, Any],
    token: str,
    ssl: Optional[SSLContext] = None,
    streaming: bool = True,
    task_display_mode: str = "plan",
    buffer_size: int = 100,
) -> None:
    """Handle a button click from an approval card."""
    from slack_sdk.web.async_client import AsyncWebClient

    action_id = action.get("action_id", "")
    approval_id = action.get("value", "")
    user_id = body.get("user", {}).get("id", "")
    channel_id = body.get("channel", {}).get("id", "")
    message_ts = body.get("message", {}).get("ts", "")
    # thread_ts: the thread where the approval card lives
    thread_ts = body.get("message", {}).get("thread_ts") or message_ts

    if action_id not in ("hitl_approve", "hitl_reject"):
        return

    approved = action_id == "hitl_approve"
    async_client = AsyncWebClient(token=token, ssl=ssl)

    # Update the approval card to show resolved status
    original_blocks = body.get("message", {}).get("blocks", [])
    updated = approved_blocks(original_blocks, user_id, approved)
    try:
        await async_client.chat_update(
            channel=channel_id,
            ts=message_ts,
            blocks=updated,
            text="Approval resolved",
        )
    except Exception as e:
        log_error(f"Failed to update approval card: {e}")

    paused = remove_paused_run(approval_id)
    if not paused:
        await send_slack_message_async(
            async_client,
            channel=channel_id,
            thread_ts=thread_ts,
            message="This approval has already been resolved or has expired.",
        )
        return

    # Apply the decision to the paused tool executions
    run_response = paused.run_response
    if run_response.tools:
        for tool in run_response.tools:
            if tool.is_paused:
                if tool.requires_confirmation:
                    tool.confirmed = approved

    if not approved:
        await send_slack_message_async(
            async_client,
            channel=channel_id,
            thread_ts=thread_ts,
            message="Action rejected. The agent will not proceed with this tool call.",
        )
        return

    # Resume the agent run with streaming
    log_debug(f"Resuming paused run: approval_id={approval_id}, run_id={run_response.run_id}")

    if streaming:
        await _continue_run_streaming(
            paused,
            async_client,
            task_display_mode,
            buffer_size,
            ssl,
        )
    else:
        await _continue_run_simple(paused, async_client)


async def _continue_run_streaming(
    paused: PausedRun,
    async_client: Any,
    task_display_mode: str,
    buffer_size: int,
    ssl: Optional[SSLContext] = None,
) -> None:
    """Resume a paused run with streaming output to Slack."""
    from agno.os.interfaces.slack.events import process_event

    entity = paused.entity
    state = StreamState(entity_type=paused.entity_type, entity_name=paused.entity_name)

    try:
        await async_client.assistant_threads_setStatus(
            channel_id=paused.channel_id,
            thread_ts=paused.thread_ts,
            status="Continuing...",
        )
    except Exception:
        pass

    stream = None
    try:
        response_stream = entity.acontinue_run(
            run_response=paused.run_response,
            stream=True,
            stream_events=True,
            user_id=paused.user_id,
            session_id=paused.session_id,
            metadata=paused.metadata,
            dependencies=paused.dependencies,
        )

        if response_stream is None:
            return

        stream = await async_client.chat_stream(
            channel=paused.channel_id,
            thread_ts=paused.thread_ts,
            recipient_team_id=paused.team_id,
            recipient_user_id=paused.user_id,
            task_display_mode=task_display_mode,
            buffer_size=buffer_size,
        )

        async for chunk in response_stream:
            state.collect_media(chunk)

            ev = getattr(chunk, "event", None)
            if ev:
                if await process_event(ev, chunk, state, stream):
                    break

            if state.has_content():
                content = state.flush()
                await stream.append(markdown_text=content)
                state.stream_chars_sent += len(content)

        final_status = state.terminal_status or "complete"
        completion_chunks = state.resolve_all_pending(final_status) if state.task_cards else []
        stop_kwargs: Dict[str, Any] = {}
        if state.has_content():
            stop_kwargs["markdown_text"] = state.flush()
        if completion_chunks:
            stop_kwargs["chunks"] = completion_chunks
        await stream.stop(**stop_kwargs)

        await upload_response_media_async(async_client, state, paused.channel_id, paused.thread_ts)

    except Exception as e:
        log_error(f"Error continuing paused run: {e}")
        if stream is not None:
            try:
                stop_kwargs_err: Dict[str, Any] = {}
                if state.task_cards:
                    stop_kwargs_err["chunks"] = state.resolve_all_pending("error")
                await stream.stop(**stop_kwargs_err)
            except Exception:
                pass
        await send_slack_message_async(
            async_client,
            channel=paused.channel_id,
            thread_ts=paused.thread_ts,
            message="Sorry, there was an error resuming the agent.",
        )
    finally:
        try:
            await async_client.assistant_threads_setStatus(
                channel_id=paused.channel_id,
                thread_ts=paused.thread_ts,
                status="",
            )
        except Exception:
            pass


async def _continue_run_simple(paused: PausedRun, async_client: Any) -> None:
    """Resume a paused run without streaming (simple message response)."""
    entity = paused.entity

    try:
        response = await entity.acontinue_run(
            run_response=paused.run_response,
            user_id=paused.user_id,
            session_id=paused.session_id,
            metadata=paused.metadata,
            dependencies=paused.dependencies,
        )

        if response and response.content:
            await send_slack_message_async(
                async_client,
                channel=paused.channel_id,
                thread_ts=paused.thread_ts,
                message=str(response.content),
            )
    except Exception as e:
        log_error(f"Error continuing paused run (simple): {e}")
        await send_slack_message_async(
            async_client,
            channel=paused.channel_id,
            thread_ts=paused.thread_ts,
            message="Sorry, there was an error resuming the agent.",
        )
