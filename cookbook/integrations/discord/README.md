# Discord Integration

Three ways to connect Agno agents, teams, and workflows to Discord:

- **`basic.py`** — `DiscordClient`. A standalone Discord bot (no AgentOS):
  the client owns the process, keeps each Discord thread as an agent session,
  and posts replies back to the originating thread.
- **[`interactions/`](interactions/)** — `DiscordInteractions` (AgentOS
  interface). Slash commands (`/ask`) over Discord's HTTP Interactions API.
  Discord POSTs signed webhooks to your app. Stateless and horizontally
  scalable; commands can be installed to a **user account** and triggered
  anywhere; supports **ephemeral** (only-you-can-see) replies. Best for
  one-shot interactions.
- **[`gateway_adapter/`](gateway_adapter/)** — `DiscordGateway` (AgentOS
  interface). Fluid chat (@mention the bot or DM it, no commands) via a
  Gateway WebSocket listener that runs inside the AgentOS process and relays
  events to the app's own HTTP endpoint. Needs no public URL or tunnel. Best
  for conversational bots.

## Which AgentOS interface?

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
mention in the same channel continue the same conversation. Each folder has
its own README with full setup, examples, and troubleshooting.

## Standalone bot (`DiscordClient`)

`DiscordClient` connects one Agno agent to Discord and keeps each Discord
thread as an agent session. Incoming text and attachments are forwarded to the
agent, and the response is posted back to the originating thread.

### Files

| File | Description |
|---|---|
| `basic.py` | Run a history-aware Agno agent as a Discord bot. |

### Prerequisites

- `OPENAI_API_KEY`
- `discord.py` (`uv pip install --python .venvs/demo/bin/python discord.py`)
- A Discord application with a bot token and the privileged Message Content
  Intent enabled. The example supplies a minimally scoped Discord client, so
  Presence and Server Members intents are not required.

`DiscordClient.serve()` reads the bot token from `DISCORD_BOT_TOKEN`. Keep the
token out of source control:

```bash
export DISCORD_BOT_TOKEN=your_bot_token
```

Invite the bot through the Discord Developer Portal with View Channels, Send
Messages, Read Message History, Create Public Threads, and Send Messages in
Threads permissions in the server channels where it will run.

### Run

From the repository root:

```bash
.venvs/demo/bin/python cookbook/integrations/discord/basic.py
```

Send the bot a direct message or mention it in a server channel. The client
creates or reuses a Discord thread and uses that thread ID as the agent session
ID.
