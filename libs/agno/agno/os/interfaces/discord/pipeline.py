"""Shared Discord processing machinery used by both the Interactions router and the Gateway router.

Everything here speaks Discord REST with a bot token — no interaction tokens, no
gateway connection — so both transports (and a future external relay) can reuse it.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx

from agno.media import Audio, File, Image, Video
from agno.os.interfaces.discord.state import (
    _SessionStoreConfig,
    find_latest_session_id,
)
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.utils.log import log_warning

DISCORD_API = "https://discord.com/api/v10"
MAX_MESSAGE_LENGTH = 2000
MAX_THREAD_NAME_LENGTH = 100

# Discord channel types considered threads
THREAD_CHANNEL_TYPES = {10, 11, 12}  # ANNOUNCEMENT, PUBLIC, PRIVATE

# Event names emitted by agents (and their Team-prefixed siblings)
TOOL_STARTED_EVENTS = {"ToolCallStarted", "TeamToolCallStarted"}
TOOL_ENDED_EVENTS = {"ToolCallCompleted", "TeamToolCallCompleted", "ToolCallError", "TeamToolCallError"}

STATUS_THINKING = "Thinking..."

StatusEdit = Callable[[str], Coroutine[Any, Any, None]]


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


async def post_in_channel(
    client: httpx.AsyncClient, bot_headers: Dict[str, str], channel_id: str, content: str
) -> Optional[str]:
    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    body = content[:MAX_MESSAGE_LENGTH] or "(empty)"
    resp = await client.post(url, headers=bot_headers, json={"content": body})
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    log_warning(f"Posting message failed: {resp.status_code} {resp.text}")
    return None


async def edit_channel_message(
    client: httpx.AsyncClient, bot_headers: Dict[str, str], channel_id: str, message_id: str, content: str
) -> None:
    url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}"
    body = content[:MAX_MESSAGE_LENGTH] or "(empty)"
    await client.patch(url, headers=bot_headers, json={"content": body})


async def trigger_typing(client: httpx.AsyncClient, bot_headers: Dict[str, str], channel_id: str) -> None:
    """Show the native 'Bot is typing...' indicator (lasts up to 10 seconds).

    Failures are swallowed — typing is cosmetic and must never break a run.
    """
    url = f"{DISCORD_API}/channels/{channel_id}/typing"
    try:
        await client.post(url, headers=bot_headers)
    except Exception as e:
        log_warning(f"Typing indicator failed: {e}")


async def create_thread(
    client: httpx.AsyncClient, bot_headers: Dict[str, str], channel_id: str, message_id: str, name: str
) -> Optional[str]:
    url = f"{DISCORD_API}/channels/{channel_id}/messages/{message_id}/threads"
    payload = {"name": name, "auto_archive_duration": 60}
    resp = await client.post(url, headers=bot_headers, json=payload)
    if resp.status_code in (200, 201):
        return resp.json().get("id")
    log_warning(f"Thread creation failed: {resp.status_code} {resp.text}")
    return None


async def resolve_session_id(
    session_cfg: _SessionStoreConfig, entity_id: Optional[str], user_id: str, scope_id: str
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
    thread status message, or channel status message).
    """
    from agno.agent import RemoteAgent
    from agno.team import RemoteTeam
    from agno.workflow import RemoteWorkflow

    active: "OrderedDict[str, str]" = OrderedDict()
    last_status = STATUS_THINKING
    final_content = ""

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
        if status != last_status:
            try:
                await status_edit(status)
            except Exception as e:
                log_warning(f"Discord tool-status edit failed: {e}")
            last_status = status

    return final_content or "(empty response)"
