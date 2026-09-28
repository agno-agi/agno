"""Turns Slack events into Agno runs and Agno output into Slack messages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Set, Union

from slack_sdk.web.async_client import AsyncWebClient

from agno.exceptions import RunCancelledException
from agno.os.interfaces.slack.utils import (
    PAUSE_LABELS,
    ActiveRun,
    BotNameResolver,
    SessionStatus,
    SlackSessions,
    StreamState,
    TaskStatus,
    Threads,
    build_run_metadata,
    call_db,
    download_event_files_async,
    extract_event_context,
    finalize_pause,
    open_chat_stream,
    post_pause_card,
    process_event,
    resolve_channel_name,
    resolve_session_id,
    resolve_slack_bot,
    resolve_slack_user,
    send_slack_message_async,
    should_respond,
    slack_delivery_kwargs,
    strip_bot_mention,
    tool_name,
    upload_response_media_async,
)
from agno.utils.log import log_debug, log_error

if TYPE_CHECKING:
    from agno.os.interfaces.slack.slack import Slack

_ERROR_MESSAGE = "Sorry, there was an error processing your message."
_STREAM_CHAR_LIMIT = 39000
_STREAM_CARD_LIMIT = 45

ONBOARDING_LEARNING_TYPE = "slack_onboarding"
ONBOARDING_NAMESPACE = "slack"
AGNO_OS_URL = "https://os.agno.com"

# Slack shows at most four suggested prompts and truncates long ones
MAX_PROMPTS = 4
MAX_PROMPT_CHARS = 300
DEFAULT_PROMPTS: List[Dict[str, str]] = [
    {"title": "Help", "message": "What can you help me with?"},
    {"title": "Search", "message": "Search the web for..."},
]
# A prompt is the text to send; a dict adds a separate short title
Prompt = Union[str, Dict[str, str]]

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
        "thread_broadcast",
    }
)


def make_web_client(token: str, ssl: Any = None) -> AsyncWebClient:
    """The one Slack Web API client a mounted interface shares across its handlers."""
    return AsyncWebClient(token=token, ssl=ssl)


def normalize_prompts(raw: Any) -> List[Dict[str, str]]:
    """Keep only well-formed ``{title, message}`` entries, capped at Slack's limit."""
    prompts: List[Dict[str, str]] = []
    for item in raw or []:
        if isinstance(item, str):
            title = message = item
        elif isinstance(item, dict):
            message = str(item.get("message") or "").strip()
            title = str(item.get("title") or message).strip()
        else:
            continue
        if not message:
            continue
        prompts.append({"title": title[:MAX_PROMPT_CHARS], "message": message[:MAX_PROMPT_CHARS]})
        if len(prompts) >= MAX_PROMPTS:
            break
    return prompts


def build_home_view(entity_name: str, description: Optional[str] = None) -> Dict[str, Any]:
    """The app's Home tab: who this is and a link to AgentOS."""
    blocks: List[Dict[str, Any]] = [{"type": "header", "text": {"type": "plain_text", "text": entity_name[:150]}}]
    if description:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": description[:3000]}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Powered by <{AGNO_OS_URL}|AgentOS>"}]})
    return {"type": "home", "blocks": blocks}


class EventContext:
    """What one inbound message resolves to."""

    def __init__(
        self,
        channel_id: str,
        thread_id: str,
        user: str,
        message_text: str,
        session_id: str,
        bot_id: str = "",
        team_id: Optional[str] = None,
        resolved_user_id: str = "",
        display_name: Optional[str] = None,
        channel_name: Optional[str] = None,
        action_token: Optional[str] = None,
    ) -> None:
        self.channel_id = channel_id
        self.thread_id = thread_id
        self.user = user
        self.message_text = message_text
        self.session_id = session_id
        # Bot sender ID (B...) when message is from a bot; empty for human messages
        self.bot_id = bot_id
        self.team_id = team_id
        self.resolved_user_id = resolved_user_id
        self.display_name = display_name
        self.channel_name = channel_name
        self.action_token = action_token


