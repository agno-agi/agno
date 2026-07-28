"""Shared Discord processing machinery used by both the Interactions router and the Gateway router.

Everything here speaks Discord REST with a bot token — no interaction tokens, no
gateway connection — so both transports (and a future external relay) can reuse it.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

import httpx

from agno.media import Audio, File, Image, Video
from agno.os.interfaces.discord.constants import (
    DISCORD_API,
    MAX_MESSAGE_LENGTH,
    MAX_THREAD_NAME_LENGTH,
)
from agno.os.interfaces.discord.state import (
    SessionStoreConfig,
    find_latest_session_id,
)
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_warning

# Event names emitted by agents (and their Team-prefixed siblings)
TOOL_STARTED_EVENTS = {"ToolCallStarted", "TeamToolCallStarted"}
TOOL_ENDED_EVENTS = {"ToolCallCompleted", "TeamToolCallCompleted", "ToolCallError", "TeamToolCallError"}

STATUS_THINKING = "Thinking..."

# Minimum seconds between tool-status edits — Discord's per-channel bucket is
# roughly 5 requests / 5s, so rapid tool chains must not PATCH on every event.
# The final answer is never debounced.
STATUS_EDIT_MIN_INTERVAL = 1.5

# 429 retry policy for Discord REST calls
MAX_RATE_LIMIT_RETRIES = 3
MAX_RETRY_AFTER_SECONDS = 30.0

StatusEdit = Callable[[str], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# Discord REST
# ---------------------------------------------------------------------------


async def discord_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json_body: Optional[Any] = None,
) -> Optional[httpx.Response]:
    """Single choke point for Discord REST calls.

    Honors 429 rate limits by waiting out ``Retry-After`` (up to
    ``MAX_RATE_LIMIT_RETRIES`` attempts) — un-retried 429s lose messages and
    feed Discord's invalid-request counter, which can Cloudflare-ban the host.
    Logs non-2xx responses. Returns the final response, or None on transport
    failure (never raises).
    """
    resp: Optional[httpx.Response] = None
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            resp = await client.request(method, url, headers=headers, json=json_body)
        except httpx.HTTPError as e:
            log_warning(f"Discord API {method} {url} transport error: {e}")
            return None
        if resp.status_code != 429:
            break
        if attempt == MAX_RATE_LIMIT_RETRIES:
            log_warning(f"Discord API {method} {url} still rate limited after {attempt} retries")
            break
        retry_after = 1.0
        try:
            retry_after = float(resp.headers.get("Retry-After") or resp.json().get("retry_after") or 1.0)
        except Exception:
            pass
        await asyncio.sleep(min(retry_after, MAX_RETRY_AFTER_SECONDS))
    if resp is not None and resp.status_code >= 400:
        log_warning(f"Discord API {method} {url} failed: {resp.status_code} {resp.text[:200]}")
    return resp


_background_tasks: Set["asyncio.Task[Any]"] = set()


def run_in_background(coro: Coroutine[Any, Any, Any]) -> "asyncio.Task[Any]":
    """create_task with a strong reference — asyncio only keeps weak refs, so
    fire-and-forget tasks can otherwise be garbage collected mid-run."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


# ---------------------------------------------------------------------------
# Text/media helpers
# ---------------------------------------------------------------------------


def resolve_media(content_type: str, url: str) -> Dict[str, Any]:
    if content_type.startswith("image/"):
        return {"images": [Image(url=url)]}
    if content_type.startswith("audio/"):
        return {"audio": [Audio(url=url)]}
    if content_type.startswith("video/"):
        return {"videos": [Video(url=url)]}
    return {"files": [File(url=url)]}


def format_attribution(user_name: str, message: str, max_len: int = MAX_MESSAGE_LENGTH) -> str:
    prefix = f"{user_name}: "
    remaining = max_len - len(prefix)
    if remaining <= 0:
        # User name alone blew the cap (pathological) — just truncate the whole line
        return f"{user_name}: {message}"[:max_len]
    if len(message) > remaining:
        # Trim message with an ellipsis so the attribution still reads as a quote
        message = message[: remaining - 1].rstrip() + "…"
    return f"{prefix}{message}"


def thread_name_from_question(question: str) -> str:
    name = " ".join(question.split()).strip() or "Conversation"
    return name[:MAX_THREAD_NAME_LENGTH]


def chunk_text(text: str, max_len: int = MAX_MESSAGE_LENGTH) -> List[str]:
    if not text:
        return ["(empty)"]
    if len(text) <= max_len:
        return [text]
    chunks: List[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, max_len)
        if cut <= 0:
            cut = max_len
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return chunks


def format_tool_status(active: "OrderedDict[str, str]") -> str:
    names = list(active.values())
    if not names:
        return STATUS_THINKING
    if len(names) == 1:
        return f"Running tool: {names[0]}..."
    return f"Running: {', '.join(names)}..."


# ---------------------------------------------------------------------------
# Channel REST operations (bot-token auth)
# ---------------------------------------------------------------------------


