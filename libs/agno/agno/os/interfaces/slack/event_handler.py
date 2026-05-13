from __future__ import annotations

from dataclasses import dataclass
from ssl import SSLContext
from typing import Any, Dict, List, Literal, Optional, Union

from slack_sdk.web.async_client import AsyncWebClient

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.slack.events import process_event
from agno.os.interfaces.slack.helpers import (
    BotNameResolver,
    build_run_metadata,
    download_event_files_async,
    extract_event_context,
    open_chat_stream,
    resolve_channel_name,
    resolve_slack_user,
    send_slack_message_async,
    should_respond,
    strip_bot_mention,
    upload_response_media_async,
)
from agno.os.interfaces.slack.state import StreamState, TaskStatus
from agno.team import RemoteTeam, Team
from agno.tools.slack import SlackTools
from agno.utils.log import log_error
from agno.workflow import RemoteWorkflow, Workflow

_ERROR_MESSAGE = "Sorry, there was an error processing your message."
_STREAM_CHAR_LIMIT = 39000
_STREAM_CARD_LIMIT = 45


@dataclass
class EventContext:
    channel_id: str
    thread_id: str
    user: str
    message_text: str
    session_id: str
    team_id: Optional[str] = None
    resolved_user_id: str = ""
    display_name: Optional[str] = None
    channel_name: Optional[str] = None
    action_token: Optional[str] = None


