import time
from collections import OrderedDict
from ssl import SSLContext
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import NAMESPACE_URL, uuid5

import httpx

from agno.exceptions import InputCheckError, UnsupportedMediaError
from agno.media import Audio, File, Image, Video
from agno.utils.log import log_error, log_warning

DEFAULT_SUGGESTED_PROMPTS: List[Dict[str, str]] = [{"title": "Get started", "message": "What can you help me with?"}]
# Slack error codes a users.info or bots.info lookup fails with on every attempt: no users:read scope,
# no such user, no such bot, or a token whose own user or workspace is deactivated
_PERMANENT_LOOKUP_ERRORS = frozenset({"missing_scope", "user_not_found", "bot_not_found", "account_inactive"})


def slack_error_code(exc: BaseException) -> Optional[str]:
    # Extracts Slack API error code from exception for logging/handling
    resp = getattr(exc, "response", None)
    data = getattr(resp, "data", None) if resp else None
    if isinstance(data, dict):
        code = data.get("error")
        if isinstance(code, str):
            return code
    return None


def run_error_reply(exc: BaseException, fallback: str, unsupported_files: str) -> str:
    # A media refusal names the adapter class, so it gets a plain line; other input checks say what to change
    if isinstance(exc, UnsupportedMediaError):
        return unsupported_files
    if isinstance(exc, InputCheckError):
        return str(exc)
    return fallback


async def resolve_session_id(
    entity: Any, entity_id: str, channel_id: str, thread_ts: str, cache: Optional["LookupCache"] = None
) -> str:
    # New format includes channel_id to prevent cross-channel collisions
    session_id = f"{entity_id}:{channel_id}:{thread_ts}"
    # Remote entities keep no local sessions, so there is no legacy session to find
    if not hasattr(entity, "aget_session"):
        return session_id
    key = f"session:{entity_id}:{channel_id}:{thread_ts}"
    if cache is not None:
        cached = cache.get(key)
        if cached is not None:
            return cached
    # Sessions created before channel-scoped keys used "{entity_id}:{thread_ts}".
    # Probe for existing legacy session so an upgrade doesn't orphan history.
    legacy_id = f"{entity_id}:{thread_ts}"
    try:
        session = await entity.aget_session(session_id=legacy_id)
    except Exception:
        # A failed probe is not cached, so the next message probes again
        return session_id
    if session is not None:
        session_id = legacy_id
    if cache is not None:
        cache.set(key, session_id)
    return session_id


def task_id(agent_name: Optional[str], base_id: str) -> str:
    # Prefix card IDs per agent so concurrent tool calls from different
    # team members don't collide in the Slack stream
    if agent_name:
        safe = agent_name.lower().replace(" ", "_")[:20]
        return f"{safe}_{base_id}"
    return base_id


def member_name(chunk: Any, entity_name: str) -> Optional[str]:
    # Return name only for team members (not leader) to prefix task card
    # labels like "Researcher: web_search" for disambiguation
    name = getattr(chunk, "agent_name", None)
    if name and isinstance(name, str) and name != entity_name:
        return name
    return None


def should_respond(event: dict, reply_to_mentions_only: bool) -> bool:
    event_type = event.get("type")
    if event_type not in ("app_mention", "message"):
        return False
    channel_type = event.get("channel_type", "")
    is_dm = channel_type == "im"
    if reply_to_mentions_only and event_type == "message" and not is_dm:
        return False
    # When responding to all messages, skip app_mention to avoid duplicates.
    # Slack fires both app_mention and message for the same @mention — the
    # message event already covers it.
    if not reply_to_mentions_only and event_type == "app_mention" and not is_dm:
        return False
    return True


