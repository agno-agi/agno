# Discord Cookbook

Two ways to connect Agno agents, teams, and workflows to Discord via AgentOS,
built on the two transports Discord offers:

- **[`interactions/`](interactions/)** — `DiscordInteractions`. Slash commands
  (`/ask`) over Discord's HTTP Interactions API. Discord POSTs signed webhooks
  to your app. Stateless and horizontally scalable; commands can be installed
  to a **user account** and triggered anywhere; supports **ephemeral**
  (only-you-can-see) replies. Best for one-shot interactions.
- **[`gateway_adapter/`](gateway_adapter/)** — `DiscordGateway`. Fluid chat
  (@mention the bot or DM it, no commands) via a Gateway WebSocket listener
  that runs inside the AgentOS process and relays events to the app's own
  HTTP endpoint. Needs no public URL or tunnel. Best for conversational bots.

## Why two interfaces?

Discord only delivers plain chat messages over a persistent Gateway WebSocket
(with the privileged Message Content Intent). An HTTP Interactions endpoint
only ever receives slash commands and component interactions — Discord never
POSTs normal messages to it. So "fluid chat" and "stateless webhook endpoint"
are different transports, and each gets its own interface.

| | `interactions/` | `gateway_adapter/` |
|---|---|---|
| Conversation style | Slash commands (`/ask`) | Fluid chat (@mention or DM) |
| Transport | Discord POSTs signed webhooks to you | Bot opens a WebSocket, relays events to your app |
| Public HTTPS URL / tunnel | **Required** | Not needed |
| Credentials | Public Key + App ID + Bot Token | Bot Token only |
| Privileged intent | No | **Message Content Intent** required |
| Extra dependency | None | `discord.py` |
| User-installable (use anywhere) | **Yes** | No (bot must be in the server) |
| Ephemeral (private) replies | **Yes** | No (regular messages) |
| Horizontal scaling | Stateless, any replica count | Single listener (or external relay) |

Both interfaces can be mounted in the same AgentOS app and share the same
session keying (`discord-{user_id}-{scope_id}-{epoch}`), so a `/ask` and a
mention in the same channel continue the same conversation.

Each folder has its own README with full setup, examples, and troubleshooting.
