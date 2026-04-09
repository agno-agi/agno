from __future__ import annotations

from ssl import SSLContext
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.slack.events import process_event
from agno.os.interfaces.slack.helpers import (
    build_run_metadata,
    download_event_files_async,
    extract_event_context,
    resolve_channel_name,
    resolve_slack_user,
    send_slack_message_async,
    should_respond,
    strip_bot_mention,
    upload_response_media_async,
)
from agno.os.interfaces.slack.security import verify_slack_signature
from agno.os.interfaces.slack.state import StreamState
from agno.team import RemoteTeam, Team
from agno.tools.slack import SlackTools
from agno.utils.log import log_error
from agno.workflow import RemoteWorkflow, Workflow

# Slack sends lifecycle events for bots with these subtypes. Without this
# filter the router would try to process its own messages, causing infinite loops.
_IGNORED_SUBTYPES = frozenset(
    {
        "bot_message",
        "bot_add",
        "bot_remove",
        "bot_enable",
        "bot_disable",
        "message_changed",
        "message_deleted",
    }
)

# User-facing error message for failed requests
_ERROR_MESSAGE = "Sorry, there was an error processing your message."

# Slack caps streamed messages at ~40K total payload (text + task card blocks)
_STREAM_CHAR_LIMIT = 39000
_STREAM_CARD_LIMIT = 45


class SlackEventResponse(BaseModel):
    status: str = Field(default="ok")