async def post_in_channel(
    client: httpx.AsyncClient, bot_headers: Dict[str, str], channel_id: str, content: str
) -> Optional[str]:
    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    body = content[:MAX_MESSAGE_LENGTH] or "(empty)"
    resp = await discord_request(client, "POST", url, headers=bot_headers, json_body={"content": body})
    if resp is not None and resp.status_code in (200, 201):
        return resp.json().get("id")
    return None


async def edit_channel_message(
    client: httpx.AsyncClient, bot_headers: Dict[str, str], channel_id: str, message_id: str, content: str
) -> None:
    url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}"
    body = content[:MAX_MESSAGE_LENGTH] or "(empty)"
    await discord_request(client, "PATCH", url, headers=bot_headers, json_body={"content": body})


async def trigger_typing(client: httpx.AsyncClient, bot_headers: Dict[str, str], channel_id: str) -> None:
    """Show the native 'Bot is typing...' indicator (lasts up to 10 seconds).

    Typing is cosmetic — discord_request never raises, so this can't break a run.
    """
    url = f"{DISCORD_API}/channels/{channel_id}/typing"
    await discord_request(client, "POST", url, headers=bot_headers)


async def create_thread(
    client: httpx.AsyncClient, bot_headers: Dict[str, str], channel_id: str, message_id: str, name: str
) -> Optional[str]:
    url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}/threads"
    payload = {"name": name, "auto_archive_duration": 60}
    resp = await discord_request(client, "POST", url, headers=bot_headers, json_body=payload)
    if resp is not None and resp.status_code in (200, 201):
        return resp.json().get("id")
    return None


# ---------------------------------------------------------------------------
# Session + streaming
# ---------------------------------------------------------------------------


async def resolve_session_id(
    session_cfg: SessionStoreConfig, entity_id: Optional[str], user_id: str, scope_id: str
) -> str:
    prefix = f"discord-{user_id}-{scope_id}-"
    if session_cfg.has_db:
        try:
            found = await find_latest_session_id(session_cfg, user_id, entity_id, session_scope=prefix)
            if found:
                return found
        except Exception as e:
            log_warning(f"Discord session lookup failed, minting fresh: {e}")
    return f"{prefix}{int(time.time())}"


async def stream_agent_run(
    entity: Any,
    message: str,
    user_id: str,
    session_id: str,
    media: Dict[str, Any],
    dependencies: Dict[str, Any],
    status_edit: StatusEdit,
) -> str:
    """Run the entity with streaming, editing the status surface as tools start/finish.

    `status_edit` is an async callable taking a single `content: str` arg that
    writes to whichever message is acting as the status surface (deferred response,
    thread status message, or channel status message). Tool-status edits are
    debounced to STATUS_EDIT_MIN_INTERVAL; the returned final answer is not.
    """
    from agno.agent import RemoteAgent
    from agno.team import RemoteTeam
    from agno.workflow import RemoteWorkflow

    active: "OrderedDict[str, str]" = OrderedDict()
    last_status = STATUS_THINKING
    last_edit_at = 0.0
    final_content = ""

    # Prime the status surface. Deliberately does not start the debounce clock,
    # so the first real tool status is never skipped.
    await status_edit(STATUS_THINKING)

    # Remote entities proxy to a server and don't accept dependency kwargs;
    # only pass them to local agents/teams/workflows
    is_remote = isinstance(entity, (RemoteAgent, RemoteTeam, RemoteWorkflow))
    run_kwargs: Dict[str, Any] = {
        "user_id": user_id,
        "session_id": session_id,
        "stream": True,
        "stream_events": True,
        "yield_run_output": True,
        **media,
    }
    if not is_remote:
        run_kwargs["dependencies"] = dependencies
        run_kwargs["add_dependencies_to_context"] = True

    async for event in entity.arun(message, **run_kwargs):
        if isinstance(event, (RunOutput, TeamRunOutput)):
            if event.content:
                final_content = event.content if isinstance(event.content, str) else str(event.content)
            continue

        event_name = getattr(event, "event", "")
        tool = getattr(event, "tool", None)
        tool_name = getattr(tool, "tool_name", None) if tool else None
        call_id = getattr(tool, "tool_call_id", None) if tool else None

        if event_name in TOOL_STARTED_EVENTS and tool_name:
            key = call_id or f"{tool_name}-{len(active)}"
            active[key] = tool_name
        elif event_name in TOOL_ENDED_EVENTS:
            if call_id and call_id in active:
                active.pop(call_id, None)
            elif tool_name:
                # Fallback: pop the first entry matching this name
                for k, v in list(active.items()):
                    if v == tool_name:
                        active.pop(k, None)
                        break
        else:
            continue

        status = format_tool_status(active)
        # Debounce: skip edits landing inside the interval (a skipped status is
        # retried on the next tool event; the final answer bypasses this entirely)
        if status != last_status and time.monotonic() - last_edit_at >= STATUS_EDIT_MIN_INTERVAL:
            try:
                await status_edit(status)
            except Exception as e:
                log_warning(f"Discord tool-status edit failed: {e}")
            last_status = status
            last_edit_at = time.monotonic()

    return final_content or "(empty response)"
