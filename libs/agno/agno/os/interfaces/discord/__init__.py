"""Discord interfaces for AgentOS — two transports, one shared pipeline.

Architecture map::

    DiscordInteractions (slash commands, stateless webhooks)
      Discord --signed POST--> /discord/interactions
        interactions.py         the interface: config, slash-command registration
        interactions_router.py  the endpoint: verify signature, ack, run, reply

    DiscordGateway (fluid chat via @mention/DM, WebSocket relay)
      Discord --WebSocket--> listener (bg thread) --POST + secret--> /discord/gateway/events
        gateway.py               the interface: config, listener thread lifecycle
        listener.py              discord.py client: filter, serialize, relay (only
                                 module that imports discord; loaded lazily)
        gateway_router.py        the endpoint: check secret, gate, run, reply

    Shared by both:
        constants.py  Discord wire-protocol enums and limits
        pipeline.py   Discord REST (discord_request: 429 retry), chunking,
                      debounced tool status, streaming runs (stream_agent_run)
        state.py      session lookup/rotation (discord-{user}-{scope}-{epoch})

Replies always go over Discord REST with the bot token (or the interaction
webhook), so the endpoints are self-sufficient — the gateway listener is only
an event source and can run in a separate process (run_listener=False).
"""

from agno.os.interfaces.discord.gateway import DiscordGateway
from agno.os.interfaces.discord.interactions import DiscordInteractions

__all__ = ["DiscordGateway", "DiscordInteractions"]
