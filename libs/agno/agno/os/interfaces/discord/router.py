"""
Discord Interactions Router

Streaming architecture:
  Discord uses HTTP Interactions (webhook-based, not Gateway WebSocket).
  1. Discord POSTs to /interactions with Ed25519-signed body
  2. We verify signature and return a deferred ACK (type 5) within 3 seconds
  3. A background task runs entity.arun() with streaming enabled
  4. Every ~1.5s, PATCH the original response with an updated embed:
     - Embed description: accumulated response text (up to 4,096 chars)
     - Embed fields: task cards (tool calls, reasoning) with status icons
  5. On completion: final embed + overflow follow-up messages for long content
  6. Media uploaded as separate follow-up attachments

Key difference from Slack: no first-class streaming API. Updates are
rate-limited periodic snapshots via webhook PATCH, not character-by-character.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from agno.agent import Agent, RemoteAgent
from agno.os.interfaces.discord.events import process_event
from agno.os.interfaces.discord.formatting import normalize_discord_markdown
from agno.os.interfaces.discord.helpers import (
    _FOLLOWUP_CHUNK_SIZE,
    _MAX_EMBED_DESCRIPTION,
    FALLBACK_ERROR_MESSAGE,
    DiscordBotClient,
    DiscordWebhook,
    build_status_embed,
    download_resolved_attachments,
    extract_interaction_options,
    extract_user,
    format_attribution,
    format_thread_name,
)
from agno.os.interfaces.discord.security import verify_discord_signature
from agno.os.interfaces.discord.state import (
    _PUBLIC_THREAD_TYPE,
    _THREAD_CHANNEL_TYPES,
    InstanceState,
    StreamState,
    _build_session_scope,
    insert_sentinel_session,
)
from agno.os.interfaces.sessions import build_session_store_config, find_latest_session_id
from agno.os.interfaces.streaming import chunk_text
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.team import RemoteTeam, Team
from agno.utils.log import log_error, log_warning
from agno.utils.message import get_text_from_message
from agno.workflow import RemoteWorkflow, Workflow

try:
    import aiohttp
except ImportError as e:
    raise ImportError("The `aiohttp` package is not installed. Please install it via `pip install aiohttp`.") from e

# Discord Interaction Types
INTERACTION_PING = 1
INTERACTION_APPLICATION_COMMAND = 2
INTERACTION_MESSAGE_COMPONENT = 3

# Discord Interaction Response Types
RESPONSE_PONG = 1
RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE = 4
RESPONSE_DEFERRED_CHANNEL_MESSAGE = 5
RESPONSE_DEFERRED_UPDATE_MESSAGE = 6

EPHEMERAL_FLAG = 64


class DiscordStatusResponse(BaseModel):
    status: str = Field(default="available")


def attach_routes(
    router: APIRouter,
    agent: Optional[Union[Agent, RemoteAgent]] = None,
    team: Optional[Union[Team, RemoteTeam]] = None,
    workflow: Optional[Union[Workflow, RemoteWorkflow]] = None,
    public_key: Optional[str] = None,
    application_id: Optional[str] = None,
    bot_token: Optional[str] = None,
    reply_in_thread: bool = True,
    streaming: bool = True,
    # Sync path only — streaming always shows reasoning via task card events
    show_reasoning: bool = False,
    error_message: str = FALLBACK_ERROR_MESSAGE,
) -> APIRouter:
    # Inner functions capture config via closure to keep each instance isolated
    entity = agent or team or workflow
    entity_type: Literal["agent", "team", "workflow"] = "agent" if agent else "team" if team else "workflow"
    _name = getattr(entity, "name", None)
    entity_name = _name if isinstance(_name, str) else entity_type
    # Multiple Discord instances on one FastAPI app need unique operation_ids
    operation_id_suffix = entity_name.lower().replace(" ", "_")
    entity_id = getattr(entity, "id", None) or entity_name

    session_config = build_session_store_config(entity, entity_type)
    instance_state = InstanceState(session_config=session_config, entity_id=entity_id)

    # Defensive fallback — Discord payloads always include application_id,
    # but the configured value covers edge cases (e.g. malformed webhooks)
    configured_app_id = application_id or ""

    # Lazy aiohttp session — attach_routes() runs at import time (sync),
    # before any event loop exists
    _http_session: Optional[aiohttp.ClientSession] = None

    async def _get_session() -> aiohttp.ClientSession:
        nonlocal _http_session
        if _http_session is None or _http_session.closed:
            _http_session = aiohttp.ClientSession()
        return _http_session

    async def _stream_response(
        webhook: DiscordWebhook,
        message_text: str,
        run_kwargs: Dict[str, Any],
    ) -> None:
        is_workflow = entity_type == "workflow"
        stream_kwargs: Dict[str, Any] = {"stream": True, "stream_events": True, **run_kwargs}
        # Workflows surface media through streaming events, not RunOutput;
        # agent/team must yield RunOutput so we can send media after the stream closes
        if not is_workflow:
            stream_kwargs["yield_run_output"] = True

        state = StreamState(
            webhook=webhook,
            entity_type=entity_type,
            entity_name=entity_name,
            error_message=error_message,
        )

        try:
            async for event in entity.arun(message_text, **stream_kwargs):  # type: ignore[union-attr]
                if isinstance(event, (RunOutput, TeamRunOutput)):
                    state.final_run_output = event
                    continue

                state.collect_media(event)

                ev = getattr(event, "event", "")
                if ev and await process_event(ev, event, state):
                    break
        except Exception:
            state.error_status = "error"
            state.accumulated_content = state.error_message
        finally:
            await state.finalize()

        # Post-stream media delivery
        # Agent/team: media is on RunOutput. Workflow: media was collected from streaming events.
        if not is_workflow and state.final_run_output:
            if state.final_run_output.status == "ERROR":
                return
            await webhook.send_response_media(state.final_run_output)

        if is_workflow and (state.images or state.videos or state.audio or state.files):
            await webhook.send_response_media(state)

    async def _sync_response(
        webhook: DiscordWebhook,
        message_text: str,
        run_kwargs: Dict[str, Any],
    ) -> None:
        response = await entity.arun(message_text, **run_kwargs)  # type: ignore[union-attr]

        if not response:
            await webhook.edit_original(content="No response generated.")
            return

        if response.status == "ERROR":
            log_error(f"Agent returned error status for interaction {webhook.interaction_token[:8]}")
            await webhook.edit_original(content=error_message)
            return

        # Happy path: format and send content as embed
        content = get_text_from_message(response.content) if response.content is not None else ""
        if not content:
            content = "(empty response)"
        content = normalize_discord_markdown(content)

        description_parts: List[str] = []
        if show_reasoning and hasattr(response, "reasoning_content") and response.reasoning_content:
            description_parts.append(f"*{response.reasoning_content}*\n")
        description_parts.append(content)
        full_description = "\n".join(description_parts)

        embed = build_status_embed(
            title="Complete",
            description=full_description[:_MAX_EMBED_DESCRIPTION],
            fields=[],
        )
        await webhook.edit_original(embeds=[embed])

        if len(full_description) > _MAX_EMBED_DESCRIPTION:
            overflow = full_description[_MAX_EMBED_DESCRIPTION:]
            for part in chunk_text(overflow, _FOLLOWUP_CHUNK_SIZE):
                await webhook.send_followup(content=part)

        await webhook.send_response_media(response)

    async def _process_interaction(data: dict) -> None:
        session = await _get_session()
        webhook = DiscordWebhook(
            session=session,
            application_id=data.get("application_id") or configured_app_id,
            interaction_token=data.get("token", ""),
        )

        try:
            message_text = extract_interaction_options(data)
            if not message_text:
                await webhook.edit_original(content="Please provide a message.")
                return

            user_id, user_name = extract_user(data)
            channel_id = data.get("channel_id", "")
            guild_id = data.get("guild_id")
            channel_obj = data.get("channel", {})
            channel_type = channel_obj.get("type") if channel_obj else None
            in_thread = channel_type in _THREAD_CHANNEL_TYPES

            # Thread creation: when reply_in_thread is enabled and not already in a thread,
            # create a thread from the deferred response message
            thread_id: Optional[str] = None
            if reply_in_thread and bot_token and not in_thread:
                # Show user attribution on the original message
                attribution = format_attribution(user_name, message_text)
                await webhook.edit_original(content=attribution)
                original_msg_id = await webhook.get_original_message_id()
                if original_msg_id:
                    bot_client = DiscordBotClient(session=session, bot_token=bot_token)
                    thread_id = await bot_client.create_message_thread(
                        channel_id, original_msg_id, format_thread_name(message_text)
                    )

            # Resolve session — use thread channel for scoping when we created one
            scope_channel = thread_id or channel_id
            scope_channel_type = _PUBLIC_THREAD_TYPE if thread_id else channel_type
            session_scope = _build_session_scope(
                entity_id, scope_channel, user_id, guild_id=guild_id, channel_type=scope_channel_type
            )
            # Default to scope key; DB lookup may override with a persisted session
            session_id = session_scope
            cfg = instance_state.session_config
            if cfg.has_db:
                try:
                    found = await find_latest_session_id(cfg, user_id, entity_id, session_scope)
                    if found:
                        session_id = found
                except Exception as e:
                    log_warning(f"Session lookup failed, using default: {str(e)}")

            media_kwargs = await download_resolved_attachments(session, data)

            # Build run config
            # Remote entities proxy to a server and don't accept dependency kwargs;
            # only pass them to local agents/teams/workflows
            is_remote = isinstance(entity, (RemoteAgent, RemoteTeam, RemoteWorkflow))
            run_kwargs: Dict[str, Any] = {
                "user_id": user_id,
                "session_id": session_id,
                "metadata": {"user_id": user_id},
                **media_kwargs,
            }
            if not is_remote:
                run_kwargs["dependencies"] = {
                    "discord_channel_id": channel_id,
                    "discord_guild_id": guild_id,
                    "discord_thread_id": thread_id,
                }
                run_kwargs["add_dependencies_to_context"] = True

            if streaming:
                await _stream_response(webhook, message_text, run_kwargs)
            else:
                await _sync_response(webhook, message_text, run_kwargs)

        except Exception as e:
            log_error(f"Error processing Discord interaction: {e}")
            try:
                await webhook.edit_original(content=error_message)
            except Exception:
                pass  # Last resort — original error already logged; avoid masking it

    async def _handle_new_command(data: dict) -> Dict[str, Any]:
        user_id, _ = extract_user(data)
        channel_id = data.get("channel_id", "")
        channel_obj = data.get("channel", {})
        channel_type = channel_obj.get("type") if channel_obj else None
        guild_id = data.get("guild_id")

        if channel_type in _THREAD_CHANNEL_TYPES:
            return {
                "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
                "data": {"content": "Use /new in a main channel, not inside a thread.", "flags": EPHEMERAL_FLAG},
            }

        cfg = instance_state.session_config
        if not cfg.has_db:
            return {
                "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
                "data": {"content": "Session memory is not configured for this bot.", "flags": EPHEMERAL_FLAG},
            }

        session_scope = _build_session_scope(
            entity_id, channel_id, user_id, guild_id=guild_id, channel_type=channel_type
        )
        new_session_id = f"{session_scope}:{uuid.uuid4().hex[:8]}"
        try:
            await insert_sentinel_session(cfg, new_session_id, user_id, entity_id)
        except Exception as e:
            log_error(f"Failed to insert sentinel session: {e}")
            return {
                "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
                "data": {"content": "Failed to reset conversation.", "flags": EPHEMERAL_FLAG},
            }

        return {
            "type": RESPONSE_CHANNEL_MESSAGE_WITH_SOURCE,
            "data": {
                "content": "Fresh conversation started. Your next message begins a new session.",
                "flags": EPHEMERAL_FLAG,
            },
        }

    @router.get(
        "/status",
        operation_id=f"discord_status_{operation_id_suffix}",
        name="discord_status",
        response_model=DiscordStatusResponse,
    )
    async def status():
        return DiscordStatusResponse()

    @router.post(
        "/interactions",
        operation_id=f"discord_interactions_{operation_id_suffix}",
        name="discord_interactions",
        description="Process incoming Discord interactions",
        responses={
            200: {"description": "Interaction processed"},
            400: {"description": "Missing signature headers"},
            403: {"description": "Invalid signature"},
        },
    )
    async def discord_interactions(request: Request, background_tasks: BackgroundTasks):
        body = await request.body()
        signature = request.headers.get("X-Signature-Ed25519", "")
        timestamp = request.headers.get("X-Signature-Timestamp", "")

        if not signature or not timestamp:
            raise HTTPException(status_code=400, detail="Missing signature headers")

        if not verify_discord_signature(body, signature, timestamp, public_key=public_key):
            raise HTTPException(status_code=403, detail="Invalid signature")

        data = await request.json()
        interaction_type = data.get("type")

        if interaction_type == INTERACTION_PING:
            return JSONResponse(content={"type": RESPONSE_PONG})

        if interaction_type == INTERACTION_APPLICATION_COMMAND:
            command_name_val = (data.get("data") or {}).get("name", "")
            # /new resets conversation — handled synchronously with ephemeral reply
            if command_name_val == "new":
                return JSONResponse(content=await _handle_new_command(data))

            interaction_id = data.get("id", "")
            # Discord retries if our ACK doesn't arrive in ~3s; returning a valid
            # deferred ACK for duplicates stops the retry cycle without reprocessing
            if interaction_id and instance_state.is_duplicate_interaction(interaction_id):
                return JSONResponse(content={"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE})
            background_tasks.add_task(_process_interaction, data)
            return JSONResponse(content={"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE})

        if interaction_type == INTERACTION_MESSAGE_COMPONENT:
            return JSONResponse(content={"type": RESPONSE_DEFERRED_UPDATE_MESSAGE})

        log_warning(f"Unhandled Discord interaction type: {interaction_type}")
        return JSONResponse(content={"type": RESPONSE_DEFERRED_CHANNEL_MESSAGE})

    async def _close_http_session() -> None:
        nonlocal _http_session
        if _http_session is not None and not _http_session.closed:
            await _http_session.close()
            _http_session = None

    router._close_http_session = _close_http_session  # type: ignore[attr-defined]

    return router