class SlackEventHandler:
    def __init__(
        self,
        slack: "Slack",
        client: AsyncWebClient,
        *,
        sessions: Optional[SlackSessions] = None,
        threads: Optional[Threads] = None,
    ) -> None:
        self.slack = slack
        self.client = client
        self.sessions = sessions or SlackSessions(client, loading_messages=slack.loading_messages)
        self.threads = threads or Threads()
        self.bot_name_resolver = BotNameResolver()
        # Users already greeted this process; the db marker covers restarts
        self._onboarded: Set[str] = set()

    # Entity facts, read off the interface so they exist in one place
    @property
    def entity(self) -> Any:
        return self.slack.entity

    @property
    def entity_id(self) -> str:
        return self.slack.entity_id

    @property
    def entity_name(self) -> str:
        return self.slack.entity_name

    @property
    def entity_type(self) -> Literal["agent", "team", "workflow"]:
        return self.slack.entity_type

    @property
    def db(self) -> Optional[Any]:
        return self.slack.db if self.slack.db is not None else getattr(self.entity, "db", None)

    def _delivery(self) -> Dict[str, Any]:
        return slack_delivery_kwargs(self.slack.unfurl_links, self.slack.unfurl_media, self.slack.markdown)

    async def _post(self, channel: str, thread_ts: str, text: str) -> None:
        await send_slack_message_async(
            self.client,
            channel=channel,
            thread_ts=thread_ts,
            message=text,
            unfurl_links=self.slack.unfurl_links,
            unfurl_media=self.slack.unfurl_media,
            mrkdwn=self.slack.markdown,
        )

    # ------------------------------------------------------------------
    # Inbound messages
    # ------------------------------------------------------------------

    def should_process(self, event: dict) -> bool:
        """The bot's own messages never reach this point: Bolt drops them first."""
        ctx = extract_event_context(event)
        subtype = event.get("subtype")
        is_bot = ctx["bot_id"] or subtype == "bot_message"
        if subtype in _IGNORED_SUBTYPES:
            return False
        if is_bot and not self.slack.respond_to_other_apps:
            return False
        return True

    async def handle_message(self, data: dict) -> None:
        """Entry point for ``message`` and ``app_mention`` events."""
        if not self.should_process(data.get("event") or {}):
            return
        if self.slack.streaming:
            await self.handle_streaming(data)
        else:
            await self.handle_non_streaming(data)

    async def session_id_for(self, channel_id: str, thread_ts: str, user_key: str) -> str:
        return await resolve_session_id(
            self.entity,
            self.entity_id,
            channel_id,
            thread_ts,
            user_key=user_key if self.slack.per_user_thread_sessions else None,
        )

    async def resolve_context(self, data: dict) -> Optional[EventContext]:
        event = data["event"]
        if not should_respond(event, self.slack.reply_to_mentions_only):
            return None

        raw = extract_event_context(event)
        bot_user_id = (data.get("authorizations") or [{}])[0].get("user_id")
        bot_name = await self.bot_name_resolver.resolve(self.client, bot_user_id) if bot_user_id else None
        message_text = strip_bot_mention(raw["message_text"], bot_user_id, bot_name)

        sender_user = raw["user"]
        sender_bot_id = raw["bot_id"]
        resolved_user_id = sender_user or sender_bot_id
        display_name = None
        if self.slack.resolve_user_identity:
            if sender_bot_id:
                resolved_user_id, display_name = await resolve_slack_bot(self.client, sender_bot_id)
            elif sender_user:
                resolved_user_id, display_name = await resolve_slack_user(self.client, sender_user)

        session_id = await self.session_id_for(raw["channel_id"], raw["thread_id"], resolved_user_id)
        channel_name = await resolve_channel_name(self.client, raw["channel_id"])

        return EventContext(
            channel_id=raw["channel_id"],
            thread_id=raw["thread_id"],
            user=sender_user,
            bot_id=sender_bot_id,
            message_text=message_text,
            session_id=session_id,
            team_id=data.get("team_id") or event.get("team"),
            resolved_user_id=resolved_user_id,
            display_name=display_name,
            channel_name=channel_name,
            action_token=raw.get("action_token"),
        )

    async def download_files(self, event: dict) -> tuple:
        return await download_event_files_async(self.slack.token or "", event, self.slack.max_file_size)

    def build_run_kwargs(
        self, ctx: EventContext, files: Any, images: Any, videos: Any, audio: Any, streaming: bool = False
    ) -> Dict[str, Any]:
        dependencies: Dict[str, Any] = {
            "Slack channel": f"#{ctx.channel_name}" if ctx.channel_name else ctx.channel_id,
            "Slack channel_id": ctx.channel_id,
            "Slack thread_ts": ctx.thread_id,
        }
        # What the user was looking at when they wrote, as reported by Slack
        entities = self.threads.entities_for(ctx.channel_id, ctx.thread_id) or self.threads.entities_for(
            ctx.channel_id, ""
        )
        if entities:
            dependencies["Slack context"] = entities

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
            "dependencies": dependencies,
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

    async def set_status(self, ctx: EventContext, status: SessionStatus) -> None:
        await self.sessions.set_status(ctx.channel_id, ctx.thread_id, status, legacy_text=self.slack.loading_text)

    async def send_error(self, ctx: EventContext, message: str = _ERROR_MESSAGE) -> None:
        await self._post(ctx.channel_id, ctx.thread_id, message)

    def _pause_session_id(self, ctx: EventContext) -> Optional[str]:
        # Cards must resume on the exact session when sessions are keyed per participant
        return ctx.session_id if self.slack.per_user_thread_sessions else None

    # ------------------------------------------------------------------
    # Non-streaming replies
    # ------------------------------------------------------------------

    async def handle_non_streaming(self, data: dict) -> None:
        ctx = await self.resolve_context(data)
        if ctx is None:
            return

        end_status: SessionStatus = "active"
        run = self.threads.start_run(ctx.channel_id, ctx.thread_id, self.entity, owner=ctx.user)
        await self.set_status(ctx, "processing")
        try:
            files, images, videos, audio, skipped = await self.download_files(data["event"])
            message_text = ctx.message_text
            if skipped:
                message_text = "[Skipped files: " + ", ".join(skipped) + "]\n" + message_text

            run_kwargs = self.build_run_kwargs(ctx, files, images, videos, audio)
            response = await self.entity.arun(message_text, **run_kwargs)
            if not response:
                return

            if response.status == "ERROR":
                log_error(f"Error processing message: {response.content}")
                await self.send_error(ctx, f"{_ERROR_MESSAGE} Please try again later.")
                return
            if response.status == "CANCELLED":
                await self.send_error(ctx, self.slack.stop_message)
                return
            if response.status == "PAUSED" and await self._handle_paused_non_streaming(ctx, response):
                end_status = "suspended"
                return

            if getattr(response, "reasoning_content", None):
                rc = str(response.reasoning_content)
                await self._post(ctx.channel_id, ctx.thread_id, "*Reasoning:*\n> " + rc.replace("\n", "\n> "))
            await self._post(ctx.channel_id, ctx.thread_id, str(response.content) if response.content else "")
            await upload_response_media_async(self.client, response, ctx.channel_id, ctx.thread_id)
            await self._name_session_after_run(ctx)

        except RunCancelledException:
            await self.send_error(ctx, self.slack.stop_message)
        except Exception as e:
            log_error(f"Error processing slack event: {str(e)}")
            await self.send_error(ctx)
        finally:
            self.threads.finish_run(ctx.channel_id, ctx.thread_id, run)
            await self.set_status(ctx, end_status)

    async def _handle_paused_non_streaming(self, ctx: EventContext, response: Any) -> bool:
        requirements = list(getattr(response, "active_requirements", None) or [])
        run_id = getattr(response, "run_id", None)
        if not (run_id and requirements):
            return False

        if response.content:
            await self._post(ctx.channel_id, ctx.thread_id, str(response.content))

        awaiting_ts = None
        labels = [PAUSE_LABELS[r.pause_type].format(tool=tool_name(r)) for r in requirements]
        if labels:
            try:
                resp = await self.client.chat_postMessage(
                    channel=ctx.channel_id, thread_ts=ctx.thread_id, text="\n".join(labels), **self._delivery()
                )
                awaiting_ts = resp.get("ts")
            except Exception as exc:
                log_error(f"[HITL] Non-streaming awaiting indicator failed: {exc}")

        try:
            await post_pause_card(
                self.client,
                response,
                ctx.channel_id,
                ctx.thread_id,
                awaiting_ts,
                unfurl_links=self.slack.unfurl_links,
                unfurl_media=self.slack.unfurl_media,
                mrkdwn=self.slack.markdown,
                session_id=self._pause_session_id(ctx),
            )
        except Exception as exc:
            log_error(f"[HITL] Non-streaming pause card failed: {exc}")
        return True

    # ------------------------------------------------------------------
    # Streaming replies
    # ------------------------------------------------------------------

    async def _open_chat_stream(self, ctx: EventContext) -> Any:
        return await open_chat_stream(
            self.client,
            ctx.channel_id,
            ctx.thread_id,
            ctx.user,
            ctx.team_id,
            self.slack.task_display_mode,
            self.slack.buffer_size,
        )

    @staticmethod
    def _title_for(ctx: EventContext) -> str:
        return ctx.message_text[:50].strip() or "New conversation"

    async def _set_thread_title(self, ctx: EventContext, state: StreamState) -> None:
        # Slack thread title, set as soon as the first content arrives
        if state.title_set:
            return
        state.title_set = True
        title = self._title_for(ctx)
        self.threads.set_last_title(ctx.channel_id, ctx.thread_id, title)
        await self.sessions.rename(ctx.channel_id, ctx.thread_id, title)

    async def _name_session_after_run(self, ctx: EventContext) -> None:
        # The Agno session row only exists once the run has finished, so the session
        # is named here, once per thread, after its first message
        if not self.threads.mark_session_named(ctx.channel_id, ctx.thread_id, ctx.session_id):
            return
        title = self._title_for(ctx)
        if self.threads.last_title(ctx.channel_id, ctx.thread_id) is None:
            # Non-streaming replies have not titled the Slack thread yet
            self.threads.set_last_title(ctx.channel_id, ctx.thread_id, title)
            await self.sessions.rename(ctx.channel_id, ctx.thread_id, title)
        await self._rename_agno_session(ctx.session_id, title)

    async def _rename_agno_session(self, session_id: str, title: str) -> None:
        rename = getattr(self.entity, "aset_session_name", None)
        if rename is None:
            return
        try:
            await rename(session_id=session_id, session_name=title)
        except Exception as exc:
            log_debug(f"Session rename failed for {session_id}: {exc}")

    async def _rotate_stream(self, ctx: EventContext, state: StreamState, stream: Any, pending_text: str = "") -> Any:
        """Close the current streaming message and continue in a fresh one."""
        in_progress = [(k, v.title) for k, v in state.task_cards.items() if v.status == "in_progress"]
        rotate_stop: Dict[str, Any] = {}
        if state.task_cards:
            rotate_stop["chunks"] = state.resolve_all_pending("complete")
        try:
            await stream.stop(**rotate_stop)
        except Exception as exc:
            # Already closed (e.g. Slack halted it after a refused stop)
            log_debug(f"stream.stop before rotation failed: {exc}")

        new_stream = await self._open_chat_stream(ctx)
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

    async def _finalize_stream(self, ctx: EventContext, state: StreamState, stream: Any) -> None:
        final_status: TaskStatus = state.terminal_status or "complete"
        stop_kwargs: Dict[str, Any] = {"session_status": "active"}
        if state.has_content():
            stop_kwargs["markdown_text"] = state.flush()
        if state.task_cards:
            chunks = state.resolve_all_pending(final_status)
            if chunks:
                stop_kwargs["chunks"] = chunks
        await stream.stop(**stop_kwargs)
        await upload_response_media_async(self.client, state, ctx.channel_id, ctx.thread_id)

    async def _finalize_cancelled(self, ctx: EventContext, state: StreamState, stream: Any) -> None:
        # Slack may already have closed the streaming message when stop was pressed,
        # so the stop call is best effort; the note below always goes out
        if stream is not None:
            stop_kwargs: Dict[str, Any] = {"session_status": "active"}
            if state.has_content():
                stop_kwargs["markdown_text"] = state.flush()
            if state.task_cards:
                stop_kwargs["chunks"] = state.resolve_all_pending("complete")
            try:
                await stream.stop(**stop_kwargs)
            except Exception as exc:
                log_debug(f"stream.stop after cancel failed: {exc}")
        if self.slack.stop_message:
            await self._post(ctx.channel_id, ctx.thread_id, self.slack.stop_message)

    async def _note_run_id(self, run: ActiveRun, state: StreamState, chunk: Any) -> None:
        if state.run_id is not None:
            return
        run_id = getattr(chunk, "run_id", None)
        if isinstance(run_id, str) and run_id:
            state.run_id = run_id
            await self.threads.note_run_id(run, run_id)

    async def handle_streaming(self, data: dict) -> None:
        ctx = await self.resolve_context(data)
        if ctx is None:
            return

        state = StreamState(entity_type=self.entity_type, entity_name=self.entity_name)
        stream = None
        end_status: SessionStatus = "active"
        run = self.threads.start_run(ctx.channel_id, ctx.thread_id, self.entity, owner=ctx.user)
        try:
            await self.set_status(ctx, "processing")

            files, images, videos, audio, skipped = await self.download_files(data["event"])
            message_text = ctx.message_text
            if skipped:
                message_text = "[Skipped files: " + ", ".join(skipped) + "]\n" + message_text

            run_kwargs = self.build_run_kwargs(ctx, files, images, videos, audio, streaming=True)
            response_stream = self.entity.arun(message_text, **run_kwargs)
            if response_stream is None:
                return

            stream = await self._open_chat_stream(ctx)
            run.stream = stream

            async for chunk in response_stream:
                state.collect_media(chunk)
                await self._note_run_id(run, state, chunk)

                if run.stream_halted:
                    # Someone other than the owner pressed stop and Slack closed the
                    # streaming message; carry on in a fresh one
                    run.stream_halted = False
                    stream = await self._rotate_stream(ctx, state, stream, state.flush() if state.has_content() else "")
                    run.stream = stream

                ev = getattr(chunk, "event", None)
                if ev and await process_event(ev, chunk, state, stream):
                    break

                if len(state.task_cards) >= _STREAM_CARD_LIMIT:
                    stream = await self._rotate_stream(ctx, state, stream, state.flush() if state.has_content() else "")
                    run.stream = stream

                if state.has_content():
                    await self._set_thread_title(ctx, state)
                    content = state.flush()
                    if state.stream_chars_sent + len(content) <= _STREAM_CHAR_LIMIT:
                        await stream.append(markdown_text=content)
                        state.stream_chars_sent += len(content)
                    else:
                        stream = await self._rotate_stream(ctx, state, stream, content)
                        run.stream = stream

            if state.cancelled:
                await self._finalize_cancelled(ctx, state, stream)
                return
            if state.paused_event is not None and await self._handle_paused_streaming(ctx, state, stream):
                end_status = "suspended"
                return

            await self._finalize_stream(ctx, state, stream)
            await self._name_session_after_run(ctx)

        except RunCancelledException:
            state.cancelled = True
            await self._finalize_cancelled(ctx, state, stream)
        except Exception as e:
            await self._handle_streaming_error(ctx, state, stream, e)
        finally:
            self.threads.finish_run(ctx.channel_id, ctx.thread_id, run)
            await self.set_status(ctx, end_status)

    async def _handle_paused_streaming(self, ctx: EventContext, state: StreamState, stream: Any) -> bool:
        pause_run_id = getattr(state.paused_event, "run_id", None)
        requirements = list(getattr(state.paused_event, "active_requirements", None) or [])
        if not (pause_run_id and requirements):
            return False

        awaiting_ts = await finalize_pause(
            client=self.client,
            stream=stream,
            state=state,
            run_id=pause_run_id,
            channel=ctx.channel_id,
            thread_ts=ctx.thread_id,
            requirements=requirements,
            unfurl_links=self.slack.unfurl_links,
            unfurl_media=self.slack.unfurl_media,
            mrkdwn=self.slack.markdown,
        )
        try:
            await post_pause_card(
                self.client,
                state.paused_event,
                ctx.channel_id,
                ctx.thread_id,
                awaiting_ts,
                unfurl_links=self.slack.unfurl_links,
                unfurl_media=self.slack.unfurl_media,
                mrkdwn=self.slack.markdown,
                session_id=self._pause_session_id(ctx),
            )
        except Exception as exc:
            log_error(f"[HITL] Failed to post Card block (pause): {exc}")
        return True

    async def _handle_streaming_error(
        self, ctx: EventContext, state: StreamState, stream: Any, error: Exception
    ) -> None:
        slack_resp = getattr(error, "response", None)
        slack_body = slack_resp.data if slack_resp else None
        slack_error = slack_body.get("error", "") if isinstance(slack_body, dict) else ""
        is_msg_too_long = (
            "msg_too_long" in slack_error or "msg_blocks_too_long" in slack_error or ("msg_too_long" in str(error))
        )
        if not is_msg_too_long:
            log_error(
                f"Error streaming slack response [channel={ctx.channel_id}, thread={ctx.thread_id}, user={ctx.user}]: {error}"
            )
        if stream is not None:
            try:
                stop_kwargs: Dict[str, Any] = {"session_status": "active"}
                if state.task_cards:
                    stop_kwargs["chunks"] = state.resolve_all_pending("complete" if is_msg_too_long else "error")
                await stream.stop(**stop_kwargs)
            except Exception:
                pass
        if not is_msg_too_long:
            await self.send_error(ctx)

    # ------------------------------------------------------------------
    # Slack lifecycle events
    # ------------------------------------------------------------------

    def prompts(self) -> List[Dict[str, str]]:
        return (
            normalize_prompts(self.slack.suggested_prompts) if self.slack.suggested_prompts else list(DEFAULT_PROMPTS)
        )

    async def handle_thread_started(self, event: dict) -> None:
        """Assistant experience only: a new thread was opened in the Messages tab."""
        thread_info = event.get("assistant_thread", {})
        channel_id = thread_info.get("channel_id", "")
        thread_ts = thread_info.get("thread_ts", "")
        if not (channel_id and thread_ts):
            return
        self.sessions.use_assistant_api()
        await self.sessions.set_suggested_prompts(channel_id, self.prompts(), thread_ts=thread_ts)

    async def handle_home_opened(self, event: dict) -> None:
        """Agent experience: the user opened the app's Messages or Home tab."""
        tab = event.get("tab")
        user_id = event.get("user") or ""
        channel_id = event.get("channel") or ""
        if tab == "home":
            if user_id:
                await self.publish_home(user_id)
            return
        if tab != "messages" or not channel_id:
            return
        # Onboarding first: Slack attaches thread-less prompts to the latest message in
        # the channel, so they must be set after anything the app posts
        await self._maybe_onboard(user_id, channel_id)
        await self.sessions.set_suggested_prompts(channel_id, self.prompts())

    async def publish_home(self, slack_user_id: str) -> None:
        view = build_home_view(self.entity_name, self.slack.entity_description)
        try:
            await self.client.views_publish(user_id=slack_user_id, view=view)
        except Exception as exc:
            log_error(f"views.publish failed for {slack_user_id}: {exc}")

    async def _maybe_onboard(self, user_id: str, channel_id: str) -> None:
        message = self.slack.onboarding_message
        if not message or not user_id or user_id in self._onboarded:
            return
        db = self.db
        if db is not None and hasattr(db, "get_learning"):
            try:
                seen = await call_db(
                    db.get_learning,
                    learning_type=ONBOARDING_LEARNING_TYPE,
                    user_id=user_id,
                    namespace=ONBOARDING_NAMESPACE,
                )
                if seen:
                    self._onboarded.add(user_id)
                    return
            except Exception as exc:
                log_debug(f"Onboarding marker lookup failed for {user_id}: {exc}")

        self._onboarded.add(user_id)
        try:
            await self.client.chat_postMessage(channel=channel_id, text=message, **self._delivery())
        except Exception as exc:
            log_error(f"Failed to send onboarding message to {user_id}: {exc}")
            return

        if db is not None and hasattr(db, "upsert_learning"):
            try:
                await call_db(
                    db.upsert_learning,
                    id=f"{ONBOARDING_LEARNING_TYPE}:{user_id}",
                    learning_type=ONBOARDING_LEARNING_TYPE,
                    content={"onboarded": True, "channel_id": channel_id},
                    user_id=user_id,
                    namespace=ONBOARDING_NAMESPACE,
                )
            except Exception as exc:
                log_debug(f"Onboarding marker save failed for {user_id}: {exc}")

    async def handle_session_stopped(self, event: dict) -> None:
        """Someone pressed Slack's stop button on a running session."""
        channel_id = event.get("channel") or ""
        thread_ts = event.get("thread_ts") or ""
        requested_by = event.get("user") or ""
        if not (channel_id and thread_ts):
            return
        run, allowed = await self.threads.request_stop(channel_id, thread_ts, requested_by or None)
        if run is None:
            # Nothing running here (already finished, or another worker owns it):
            # Slack leaves the session in processing until told otherwise
            await self.sessions.set_status(channel_id, thread_ts, "active")
            return
        if not allowed:
            # Slack already halted the streaming message for everyone; the run goes on
            # in a new one, and the presser learns why nothing stopped
            await self.sessions.set_status(channel_id, thread_ts, "processing", legacy_text=self.slack.loading_text)
            if requested_by:
                try:
                    await self.client.chat_postEphemeral(
                        channel=channel_id,
                        user=requested_by,
                        thread_ts=thread_ts,
                        text=f"Only <@{run.owner}> can stop this run.",
                    )
                except Exception as exc:
                    log_debug(f"chat.postEphemeral after refused stop failed: {exc}")

    async def handle_title_changed(self, event: dict) -> None:
        """The user renamed a session in Slack; mirror it onto the Agno session."""
        channel_id = event.get("channel") or ""
        thread_ts = event.get("thread_ts") or ""
        title = (event.get("title") or "").strip()
        if not (channel_id and thread_ts and title):
            return
        if title == (event.get("previous_title") or "").strip():
            return
        if self.threads.last_title(channel_id, thread_ts) == title:
            return  # our own rename echoed back
        self.threads.set_last_title(channel_id, thread_ts, title)
        session_id = await self.session_id_for(channel_id, thread_ts, event.get("user") or "")
        await self._rename_agno_session(session_id, title)

    async def handle_context_changed(self, event: dict) -> None:
        """Slack reports what the user is looking at (channel, thread, canvas, ...)."""
        thread_info = event.get("assistant_thread") or {}
        channel_id = thread_info.get("channel_id") or event.get("channel") or event.get("channel_id") or ""
        thread_ts = thread_info.get("thread_ts") or event.get("thread_ts") or ""
        context = thread_info.get("context") if thread_info else event.get("context")
        if channel_id:
            self.threads.set_context(channel_id, thread_ts, context if isinstance(context, dict) else None)
