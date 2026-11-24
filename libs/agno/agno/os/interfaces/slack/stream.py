from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Sequence, Tuple

from slack_sdk.errors import SlackApiError

from agno.os.interfaces.slack.helpers import send_slack_message_async, slack_error_code
from agno.utils.log import log_error

if TYPE_CHECKING:
    from agno.os.interfaces.slack.context import EventContext, SlackContext

# Slack cuts a stream at about 12,000 chars, so rotate before it
_STREAM_CHAR_BUDGET = 11_500
# Slack keeps the first 50 task cards of a message and silently drops the rest
_STREAM_CARD_LIMIT = 45
# Slack closes a stream 10 minutes after startStream, so a new message takes over at 9
_STREAM_ROTATE_SECONDS = 540.0

_CONTINUED_PREFIX = "_(continued)_\n"
# A code block cut by a rotation closes in the old message and reopens in the new one
_FENCE_CLOSE = "\n```"
_FENCE_OPEN = "```\n"

# Codes a stop may get for a stream Slack already ended
_ENDED_CODES = frozenset({"stopped_by_user", "message_not_in_streaming_state", "invalid_ts"})
# Codes a startStream gets for a recipient that cannot be streamed to, e.g. a user outside the channel
_RECIPIENT_CODES = frozenset(
    {"channel_type_not_supported", "user_not_found", "missing_recipient_user_id", "missing_recipient_team_id"}
)


class StreamStopped(Exception):
    """Slack refused an append because the user stopped the stream."""

    pass


