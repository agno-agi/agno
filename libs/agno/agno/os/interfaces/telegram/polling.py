"""
Long-polling transport for the Telegram interface.

An alternative to webhook mode that does **not** require a public URL,
TLS certificates, or a FastAPI server.  Perfect for local development
and setups behind NAT / Tailscale.
"""

import asyncio
import json

from agno.os.interfaces.telegram.processor import TelegramMessageProcessor
from agno.utils.log import log_error, log_info


class TelegramPolling:
    """Runs a Telegram bot in long-polling mode.

    Usage::

        poller = TelegramPolling(processor=my_processor)
        await poller.start()          # blocks until stopped
        # or
        asyncio.run(poller.start())
    """

    def __init__(self, processor: TelegramMessageProcessor):
        self.processor = processor
        self._running = False
        self._tasks: set = set()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start long-polling. Blocks until :meth:`stop` is called or
        an unrecoverable error occurs. Closes the bot's HTTP session on exit."""
        self._running = True
        bot = self.processor.bot
        offset: int = 0
        timeout = 30  # seconds per long-poll request

        log_info("Telegram polling started")

        try:
            while self._running:
                try:
                    updates = await bot.get_updates(offset=offset, timeout=timeout)
                except Exception as e:
                    log_error(f"Polling error: {e}")
                    await asyncio.sleep(5)
                    continue

                for update in updates:
                    # Advance offset to acknowledge this update
                    offset = update.update_id + 1

                    message = None
                    if hasattr(update, "message") and update.message:
                        message = _message_to_dict(update.message)
                    elif hasattr(update, "edited_message") and update.edited_message:
                        message = _message_to_dict(update.edited_message)

                    if message is None:
                        continue

                    # Process in the background so we don't block the poll loop;
                    # keep a reference so the task is not garbage-collected mid-run.
                    task = asyncio.create_task(self._safe_process(message))
                    self._tasks.add(task)
                    task.add_done_callback(self._tasks.discard)
        finally:
            await bot.close_session()
            log_info("Telegram polling stopped")

    def stop(self) -> None:
        """Signal the poll loop to exit."""
        self._running = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _safe_process(self, message: dict) -> None:
        try:
            await self.processor.process_message(message)
        except Exception as e:
            log_error(f"Unhandled error in polling message handler: {e}")


# ------------------------------------------------------------------
# Conversion helper — telebot Message → dict
# ------------------------------------------------------------------


def _message_to_dict(msg) -> dict:
    """Convert a ``telebot.types.Message`` to a plain dict.

    The processor's ``process_message`` expects the same JSON structure
    that Telegram sends in webhook payloads, so we serialise the object
    back to its raw dict form.
    """
    # pyTelegramBotAPI Message objects expose ``.json`` — either a method
    # returning the raw API response as a JSON string, or the raw dict itself
    # (varies by version). Handle both.
    raw = getattr(msg, "json", None)
    if callable(raw):
        return json.loads(raw())
    if isinstance(raw, dict):
        return raw

    # Last resort: manual conversion of the fields the processor reads
    result: dict = {}
    if msg.chat:
        result["chat"] = {"id": msg.chat.id, "type": getattr(msg.chat, "type", "private")}
    if msg.from_user:
        result["from"] = {
            "id": msg.from_user.id,
            "is_bot": getattr(msg.from_user, "is_bot", False),
        }
    if hasattr(msg, "message_id"):
        result["message_id"] = msg.message_id
    if hasattr(msg, "message_thread_id") and msg.message_thread_id:
        result["message_thread_id"] = msg.message_thread_id
    if hasattr(msg, "text") and msg.text:
        result["text"] = msg.text
    if hasattr(msg, "caption") and msg.caption:
        result["caption"] = msg.caption
    # Media fields
    for field in ("photo", "audio", "voice", "video", "document", "sticker"):
        val = getattr(msg, field, None)
        if val:
            result[field] = _serialise_media(val)
    if hasattr(msg, "reply_to_message") and msg.reply_to_message:
        rt = msg.reply_to_message
        result["reply_to_message"] = {"from": {"id": rt.from_user.id}} if rt.from_user else {}
    # Entities (for mention detection)
    if hasattr(msg, "entities") and msg.entities:
        result["entities"] = [{"type": e.type, "offset": e.offset, "length": e.length} for e in msg.entities]
    return result


def _serialise_media(val):
    """Convert media objects to dicts that match the webhook JSON shape."""
    if isinstance(val, list):
        return [_serialise_media(item) for item in val]
    if isinstance(val, dict):
        return val
    if hasattr(val, "file_id"):
        d: dict = {"file_id": val.file_id}
        if hasattr(val, "file_size") and val.file_size:
            d["file_size"] = val.file_size
        if hasattr(val, "file_name") and val.file_name:
            d["file_name"] = val.file_name
        return d
    return val
