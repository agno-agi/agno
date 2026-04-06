"""Socket Mode transport for the Slack interface.

Socket Mode lets the bot receive events without exposing a public HTTP endpoint.
The app connects outbound to Slack over a WebSocket using an App-Level Token
(``xapp-...``), so it works behind firewalls and in local development without a
tunnel.

Usage::

    slack = Slack(agent=my_agent, socket_mode=True, app_token="xapp-...")
    await slack.astart()          # async — blocks until stopped
    # or
    slack.start()                 # sync wrapper around asyncio.run

Required Slack app configuration:
- Enable Socket Mode in your app settings (Settings → Socket Mode)
- Generate an App-Level Token with the ``connections:write`` scope
- Keep the same bot token scopes as HTTP mode
"""
from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict

from agno.os.interfaces.slack._processing import (
    IGNORED_SUBTYPES,
    ProcessingConfig,
    handle_thread_started,
    process_slack_event,
    stream_slack_response,
)
from agno.utils.log import log_info

# Optional runtime imports — guarded so this module is importable even when
# slack-sdk[aiohttp] is not installed. start_socket_mode() raises ImportError
# with a helpful message when SocketModeClient is None.
try:
    from slack_sdk.socket_mode.aiohttp import SocketModeClient
    from slack_sdk.socket_mode.response import SocketModeResponse
    from slack_sdk.web.async_client import AsyncWebClient
except ImportError:
    SocketModeClient = None  # type: ignore[assignment,misc]
    SocketModeResponse = None  # type: ignore[assignment,misc]
    AsyncWebClient = None  # type: ignore[assignment,misc]


def _make_handler(config: ProcessingConfig) -> Callable:
    """Return the Socket Mode event handler closure for the given config.

    Extracted as a module-level factory so it can be tested independently of
    the WebSocket connection lifecycle.
    """

    async def _handler(client: Any, req: Any) -> None:
        # ACK immediately — Slack expects acknowledgment within 3 seconds.
        # Processing happens in the background so long-running agent calls
        # never block the acknowledgment.
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

        if req.type != "events_api":
            return

        data: Dict[str, Any] = req.payload
        event = data.get("event", {})
        event_type = event.get("type")

        # setSuggestedPrompts requires "Agents & AI Apps" mode (streaming UX only)
        if event_type == "assistant_thread_started" and config.streaming:
            asyncio.create_task(handle_thread_started(event, config))
        # Bot self-loop prevention: check bot_id at both the top-level event
        # and inside message_changed's nested "message" object.
        elif (
            event.get("bot_id")
            or (event.get("message") or {}).get("bot_id")
            or event.get("subtype") in IGNORED_SUBTYPES
        ):
            pass
        elif config.streaming:
            asyncio.create_task(stream_slack_response(data, config))
        else:
            asyncio.create_task(process_slack_event(data, config))

    return _handler


async def start_socket_mode(config: ProcessingConfig, app_token: str) -> None:
    """Connect to Slack via Socket Mode and process events until cancelled.

    This coroutine blocks indefinitely. Run it with ``asyncio.run()`` or
    schedule it as a task inside a running event loop.

    Args:
        config: Shared processing configuration (entity, tokens, options).
        app_token: Slack App-Level Token (``xapp-...``).  Required for Socket
            Mode; distinct from the bot token stored in ``config.slack_tools``.
    """
    if SocketModeClient is None:
        raise ImportError(
            "slack-sdk with aiohttp support is required for Socket Mode. "
            "Install it with: pip install 'slack-sdk[aiohttp]'"
        )

    web_client = AsyncWebClient(token=config.slack_tools.token, ssl=config.ssl)
    socket_client = SocketModeClient(app_token=app_token, web_client=web_client)
    socket_client.socket_mode_request_listeners.append(_make_handler(config))

    log_info("Connecting to Slack via Socket Mode...")
    await socket_client.connect()
    log_info("Slack Socket Mode connected.")

    try:
        # Block forever; cancelled when the caller shuts down (e.g. Ctrl-C).
        await asyncio.Future()
    finally:
        await socket_client.close()
        log_info("Slack Socket Mode disconnected.")