class SlackChallengeResponse(BaseModel):
    challenge: str = Field(description="Challenge string to echo back to Slack")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
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
) -> APIRouter:
    # Inner functions capture config via closure to keep each instance isolated
    entity = agent or team or workflow
    # entity_type drives event dispatch (agent vs team vs workflow events)
    entity_type: Literal["agent", "team", "workflow"] = "agent" if agent else "team" if team else "workflow"
    raw_name = getattr(entity, "name", None)
    # entity_name labels task cards; entity_id namespaces session IDs
    entity_name = raw_name if isinstance(raw_name, str) else entity_type
    # Multiple Slack instances can be mounted on one FastAPI app (e.g. /research
    # and /analyst). op_suffix makes each operation_id unique to avoid collisions.
    op_suffix = entity_name.lower().replace(" ", "_")
    entity_id = getattr(entity, "id", None) or entity_name

    slack_tools = SlackTools(token=token, ssl=ssl, max_file_size=max_file_size)

    @router.post(
        "/events",
        operation_id=f"slack_events_{op_suffix}",
        name="slack_events",
        description="Process incoming Slack events",
        response_model=Union[SlackChallengeResponse, SlackEventResponse],
        response_model_exclude_none=True,
        responses={
            200: {"description": "Event processed successfully"},
            400: {"description": "Missing Slack headers"},
            403: {"description": "Invalid Slack signature"},
        },
    )
    async def slack_events(request: Request, background_tasks: BackgroundTasks):
        # ACK immediately, process in background. Slack retries after ~3s if it
        # doesn't get a 200, so long-running agent calls must not block the response.
        body = await request.body()
        timestamp = request.headers.get("X-Slack-Request-Timestamp")
        slack_signature = request.headers.get("X-Slack-Signature", "")

        if not timestamp or not slack_signature:
            raise HTTPException(status_code=400, detail="Missing Slack headers")

        if not verify_slack_signature(body, timestamp, slack_signature, signing_secret=signing_secret):
            raise HTTPException(status_code=403, detail="Invalid signature")

        # Slack retries after ~3s if it doesn't get a 200. Since we ACK
        # immediately and process in background, retries are always duplicates.
        # Trade-off: if the server crashes mid-processing, the retried event
        # carrying the same payload won't be reprocessed — acceptable for chat.
        if request.headers.get("X-Slack-Retry-Num"):
            return SlackEventResponse(status="ok")

        data = await request.json()

        if data.get("type") == "url_verification":
            return SlackChallengeResponse(challenge=data.get("challenge"))

        if "event" in data:
            event = data["event"]
            event_type = event.get("type")
            # setSuggestedPrompts requires "Agents & AI Apps" mode (streaming UX only)
            if event_type == "assistant_thread_started" and streaming:
                background_tasks.add_task(_handle_thread_started, event)
            # Bot self-loop prevention: check bot_id at both the top-level event
            # and inside message_changed's nested "message" object. Without the
            # nested check, edited bot messages would be reprocessed as new events.
            elif (
                event.get("bot_id")
                or (event.get("message") or {}).get("bot_id")
                or event.get("subtype") in _IGNORED_SUBTYPES
            ):
                pass
            elif streaming:
                background_tasks.add_task(_stream_slack_response, data)
            else:
                background_tasks.add_task(_process_slack_event, data)

        return SlackEventResponse(status="ok")

    async def _process_slack_event(data: dict):
        event = data["event"]
        if not should_respond(event, reply_to_mentions_only):
            return

        from slack_sdk.web.async_client import AsyncWebClient

        ctx = extract_event_context(event)

        # Strip the bot's own @mention from the message text
        bot_user_id = (data.get("authorizations") or [{}])[0].get("user_id")
        ctx["message_text"] = strip_bot_mention(ctx["message_text"], bot_user_id)

        # Namespace with entity_id so threads don't collide across mounted interfaces
        session_id = f"{entity_id}:{ctx['thread_id']}"
        async_client = AsyncWebClient(token=slack_tools.token, ssl=ssl)

        try:
            await async_client.assistant_threads_setStatus(
                channel_id=ctx["channel_id"],
                thread_ts=ctx["thread_id"],
                status=loading_text,
            )
        except Exception:
            pass

        try:
            # Resolve Slack user ID to email + display name when opted in
            resolved_user_id = ctx["user"]
            display_name = None
            if resolve_user_identity:
                resolved_user_id, display_name = await resolve_slack_user(async_client, ctx["user"])

            channel_name = await resolve_channel_name(async_client, ctx["channel_id"])

            files, images, videos, audio, skipped = await download_event_files_async(
                slack_tools.token, event, slack_tools.max_file_size
            )

            message_text = ctx["message_text"]
            if skipped:
                notice = "[Skipped files: " + ", ".join(skipped) + "]"
                message_text = f"{notice}\n{message_text}"
            run_kwargs: Dict[str, Any] = {
                "user_id": resolved_user_id,
                "session_id": session_id,
                "metadata": build_run_metadata(display_name, resolved_user_id, ctx),
                "dependencies": {
                    "Slack channel": f"#{channel_name}" if channel_name else ctx["channel_id"],
                    "Slack channel_id": ctx["channel_id"],
                    "Slack thread_ts": ctx["thread_id"],
                },
                "add_dependencies_to_context": True,
                "files": files or None,
                "images": images or None,
                "videos": videos or None,
                "audio": audio or None,
            }

            response = await entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]

            if response:
                if response.status == "ERROR":
                    log_error(f"Error processing message: {response.content}")
                    await send_slack_message_async(
                        async_client,
                        channel=ctx["channel_id"],
                        message=f"{_ERROR_MESSAGE} Please try again later.",
                        thread_ts=ctx["thread_id"],
                    )
                    return

                if hasattr(response, "reasoning_content") and response.reasoning_content:
                    rc = str(response.reasoning_content)
                    formatted = "*Reasoning:*\n> " + rc.replace("\n", "\n> ")
                    await send_slack_message_async(
                        async_client,
                        channel=ctx["channel_id"],
                        message=formatted,
                        thread_ts=ctx["thread_id"],
                    )

                content = str(response.content) if response.content else ""
                await send_slack_message_async(
                    async_client,
                    channel=ctx["channel_id"],
                    message=content,
                    thread_ts=ctx["thread_id"],
                )
                await upload_response_media_async(async_client, response, ctx["channel_id"], ctx["thread_id"])
        except Exception as e:
            log_error(f"Error processing slack event: {str(e)}")
            await send_slack_message_async(
                async_client,
                channel=ctx["channel_id"],
                message=_ERROR_MESSAGE,
                thread_ts=ctx["thread_id"],
            )
        finally:
            # Clear "Thinking..." status. In streaming mode stream.stop() handles
            # this automatically, but the non-streaming path must clear explicitly.
            try:
                await async_client.assistant_threads_setStatus(
                    channel_id=ctx["channel_id"], thread_ts=ctx["thread_id"], status=""
                )
            except Exception:
                pass

    async def _stream_slack_response(data: dict):
        from slack_sdk.web.async_client import AsyncWebClient

        event = data["event"]
        if not should_respond(event, reply_to_mentions_only):
            return

        ctx = extract_event_context(event)

        # Strip the bot's own @mention from the message text
        bot_user_id = (data.get("authorizations") or [{}])[0].get("user_id")
        ctx["message_text"] = strip_bot_mention(ctx["message_text"], bot_user_id)

        session_id = f"{entity_id}:{ctx['thread_id']}"

        # Not consistently placed across Slack event envelope shapes
        team_id = data.get("team_id") or event.get("team")
        # CRITICAL: recipient_user_id must be the HUMAN user, not the bot.
        # event["user"] = human who sent the message. data["authorizations"][0]["user_id"]
        # = the bot's own user ID. Using the bot ID causes Slack to stream content
        # to an invisible recipient, resulting in a blank bubble until stopStream.
        user_id = ctx["user"]

        async_client = AsyncWebClient(token=slack_tools.token, ssl=ssl)
        state = StreamState(entity_type=entity_type, entity_name=entity_name)
        stream = None

        try:
            try:
                status_kwargs: Dict[str, Any] = {
                    "channel_id": ctx["channel_id"],
                    "thread_ts": ctx["thread_id"],
                    "status": loading_text,
                }
                if loading_messages:
                    status_kwargs["loading_messages"] = loading_messages
                await async_client.assistant_threads_setStatus(**status_kwargs)
            except Exception:
                pass

            # Resolve Slack user ID to email + display name when opted in
            resolved_user_id = ctx["user"]
            display_name = None
            if resolve_user_identity:
                resolved_user_id, display_name = await resolve_slack_user(async_client, ctx["user"])

            channel_name = await resolve_channel_name(async_client, ctx["channel_id"])

            files, images, videos, audio, skipped = await download_event_files_async(
                slack_tools.token, event, slack_tools.max_file_size
            )

            message_text = ctx["message_text"]
            if skipped:
                notice = "[Skipped files: " + ", ".join(skipped) + "]"
                message_text = f"{notice}\n{message_text}"
            run_kwargs: Dict[str, Any] = {
                "stream": True,
                # Enables event-level chunks for task card and tool lifecycle rendering
                "stream_events": True,
                "user_id": resolved_user_id,
                "session_id": session_id,
                "metadata": build_run_metadata(display_name, resolved_user_id, ctx),
                "dependencies": {
                    "Slack channel": f"#{channel_name}" if channel_name else ctx["channel_id"],
                    "Slack channel_id": ctx["channel_id"],
                    "Slack thread_ts": ctx["thread_id"],
                },
                "add_dependencies_to_context": True,
                "files": files or None,
                "images": images or None,
                "videos": videos or None,
                "audio": audio or None,
            }

            response_stream = entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]

            if response_stream is None:
                try:
                    await async_client.assistant_threads_setStatus(
                        channel_id=ctx["channel_id"], thread_ts=ctx["thread_id"], status=""
                    )
                except Exception:
                    pass
                return

            # Deferred so "Thinking..." indicator stays visible during file
            # download and agent startup (opening earlier shows a blank bubble)
            stream = await async_client.chat_stream(
                channel=ctx["channel_id"],
                thread_ts=ctx["thread_id"],
                recipient_team_id=team_id,
                recipient_user_id=user_id,
                task_display_mode=task_display_mode,
                buffer_size=buffer_size,
            )

            async def _rotate_stream(pending_text: str = ""):
                """Close current stream and open a new one, carrying over in-progress cards."""
                nonlocal stream
                assert stream is not None  # Caller only invokes after stream is opened
                in_progress = [(k, v.title) for k, v in state.task_cards.items() if v.status == "in_progress"]
                rotate_stop: Dict[str, Any] = {}
                if state.task_cards:
                    rotate_stop["chunks"] = state.resolve_all_pending("complete")
                await stream.stop(**rotate_stop)
                new_stream = await async_client.chat_stream(
                    channel=ctx["channel_id"],
                    thread_ts=ctx["thread_id"],
                    recipient_team_id=team_id,
                    recipient_user_id=user_id,
                    task_display_mode=task_display_mode,
                    buffer_size=buffer_size,
                )
                # Only mutate state after both async ops succeed
                state.task_cards.clear()
                state.stream_chars_sent = 0
                stream = new_stream
                # Re-open in-progress cards so the user sees continuity
                for key, card_title in in_progress:
                    state.track_task(key, card_title)
                    await stream.append(
                        markdown_text="",
                        chunks=[{"type": "task_update", "id": key, "title": card_title, "status": "in_progress"}],
                    )
                if pending_text:
                    continued = "_(continued)_\n" + pending_text
                    await stream.append(markdown_text=continued)
                    state.stream_chars_sent = len(continued)

            async for chunk in response_stream:
                state.collect_media(chunk)

                ev = getattr(chunk, "event", None)
                if ev:
                    if await process_event(ev, chunk, state, stream):
                        break

                # Card overflow: rotate before Slack rejects the payload
                if len(state.task_cards) >= _STREAM_CARD_LIMIT:
                    await _rotate_stream(state.flush() if state.has_content() else "")

                if state.has_content():
                    if not state.title_set:
                        state.title_set = True
                        title = ctx["message_text"][:50].strip() or "New conversation"
                        try:
                            await async_client.assistant_threads_setTitle(
                                channel_id=ctx["channel_id"], thread_ts=ctx["thread_id"], title=title
                            )
                        except Exception:
                            pass

                    content = state.flush()
                    content_len = len(content)
                    if state.stream_chars_sent + content_len <= _STREAM_CHAR_LIMIT:
                        await stream.append(markdown_text=content)
                        state.stream_chars_sent += content_len
                    else:
                        await _rotate_stream(content)
            # Default to complete when no terminal error/cancel event arrived
            final_status: Literal["in_progress", "complete", "error"] = state.terminal_status or "complete"
            completion_chunks = state.resolve_all_pending(final_status) if state.task_cards else []
            stop_kwargs: Dict[str, Any] = {}
            if state.has_content():
                stop_kwargs["markdown_text"] = state.flush()
            if completion_chunks:
                stop_kwargs["chunks"] = completion_chunks
            await stream.stop(**stop_kwargs)

            await upload_response_media_async(async_client, state, ctx["channel_id"], ctx["thread_id"])

        except Exception as e:
            # Check structured response first (cheap); fall back to str(e) only if needed
            slack_resp = getattr(e, "response", None)
            slack_body = slack_resp.data if slack_resp else None
            slack_error = slack_body.get("error", "") if isinstance(slack_body, dict) else ""
            is_msg_too_long = "msg_too_long" in slack_error or "msg_blocks_too_long" in slack_error
            if not is_msg_too_long:
                is_msg_too_long = "msg_too_long" in str(e)
            if not is_msg_too_long:
                log_error(
                    f"Error streaming slack response [channel={ctx['channel_id']}, thread={ctx['thread_id']}, user={user_id}]"
                )
            try:
                await async_client.assistant_threads_setStatus(
                    channel_id=ctx["channel_id"], thread_ts=ctx["thread_id"], status=""
                )
            except Exception:
                pass
            # Clean up open stream so Slack doesn't show stuck progress indicators
            if stream is not None:
                try:
                    stop_kwargs_err: Dict[str, Any] = {}
                    if state.task_cards:
                        stop_kwargs_err["chunks"] = state.resolve_all_pending(
                            "complete" if is_msg_too_long else "error"
                        )
                    await stream.stop(**stop_kwargs_err)
                except Exception:
                    pass
            if not is_msg_too_long:
                await send_slack_message_async(
                    async_client,
                    channel=ctx["channel_id"],
                    message=_ERROR_MESSAGE,
                    thread_ts=ctx["thread_id"],
                )

    async def _handle_thread_started(event: dict):
        from slack_sdk.web.async_client import AsyncWebClient

        async_client = AsyncWebClient(token=slack_tools.token, ssl=ssl)
        thread_info = event.get("assistant_thread", {})
        channel_id = thread_info.get("channel_id", "")
        thread_ts = thread_info.get("thread_ts", "")
        if not channel_id or not thread_ts:
            return

        prompts = suggested_prompts or [
            {"title": "Help", "message": "What can you help me with?"},
            {"title": "Search", "message": "Search the web for..."},
        ]
        try:
            await async_client.assistant_threads_setSuggestedPrompts(
                channel_id=channel_id, thread_ts=thread_ts, prompts=prompts
            )
        except Exception as e:
            log_error(f"Failed to set suggested prompts: {str(e)}")

    return router