@dataclass
class SlackEventHandler:
    slack_tools: SlackTools
    ssl: Optional[SSLContext]
    entity: Union[Agent, RemoteAgent, Team, RemoteTeam, Workflow, RemoteWorkflow]
    entity_id: str
    entity_name: str
    entity_type: Literal["agent", "team", "workflow"]
    bot_name_resolver: BotNameResolver
    reply_to_mentions_only: bool
    resolve_user_identity: bool
    loading_text: str
    loading_messages: Optional[List[str]]
    task_display_mode: str
    buffer_size: int
    suggested_prompts: Optional[List[Dict[str, str]]] = None

    def _client(self) -> AsyncWebClient:
        return AsyncWebClient(token=self.slack_tools.token, ssl=self.ssl)

    async def resolve_context(self, data: dict) -> Optional[EventContext]:
        event = data["event"]
        if not should_respond(event, self.reply_to_mentions_only):
            return None

        client = self._client()
        raw_ctx = extract_event_context(event)

        bot_user_id = (data.get("authorizations") or [{}])[0].get("user_id")
        bot_name = await self.bot_name_resolver.resolve(client, bot_user_id) if bot_user_id else None
        message_text = strip_bot_mention(raw_ctx["message_text"], bot_user_id, bot_name)

        session_id = f"{self.entity_id}:{raw_ctx['thread_id']}"
        team_id = data.get("team_id") or event.get("team")

        resolved_user_id = raw_ctx["user"]
        display_name = None
        if self.resolve_user_identity:
            resolved_user_id, display_name = await resolve_slack_user(client, raw_ctx["user"])

        channel_name = await resolve_channel_name(client, raw_ctx["channel_id"])

        return EventContext(
            channel_id=raw_ctx["channel_id"],
            thread_id=raw_ctx["thread_id"],
            user=raw_ctx["user"],
            message_text=message_text,
            session_id=session_id,
            team_id=team_id,
            resolved_user_id=resolved_user_id,
            display_name=display_name,
            channel_name=channel_name,
            action_token=raw_ctx.get("action_token"),
        )

    async def download_files(self, event: dict) -> tuple:
        return await download_event_files_async(self.slack_tools.token, event, self.slack_tools.max_file_size)

    def build_run_kwargs(
        self,
        ctx: EventContext,
        files: Any,
        images: Any,
        videos: Any,
        audio: Any,
        streaming: bool = False,
    ) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "user_id": ctx.resolved_user_id,
            "session_id": ctx.session_id,
            "metadata": build_run_metadata(
                ctx.display_name,
                ctx.resolved_user_id,
                {
                    "channel_id": ctx.channel_id,
                    "thread_id": ctx.thread_id,
                    "user": ctx.user,
                    "message_text": ctx.message_text,
                    "action_token": ctx.action_token,
                },
            ),
            "dependencies": {
                "Slack channel": f"#{ctx.channel_name}" if ctx.channel_name else ctx.channel_id,
                "Slack channel_id": ctx.channel_id,
                "Slack thread_ts": ctx.thread_id,
            },
            "add_dependencies_to_context": True,
            "files": files or None,
            "images": images or None,
            "videos": videos or None,
            "audio": audio or None,
        }
        if streaming:
            kwargs["stream"] = True
            kwargs["stream_events"] = True
        return kwargs

    async def set_status(self, ctx: EventContext, status: str) -> None:
        try:
            status_kwargs: Dict[str, Any] = {
                "channel_id": ctx.channel_id,
                "thread_ts": ctx.thread_id,
                "status": status,
            }
            if status and self.loading_messages:
                status_kwargs["loading_messages"] = self.loading_messages
            await self._client().assistant_threads_setStatus(**status_kwargs)
        except Exception:
            pass

    async def send_error(self, ctx: EventContext, message: str = _ERROR_MESSAGE) -> None:
        await send_slack_message_async(
            self._client(),
            channel=ctx.channel_id,
            message=message,
            thread_ts=ctx.thread_id,
        )

    async def handle_non_streaming(self, data: dict) -> None:
        ctx = await self.resolve_context(data)
        if ctx is None:
            return

        client = self._client()
        await self.set_status(ctx, self.loading_text)

        try:
            files, images, videos, audio, skipped = await self.download_files(data["event"])

            message_text = ctx.message_text
            if skipped:
                notice = "[Skipped files: " + ", ".join(skipped) + "]"
                message_text = f"{notice}\n{message_text}"

            run_kwargs = self.build_run_kwargs(ctx, files, images, videos, audio, streaming=False)
            response = await self.entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]

            if response:
                if response.status == "ERROR":
                    log_error(f"Error processing message: {response.content}")
                    await self.send_error(ctx, f"{_ERROR_MESSAGE} Please try again later.")
                    return

                if response.status == "PAUSED":
                    handled = await self._handle_paused_non_streaming(ctx, response)
                    if handled:
                        return

                if hasattr(response, "reasoning_content") and response.reasoning_content:
                    rc = str(response.reasoning_content)
                    formatted = "*Reasoning:*\n> " + rc.replace("\n", "\n> ")
                    await send_slack_message_async(
                        client, channel=ctx.channel_id, message=formatted, thread_ts=ctx.thread_id
                    )

                content = str(response.content) if response.content else ""
                await send_slack_message_async(client, channel=ctx.channel_id, message=content, thread_ts=ctx.thread_id)
                await upload_response_media_async(client, response, ctx.channel_id, ctx.thread_id)

        except Exception as e:
            log_error(f"Error processing slack event: {str(e)}")
            await self.send_error(ctx)
        finally:
            await self.set_status(ctx, "")

    async def _handle_paused_non_streaming(self, ctx: EventContext, response: Any) -> bool:
        from agno.os.interfaces.slack.pause import _PAUSE_LABELS, post_pause_card
        from agno.os.interfaces.slack.types import tool_name

        client = self._client()
        requirements = list(getattr(response, "active_requirements", None) or [])
        run_id = getattr(response, "run_id", None)

        if not (run_id and requirements):
            return False

        content = str(response.content) if response.content else ""
        if content:
            await send_slack_message_async(client, channel=ctx.channel_id, message=content, thread_ts=ctx.thread_id)

        pause_labels = [_PAUSE_LABELS[r.pause_type].format(tool=tool_name(r)) for r in requirements]
        awaiting_ts = None
        if pause_labels:
            try:
                awaiting_resp = await client.chat_postMessage(
                    channel=ctx.channel_id,
                    thread_ts=ctx.thread_id,
                    text="\n".join(pause_labels),
                    mrkdwn=True,
                )
                awaiting_ts = awaiting_resp.get("ts")
            except Exception as exc:
                log_error(f"[HITL] Non-streaming awaiting indicator failed: {exc}")

        try:
            await post_pause_card(client, response, ctx.channel_id, ctx.thread_id, awaiting_ts)
        except Exception as exc:
            log_error(f"[HITL] Non-streaming pause card failed: {exc}")

        return True

    async def _open_chat_stream(self, client: AsyncWebClient, ctx: EventContext) -> Any:
        return await open_chat_stream(
            client, ctx.channel_id, ctx.thread_id, ctx.user, ctx.team_id,
            self.task_display_mode, self.buffer_size,
        )

    async def _set_thread_title(self, client: AsyncWebClient, ctx: EventContext, state: StreamState) -> None:
        if state.title_set:
            return
        state.title_set = True
        title = ctx.message_text[:50].strip() or "New conversation"
        try:
            await client.assistant_threads_setTitle(
                channel_id=ctx.channel_id, thread_ts=ctx.thread_id, title=title
            )
        except Exception:
            pass

    async def _rotate_stream(
        self, client: AsyncWebClient, ctx: EventContext, state: StreamState, stream: Any, pending_text: str = ""
    ) -> Any:
        in_progress = [(k, v.title) for k, v in state.task_cards.items() if v.status == "in_progress"]
        rotate_stop: Dict[str, Any] = {}
        if state.task_cards:
            rotate_stop["chunks"] = state.resolve_all_pending("complete")
        await stream.stop(**rotate_stop)

        new_stream = await self._open_chat_stream(client, ctx)
        state.task_cards.clear()
        state.stream_chars_sent = 0

        for key, card_title in in_progress:
            state.track_task(key, card_title)
            await new_stream.append(
                markdown_text="",
                chunks=[{"type": "task_update", "id": key, "title": card_title, "status": "in_progress"}],
            )
        if pending_text:
            continued = "_(continued)_\n" + pending_text
            await new_stream.append(markdown_text=continued)
            state.stream_chars_sent = len(continued)

        return new_stream

    async def _finalize_stream(self, client: AsyncWebClient, ctx: EventContext, state: StreamState, stream: Any) -> None:
        final_status: TaskStatus = state.terminal_status or "complete"
        completion_chunks = state.resolve_all_pending(final_status) if state.task_cards else []
        stop_kwargs: Dict[str, Any] = {}
        if state.has_content():
            stop_kwargs["markdown_text"] = state.flush()
        if completion_chunks:
            stop_kwargs["chunks"] = completion_chunks

        await stream.stop(**stop_kwargs)
        await upload_response_media_async(client, state, ctx.channel_id, ctx.thread_id)

    async def handle_streaming(self, data: dict) -> None:
        ctx = await self.resolve_context(data)
        if ctx is None:
            return

        client = self._client()
        state = StreamState(entity_type=self.entity_type, entity_name=self.entity_name)
        stream = None

        try:
            await self.set_status(ctx, self.loading_text)

            files, images, videos, audio, skipped = await self.download_files(data["event"])
            message_text = ctx.message_text
            if skipped:
                message_text = f"[Skipped files: {', '.join(skipped)}]\n{message_text}"

            run_kwargs = self.build_run_kwargs(ctx, files, images, videos, audio, streaming=True)
            response_stream = self.entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]
            if response_stream is None:
                await self.set_status(ctx, "")
                return

            stream = await self._open_chat_stream(client, ctx)

            async for chunk in response_stream:
                state.collect_media(chunk)

                ev = getattr(chunk, "event", None)
                if ev and await process_event(ev, chunk, state, stream):
                    break

                if len(state.task_cards) >= _STREAM_CARD_LIMIT:
                    stream = await self._rotate_stream(client, ctx, state, stream, state.flush() if state.has_content() else "")

                if state.has_content():
                    await self._set_thread_title(client, ctx, state)
                    content = state.flush()
                    if state.stream_chars_sent + len(content) <= _STREAM_CHAR_LIMIT:
                        await stream.append(markdown_text=content)
                        state.stream_chars_sent += len(content)
                    else:
                        stream = await self._rotate_stream(client, ctx, state, stream, content)

            if state.paused_event is not None:
                handled = await self._handle_paused_streaming(ctx, state, stream)
                if handled:
                    return

            await self._finalize_stream(client, ctx, state, stream)

        except Exception as e:
            await self._handle_streaming_error(ctx, state, stream, e)

    async def _handle_paused_streaming(self, ctx: EventContext, state: StreamState, stream: Any) -> bool:
        from agno.os.interfaces.slack.pause import finalize_pause, post_pause_card

        client = self._client()
        pause_run_id = getattr(state.paused_event, "run_id", None)
        requirements = list(getattr(state.paused_event, "active_requirements", None) or [])

        if not (pause_run_id and requirements):
            return False

        awaiting_ts = await finalize_pause(
            client=client,
            stream=stream,
            state=state,
            run_id=pause_run_id,
            channel=ctx.channel_id,
            thread_ts=ctx.thread_id,
            requirements=requirements,
        )
        try:
            await post_pause_card(client, state.paused_event, ctx.channel_id, ctx.thread_id, awaiting_ts)
        except Exception as exc:
            log_error(f"[HITL] Failed to post Card block (pause): {exc}")

        return True

    async def _handle_streaming_error(
        self, ctx: EventContext, state: StreamState, stream: Any, error: Exception
    ) -> None:
        slack_resp = getattr(error, "response", None)
        slack_body = slack_resp.data if slack_resp else None
        slack_error = slack_body.get("error", "") if isinstance(slack_body, dict) else ""
        is_msg_too_long = "msg_too_long" in slack_error or "msg_blocks_too_long" in slack_error
        if not is_msg_too_long:
            is_msg_too_long = "msg_too_long" in str(error)

        if not is_msg_too_long:
            log_error(
                f"Error streaming slack response [channel={ctx.channel_id}, thread={ctx.thread_id}, user={ctx.user}]: {error}"
            )

        await self.set_status(ctx, "")

        if stream is not None:
            try:
                stop_kwargs: Dict[str, Any] = {}
                if state.task_cards:
                    stop_kwargs["chunks"] = state.resolve_all_pending("complete" if is_msg_too_long else "error")
                await stream.stop(**stop_kwargs)
            except Exception:
                pass

        if not is_msg_too_long:
            await self.send_error(ctx)

    async def handle_thread_started(self, event: dict) -> None:
        thread_info = event.get("assistant_thread", {})
        channel_id = thread_info.get("channel_id", "")
        thread_ts = thread_info.get("thread_ts", "")
        if not (channel_id and thread_ts):
            return

        prompts = self.suggested_prompts or [
            {"title": "Help", "message": "What can you help me with?"},
            {"title": "Search", "message": "Search the web for..."},
        ]
        try:
            await self._client().assistant_threads_setSuggestedPrompts(
                channel_id=channel_id, thread_ts=thread_ts, prompts=prompts
            )
        except Exception as e:
            log_error(f"Failed to set suggested prompts: {str(e)}")