def build_run_metadata(
    display_name: Optional[str],
    resolved_user_id: str,
    ctx: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    metadata: Dict[str, Any] = {}
    if display_name:
        metadata["user_name"] = display_name
        metadata["user_id"] = resolved_user_id
    if ctx.get("action_token"):
        metadata["action_token"] = ctx["action_token"]
    if ctx.get("message_ts"):
        metadata["slack_message_ts"] = ctx["message_ts"]
    return metadata or None


def extract_event_context(event: dict) -> Dict[str, Any]:
    return {
        "message_text": event.get("text", ""),
        "channel_id": event.get("channel", ""),
        # Human sender ID (U.../W...) — empty for webhook/legacy bot messages
        "user": event.get("user") or "",
        # Bot sender ID (B...) — present on all bot-authored messages
        "bot_id": event.get("bot_id") or "",
        # Prefer existing thread; fall back to message ts for new conversations
        "thread_id": event.get("thread_ts") or event.get("ts", ""),
        # User-scoped token for assistant.search.context workspace search
        "action_token": (event.get("assistant_thread") or {}).get("action_token") or event.get("action_token"),
    }


def strip_bot_mention(text: str, bot_user_id: Optional[str], bot_name: Optional[str] = None) -> str:
    """Replace the bot's own @mention with its display name (or remove if no name).

    Slack encodes mentions as ``<@U123>``. When a user @-mentions the bot,
    the agent shouldn't see its own ID in the text — it just adds noise and
    causes the model to echo back the raw mention tag.

    If bot_name is provided, the mention is replaced with that name so the
    agent sees "hi Scout" instead of "hi " when the user types "hi @Scout".

    Only processes the *bot's* mention; other users' mentions are preserved.
    """
    if not bot_user_id or not text:
        return text
    import re

    replacement = f" {bot_name} " if bot_name else " "
    return re.sub(rf"\s*<@{re.escape(bot_user_id)}>\s*", replacement, text).strip()


async def resolve_slack_user(
    async_client: Any, slack_user_id: str, errors: Optional[Set[str]] = None
) -> Tuple[str, Optional[str]]:
    """Resolve a Slack user ID to (canonical_user_id, display_name).

    Returns the user's email as canonical_user_id if available, otherwise
    falls back to the raw Slack user ID. Display name is best-effort.
    """
    try:
        resp = await async_client.users_info(user=slack_user_id)
        user = resp.get("user", {}) if resp else {}
        profile = user.get("profile", {})

        email = profile.get("email")
        resolved_id = email if email else slack_user_id

        display_name = profile.get("display_name") or profile.get("real_name") or user.get("name") or None
        if display_name is not None and not display_name.strip():
            display_name = None

        return (resolved_id, display_name)
    except Exception as e:
        log_warning(f"Failed to resolve Slack user {slack_user_id}: {str(e)}")
        # The Slack error code ("" for a network error), so a caller can tell a permanent failure apart
        if errors is not None:
            errors.add(slack_error_code(e) or "")
        return (slack_user_id, None)


async def resolve_slack_bot(
    async_client: Any, bot_id: str, errors: Optional[Set[str]] = None
) -> Tuple[str, Optional[str]]:
    try:
        resp = await async_client.bots_info(bot=bot_id)
        bot = resp.get("bot", {}) if resp else {}
        return (bot_id, bot.get("name") or None)
    except Exception as e:
        log_warning(f"Failed to resolve Slack bot {bot_id}: {str(e)}")
        if errors is not None:
            errors.add(slack_error_code(e) or "")
        return (bot_id, None)


class BotNameResolver:
    """Resolves a Slack bot user ID to its display name with per-instance caching.

    Each Slack interface holds one on its SlackContext, reused when its routes are
    built again, so it keeps its own cache without polluting module-level state.
    Only successful lookups are cached — transient API failures are retried on
    the next message.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, str] = {}

    async def resolve(self, async_client: Any, bot_user_id: str) -> Optional[str]:
        if bot_user_id in self._cache:
            return self._cache[bot_user_id]

        try:
            resp = await async_client.users_info(user=bot_user_id)
            user = resp.get("user", {}) if resp else {}
            profile = user.get("profile", {})

            name = profile.get("display_name") or profile.get("real_name") or user.get("name") or None
            if name is not None and not name.strip():
                name = None

            if name is not None:
                self._cache[bot_user_id] = name
            return name
        except Exception as e:
            log_warning(f"Failed to resolve bot name for {bot_user_id}: {str(e)}")
            return None


class EventDeduplicator:
    """Remembers recently seen Slack event_ids so a retried delivery runs at most once.

    Slack retries any event not acked within 3s (immediately, then +1 min, then +5 min),
    marking each with X-Slack-Retry-Num. A retry is only a duplicate if the original
    delivery reached us, so the route dedupes on event_id instead of dropping every retry.
    Each Slack interface holds one on its SlackContext, reused when its routes are built again.

    The seen-set is per-process. With several uvicorn workers or replicas, a retry that
    lands on a different process is not recognised and the event runs a second time,
    tool side effects included. Run one process per Slack app or add a shared store.
    """

    # Must outlive Slack's final retry at +5 minutes
    DEDUP_TTL_SECONDS: float = 600.0
    DEDUP_MAX_ENTRIES: int = 4096

    def __init__(self) -> None:
        self._seen: "OrderedDict[str, float]" = OrderedDict()

    def is_duplicate(self, event_id: str) -> bool:
        now = time.monotonic()
        expired = [eid for eid, ts in self._seen.items() if now - ts > self.DEDUP_TTL_SECONDS]
        for eid in expired:
            del self._seen[eid]
        if event_id in self._seen:
            return True
        self._seen[event_id] = now
        # Bounded: under heavy traffic the oldest id is evicted before its TTL, so a late
        # retry of it is reprocessed as a duplicate run. Every signed event that reaches the
        # route takes a slot, including ones that never start a run. Accepted over unbounded growth.
        while len(self._seen) > self.DEDUP_MAX_ENTRIES:
            self._seen.popitem(last=False)
        return False


class LookupCache:
    """Remembers recent Slack lookups (channel names, user identities, session ids) so a message skips the call.

    Entries expire so a renamed channel or a changed email is picked up again; only successful
    lookups are cached, except a sender name that can never be looked up (no users:read scope,
    no such user or bot). Instantiated once per mounted Slack interface.
    """

    LOOKUP_TTL_SECONDS: float = 600.0
    LOOKUP_MAX_ENTRIES: int = 4096

    def __init__(self) -> None:
        self._entries: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()

    def get(self, key: str) -> Optional[Any]:
        now = time.monotonic()
        expired = [k for k, (ts, _) in self._entries.items() if now - ts > self.LOOKUP_TTL_SECONDS]
        for k in expired:
            del self._entries[k]
        entry = self._entries.get(key)
        return entry[1] if entry is not None else None

    def set(self, key: str, value: Any) -> None:
        self._entries[key] = (time.monotonic(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.LOOKUP_MAX_ENTRIES:
            self._entries.popitem(last=False)

    async def channel_name(self, async_client: Any, channel_id: str) -> Optional[str]:
        key = f"channel:{channel_id}"
        name = self.get(key)
        if name is None:
            name = await resolve_channel_name(async_client, channel_id)
            if name is not None:
                self.set(key, name)
        return name

    async def user_identity(
        self, async_client: Any, slack_user_id: str, errors: Optional[Set[str]] = None
    ) -> Tuple[str, Optional[str]]:
        key = f"user:{slack_user_id}"
        cached = self.get(key)
        if cached is not None:
            return cached
        resolved_user_id, display_name = await resolve_slack_user(async_client, slack_user_id, errors)
        # resolve_slack_user falls back to the raw id on failure; only real lookups are kept
        if resolved_user_id != slack_user_id or display_name:
            self.set(key, (resolved_user_id, display_name))
        return resolved_user_id, display_name

    async def bot_identity(
        self, async_client: Any, bot_id: str, errors: Optional[Set[str]] = None
    ) -> Tuple[str, Optional[str]]:
        key = f"bot:{bot_id}"
        cached = self.get(key)
        if cached is not None:
            return cached
        resolved_id, name = await resolve_slack_bot(async_client, bot_id, errors)
        if name:
            self.set(key, (resolved_id, name))
        return resolved_id, name

    async def sender_name(self, async_client: Any, user_id: str, bot_id: str) -> Optional[str]:
        # A user-token post carries both ids; the human is the sender, as for the run's owner
        sender = user_id or bot_id
        if not sender:
            return None
        key = f"name:{sender}"
        name = self.get(key)
        if name is None:
            errors: Set[str] = set()
            if user_id:
                _, name = await self.user_identity(async_client, user_id, errors)
            else:
                _, name = await self.bot_identity(async_client, bot_id, errors)
            # An unknown name is kept only after a permanent failure, so an app without users:read is not
            # looked up on every message while a rate limit or network error is retried on the next one
            if errors <= _PERMANENT_LOOKUP_ERRORS:
                self.set(key, name or "")
        return name or None


async def resolve_channel_name(async_client: Any, channel_id: str) -> Optional[str]:
    """Resolve a Slack channel ID to its human-readable name."""
    try:
        resp = await async_client.conversations_info(channel=channel_id)
        channel = resp.get("channel", {}) if resp else {}
        # API returns "" for unnamed channels; normalize to None
        return channel.get("name") or None
    except Exception as e:
        log_warning(f"Failed to resolve channel name for {channel_id}: {str(e)}")
        return None


async def download_event_files_async(
    token: str, event: dict, max_file_size: int, ssl: Optional[SSLContext] = None
) -> Tuple[List[File], List[Image], List[Video], List[Audio], List[str]]:
    files: List[File] = []
    images: List[Image] = []
    videos: List[Video] = []
    audio: List[Audio] = []
    skipped: List[str] = []

    if not event.get("files"):
        return files, images, videos, audio, skipped

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(verify=ssl if ssl is not None else True) as client:
        for file_info in event["files"]:
            file_id = file_info.get("id")
            filename = file_info.get("name", "file")
            mimetype = file_info.get("mimetype", "application/octet-stream")
            # Slack sends "size": null for some files
            file_size = file_info.get("size") or 0

            if file_size > max_file_size:
                limit_mb = max_file_size / (1024 * 1024)
                actual_mb = file_size / (1024 * 1024)
                skipped.append(f"{filename} ({actual_mb:.1f}MB — exceeds {limit_mb:.0f}MB limit)")
                continue

            # Slack redirects url_private for some files (e.g. PDFs); url_private_download serves the bytes
            download_url = file_info.get("url_private_download") or file_info.get("url_private")
            if not download_url:
                continue

            try:
                resp = await client.get(download_url, headers=headers, timeout=30)
                resp.raise_for_status()
                file_content = resp.content

                if mimetype.startswith("image/"):
                    fmt = mimetype.split("/")[-1]
                    images.append(Image(content=file_content, id=file_id, mime_type=mimetype, format=fmt))
                elif mimetype.startswith("video/"):
                    videos.append(Video(content=file_content, mime_type=mimetype))
                elif mimetype.startswith("audio/"):
                    audio.append(Audio(content=file_content, mime_type=mimetype))
                else:
                    # Pass None for unsupported types to avoid File validation errors
                    safe_mime = mimetype if mimetype in File.valid_mime_types() else None
                    files.append(File(content=file_content, filename=filename, mime_type=safe_mime))
            except Exception as e:
                log_error(f"Failed to download file {file_id}: {str(e)}")

    return files, images, videos, audio, skipped


async def upload_response_media_async(async_client: Any, response: Any, channel_id: str, thread_ts: str) -> None:
    media_attrs = [
        ("images", "image.png"),
        ("files", "file"),
        ("videos", "video.mp4"),
        ("audio", "audio.mp3"),
    ]
    for attr, default_name in media_attrs:
        items = getattr(response, attr, None)
        if not items:
            continue
        for item in items:
            # Fetching a URL-backed item can fail; the answer is already posted, so log and go on
            try:
                content_bytes = item.get_content_bytes()
                if content_bytes:
                    await async_client.files_upload_v2(
                        channel=channel_id,
                        content=content_bytes,
                        filename=getattr(item, "filename", None) or default_name,
                        thread_ts=thread_ts,
                    )
            except Exception as e:
                log_error(f"Failed to upload {attr.rstrip('s')}: {str(e)}")


async def post_ephemeral(client: Any, channel: str, user: str, text: str, thread_ts: Optional[str] = None) -> None:
    try:
        await client.chat_postEphemeral(channel=channel, user=user, text=text, thread_ts=thread_ts)
    except Exception as exc:
        log_error(f"[HITL] chat_postEphemeral failed: {exc}")


async def update_message(client: Any, channel: str, ts: str, text: str, blocks: List[Dict[str, Any]]) -> bool:
    try:
        await client.chat_update(channel=channel, ts=ts, text=text, blocks=blocks)
        return True
    except Exception as exc:
        log_error(f"[HITL] chat_update failed for ts={ts}: {exc}")
        return False


async def delete_awaiting_indicator(client: Any, channel: str, awaiting_ts: Optional[str]) -> None:
    # The thread root is never a fallback: deleting it would remove the user's message
    if not awaiting_ts:
        return
    try:
        await client.chat_delete(channel=channel, ts=awaiting_ts)
    except Exception as exc:
        if "message_not_found" not in str(exc):
            log_error(f"[HITL] chat_delete (awaiting indicator) failed for ts={awaiting_ts}: {exc}")


def slack_delivery_kwargs(unfurl_links: bool, unfurl_media: bool, mrkdwn: bool) -> Dict[str, Any]:
    # mrkdwn=False means plaintext delivery: parse="none" stops Slack from
    # linkifying bare URLs and link_names=False stops bare @name expansion. Note
    # this does NOT neutralize control sequences already encoded as `<!channel>`
    # / `<@U123>` — only parse="full" escapes those. Card bodies inert those
    # characters directly (see builders.inert_code_span_text); the plain message
    # path relies on the model not emitting pre-encoded sequences.
    kwargs: Dict[str, Any] = {"unfurl_links": unfurl_links, "unfurl_media": unfurl_media, "mrkdwn": mrkdwn}
    if not mrkdwn:
        kwargs["parse"] = "none"
        kwargs["link_names"] = False
    return kwargs


async def send_slack_message_async(
    async_client: Any,
    channel: str,
    thread_ts: str,
    message: str,
    italics: bool = False,
    unfurl_links: bool = True,
    unfurl_media: bool = True,
    mrkdwn: bool = True,
) -> None:
    if not message or not message.strip():
        return

    def _format(text: str) -> str:
        if italics:
            return "\n".join([f"_{line}_" for line in text.split("\n")])
        return text

    delivery = slack_delivery_kwargs(unfurl_links, unfurl_media, mrkdwn)

    # Under Slack's 40K char limit with margin for batch prefix overhead
    max_len = 39900
    if len(message) <= max_len:
        await async_client.chat_postMessage(channel=channel, text=_format(message), thread_ts=thread_ts, **delivery)
        return

    message_batches = [message[i : i + max_len] for i in range(0, len(message), max_len)]
    for i, batch in enumerate(message_batches, 1):
        batch_message = f"[{i}/{len(message_batches)}] {batch}"
        await async_client.chat_postMessage(
            channel=channel, text=_format(batch_message), thread_ts=thread_ts, **delivery
        )


def slack_run_id(team_id: str, entity_id: str, channel_id: str, message_ts: str) -> str:
    # One run per message and entity: a redelivery, a paired app_mention or a second app serving it shares the run
    return str(uuid5(NAMESPACE_URL, f"agno:slack:{team_id}:{entity_id}:{channel_id}:{message_ts}"))


async def start_status(
    async_client: Any, channel: str, thread_ts: str, loading_text: str, loading_messages: Optional[List[str]] = None
) -> None:
    status_kwargs: Dict[str, Any] = {"channel_id": channel, "thread_ts": thread_ts, "status": loading_text}
    if loading_messages:
        status_kwargs["loading_messages"] = loading_messages
    try:
        await async_client.assistant_threads_setStatus(**status_kwargs)
    except Exception:
        pass


async def clear_status(async_client: Any, channel: str, thread_ts: str) -> None:
    # For paths where no stopStream ends the status
    try:
        await async_client.assistant_threads_setStatus(channel_id=channel, thread_ts=thread_ts, status="")
    except Exception:
        pass


async def set_title(async_client: Any, channel: str, thread_ts: str, text: str) -> None:
    title = text[:50].strip() or "New conversation"
    try:
        await async_client.assistant_threads_setTitle(channel_id=channel, thread_ts=thread_ts, title=title)
    except Exception:
        pass


async def set_suggested_prompts(
    async_client: Any, channel: str, thread_ts: Optional[str] = None, prompts: Optional[List[Dict[str, str]]] = None
) -> None:
    # Without thread_ts the prompts apply to the agent view's Messages tab
    prompt_kwargs: Dict[str, Any] = {"channel_id": channel, "prompts": prompts or DEFAULT_SUGGESTED_PROMPTS}
    if thread_ts:
        prompt_kwargs["thread_ts"] = thread_ts
    try:
        await async_client.assistant_threads_setSuggestedPrompts(**prompt_kwargs)
    except Exception as e:
        log_error(f"Failed to set suggested prompts: {str(e)}")