class SlackStream:
    """One reply in Slack, across as many stream messages as Slack's limits need.

    The stream opens lazily on the first append. Text past the char budget, more cards than a message
    takes, and a stream about to reach its 10-minute lifetime each move the reply to a new message;
    cards still open in the old message close as complete there and reopen in the new one. Every call
    takes one lock, so the rotation timer and the run's own appends never interleave. A recipient Slack
    cannot stream to, e.g. a user outside the channel, gets the reply as plain messages instead.

    The chat.*Stream methods are called directly rather than through slack_sdk's ChatStream, whose buffer
    keeps text Slack refused and sends it again with the next call.
    """

    def __init__(
        self,
        client: Any,
        event_context: "EventContext",
        ctx: "SlackContext",
        recipient_user_id: Optional[str] = None,
    ) -> None:
        self._client = client
        self._event_context = event_context
        self._recipient_user_id = recipient_user_id or event_context.owner
        self._ctx = ctx
        self._lock = asyncio.Lock()
        self._ts: Optional[str] = None
        self._chars = 0
        self._text = ""
        self._prefix_chars = len(_CONTINUED_PREFIX)
        self._cards: Dict[str, Tuple[str, str]] = {}
        self._carried = 0
        self._pending = ""
        self._timer: Optional["asyncio.Task[Any]"] = None
        self._user_stopped = False
        self._closed = False
        self._fallback = False
        self._posted = False
        self.ended = False

    @property
    def opened(self) -> bool:
        return self._ts is not None or self._posted

    @property
    def closed(self) -> bool:
        return self._closed

    async def append(self, markdown_text: str = "", chunks: Optional[Sequence[Mapping[str, Any]]] = None) -> None:
        async with self._lock:
            if self._closed:
                return
            if self._user_stopped:
                raise StreamStopped()
            self._pending += markdown_text or ""
            if chunks or len(self._pending) >= self._ctx.buffer_size:
                await self._flush([dict(c) for c in chunks] if chunks else None)

    async def stop(
        self,
        markdown_text: Optional[str] = None,
        chunks: Optional[Sequence[Mapping[str, Any]]] = None,
        session_status: Optional[str] = None,
    ) -> None:
        """End the reply. Safe to call more than once and on a stream Slack already ended."""
        async with self._lock:
            if self._closed:
                return
            self._pending += markdown_text or ""
            # Without chunks, e.g. a Stop with no run state at hand, open cards close as complete, not failed
            closing = [dict(c) for c in chunks] if chunks else self._open_cards("complete", "stopped") or None
            flush_error: Optional[BaseException] = None
            try:
                if self._user_stopped:
                    return
                try:
                    if self._pending:
                        await self._flush(None)
                except StreamStopped:
                    return
                except Exception as e:
                    # The message is still ended below, so it does not keep streaming until Slack's cutoff
                    flush_error = e
                if self._ts is None and closing:
                    await self._send("", closing)
                    closing = None
                if self._fallback:
                    await self._post_fallback()
                if self._ts is not None:
                    self.ended = await self._close_message(self._ts, closing, session_status)
            except StreamStopped:
                pass
            finally:
                self._closed = True
                self._cancel_timer()
            if flush_error is not None:
                raise flush_error

    def close(self) -> None:
        """Release the timer of a reply that ends without a stop, e.g. on cancellation."""
        self._closed = True
        self._cancel_timer()

    async def _flush(self, chunks: Optional[List[Dict[str, Any]]]) -> None:
        text, self._pending = self._pending, ""
        new = {str(c.get("id")) for c in chunks or []} - set(self._cards)
        # A message that carried cards in rotates only when one of its cards stays behind, else all carry again
        if (
            new
            and len(self._cards) + len(new) > _STREAM_CARD_LIMIT
            and (not self._carried or len(self._open_cards("in_progress")) < len(self._cards))
        ):
            await self._rotate()
        while text:
            room = _STREAM_CHAR_BUDGET - len(_FENCE_CLOSE) - self._chars
            if len(text) <= room:
                await self._send(text, chunks)
                return
            if self._has_content():
                cut = text.rfind("\n", 0, room)
                if cut > 0:
                    await self._send(text[:cut], None)
                    text = text[cut:]
                await self._rotate()
                continue
            cut = text.rfind("\n", 0, room)
            if cut <= 0:
                cut = text.rfind(" ", 0, room)
            if cut <= 0:
                cut = room
            await self._send(text[:cut], None)
            text = text[cut:]
            await self._rotate()
        if chunks:
            await self._send("", chunks)

    def _has_content(self) -> bool:
        # A continued message starts with its prefix and carried cards; anything past that is content
        return self._chars > self._prefix_chars or (self._ts is not None and self._chars == 0 and bool(self._cards))

    async def _send(self, text: str, chunks: Optional[List[Dict[str, Any]]], *, reopened: bool = False) -> None:
        try:
            await self._call(text, chunks)
        except SlackApiError as e:
            code = slack_error_code(e)
            if code == "stopped_by_user":
                self._user_stopped = True
                raise StreamStopped() from e
            if code == "message_not_in_streaming_state" and self._ts is not None:
                if self._ctx.runs.was_stopped(self._event_context.run_id):
                    self._user_stopped = True
                    raise StreamStopped() from e
                if reopened:
                    raise
                # Slack ended the stream, e.g. at its 10-minute cutoff: its message is final, so continue in a new one
                await self._start_continuation()
                await self._send(text, chunks, reopened=True)
                return
            if code == "msg_too_long":
                if self._has_content():
                    # Nothing of the refused call was kept, so it goes again, whole, in a new message
                    await self._rotate()
                    await self._send(text, chunks)
                    return
                if len(text) > 1:
                    half = len(text) // 2
                    await self._send(text[:half], None)
                    await self._send(text[half:], chunks)
                    return
            raise

    async def _call(self, text: str, chunks: Optional[List[Dict[str, Any]]]) -> None:
        payload: List[Dict[str, Any]] = [{"type": "markdown_text", "text": text}] if text else []
        payload += chunks or []
        if self._ts is None and not self._fallback:
            try:
                response = await self._client.chat_startStream(
                    channel=self._event_context.channel,
                    thread_ts=self._event_context.thread_ts,
                    recipient_team_id=self._event_context.team_id,
                    recipient_user_id=self._recipient_user_id,
                    task_display_mode=self._ctx.task_display_mode,
                    chunks=payload,
                )
            except SlackApiError as e:
                if slack_error_code(e) not in _RECIPIENT_CODES:
                    raise
                # The recipient cannot get a stream, so the rest of the reply posts as plain messages
                self._fallback = True
                self._prefix_chars = 0
            else:
                self._ts = str(response["ts"])
                self._ctx.runs.attach_ts(self._event_context.run_id, self._ts)
                if self._ts not in self._event_context.streaming_message_ts:
                    self._event_context.streaming_message_ts.append(self._ts)
                if not self._closed:
                    self._timer = self._ctx.runs.spawn(self._expire_after(_STREAM_ROTATE_SECONDS))
        elif self._ts is not None:
            await self._client.chat_appendStream(channel=self._event_context.channel, ts=self._ts, chunks=payload)
        self._chars += len(text)
        self._text += text
        if self._fallback:
            # Task cards exist only in a stream, so a plain-message reply keeps the text and drops them
            return
        for chunk in chunks or []:
            self._cards[str(chunk.get("id"))] = (str(chunk.get("title", "")), str(chunk.get("status", "")))

    def _open_cards(self, status: str, suffix: str = "") -> List[Dict[str, Any]]:
        # The cards this message last showed as in progress, whatever the run has marked since
        cards = []
        for card_id, (title, sent_status) in self._cards.items():
            if sent_status == "in_progress":
                shown = f"{title}: {suffix}" if suffix else title
                cards.append({"type": "task_update", "id": card_id, "title": shown, "status": status})
        return cards

    async def _rotate(self) -> None:
        """Finish the current message and continue the reply in a new one."""
        if self._fallback:
            await self._post_fallback()
            return
        carried = self._open_cards("in_progress")
        fenced = self._fence_open()
        if self._ts is not None:
            if fenced:
                try:
                    await self._call(_FENCE_CLOSE, None)
                except SlackApiError:
                    # The stop below still ends the message and handles a user stop
                    pass
            # Open cards would show as failed in a stopped message, so they close as complete here
            await self._close_message(self._ts, self._open_cards("complete", "continued below") or None, "processing")
        await self._start_continuation(carried, fenced)

    async def _start_continuation(
        self, carried: Optional[List[Dict[str, Any]]] = None, fenced: Optional[bool] = None
    ) -> None:
        if carried is None:
            carried = self._open_cards("in_progress")
        if fenced is None:
            fenced = self._fence_open()
        prefix = _CONTINUED_PREFIX + _FENCE_OPEN if fenced else _CONTINUED_PREFIX
        self._cancel_timer()
        self._ts = None
        self._chars = 0
        self._text = ""
        self._prefix_chars = len(prefix)
        self._cards = {}
        self._carried = len(carried or [])
        await self._call(prefix, carried or None)

    async def _post_fallback(self) -> None:
        text, self._text = self._text, ""
        self._chars = 0
        if not text.strip():
            return
        await send_slack_message_async(
            self._client,
            channel=self._event_context.channel,
            thread_ts=self._event_context.thread_ts,
            message=text,
            unfurl_links=self._ctx.unfurl_links,
            unfurl_media=self._ctx.unfurl_media,
            mrkdwn=self._ctx.markdown,
        )
        self._posted = True

    def _fence_open(self) -> bool:
        # An odd number of ``` lines in this message leaves a code block open
        return sum(line.startswith("```") for line in self._text.split("\n")) % 2 == 1

    async def _close_message(
        self, ts: str, chunks: Optional[List[Dict[str, Any]]], session_status: Optional[str]
    ) -> bool:
        """Stop a message, falling back to no session status and then to a bare stop; True when it ended here."""
        attempts = [(chunks, session_status)]
        if session_status:
            attempts.append((chunks, None))
        if chunks:
            attempts.append((None, None))
        last_error: Optional[SlackApiError] = None
        for attempt_chunks, attempt_status in attempts:
            try:
                kwargs: Dict[str, Any] = {"session_status": attempt_status} if attempt_status else {}
                await self._client.chat_stopStream(
                    channel=self._event_context.channel, ts=ts, chunks=attempt_chunks, **kwargs
                )
                return True
            except SlackApiError as e:
                code = slack_error_code(e)
                if code == "stopped_by_user":
                    self._user_stopped = True
                    raise StreamStopped() from e
                if code in _ENDED_CODES:
                    # A stream Slack already ended leaves the status to the caller
                    return False
                last_error = e
        assert last_error is not None
        raise last_error

    async def _expire_after(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        async with self._lock:
            if self._closed or self._user_stopped:
                return
            self._timer = None
            try:
                await self._rotate()
            except StreamStopped:
                pass
            except Exception as e:
                log_error(f"Slack stream rotation failed: {str(e)}")

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
