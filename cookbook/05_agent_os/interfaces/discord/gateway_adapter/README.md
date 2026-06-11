# Discord Gateway Adapter Cookbook

Examples for the `DiscordGateway` interface: fluid chat with no slash
commands. Mention the bot in a server channel, or DM it, and just talk.

## How It Works

Discord only delivers plain chat messages over a persistent **Gateway
WebSocket** — never to an HTTP endpoint. But AgentOS is an HTTP app. The
gateway adapter bridges the two: a minimal discord.py listener runs in a
background thread inside the AgentOS process and **relays** each message as
an HTTP POST to the app's own events endpoint, where the real processing
happens.

```
                ONE AGENTOS PROCESS
  ┌────────────────────────────────────────────────────┐
  │                                                    │
  │   listener thread (discord.py, own event loop)     │
  │      ▲ WebSocket: Discord pushes every message     │
  │      │                                             │
  │      │ filter (mentions, DMs, threads, no bots)    │
  │      │ serialize to JSON                           │
  │      ▼                                             │
  │   POST http://localhost:7777/discord/gateway/events │
  │      + X-Discord-Gateway-Secret header             │
  │      │                                             │
  │      ▼                                             │
  │   FastAPI route (the processing brain)             │
  │      - re-checks gating (it is the authority)      │
  │      - resolves session, runs the agent (streamed) │
  │      - live tool status, chunking                  │
  │      ▼                                             │
  │   replies via Discord REST with the bot token      │
  │                                                    │
  └────────────────────────────────────────────────────┘
```

Key properties:

- **The bot dials out.** No public URL, tunnel, application id, or public key
  — only the bot token. Works behind NAT, on a laptop, anywhere with outbound
  internet.
- **The endpoint is the brain.** The listener only filters and forwards.
  Because the relay speaks plain HTTP, it can later run as a separate process
  feeding one or more stateless AgentOS replicas (see below).
- **Replies go over REST**, not the WebSocket — the endpoint is
  self-sufficient.
- **Shared secret auth.** Unlike Interactions webhooks, relayed gateway
  events carry no Discord signature, so the endpoint rejects any POST without
  the `X-Discord-Gateway-Secret` header (auto-generated per process,
  overridable via `DISCORD_GATEWAY_SECRET`).

## Mention-Gating

So the bot doesn't answer every message in a busy channel:

- **Server channel**: responds only when the bot is **@mentioned**. The reply
  opens a thread off your message (disable with `reply_in_thread=False`).
- **Thread the bot started or participates in**: responds to every message —
  keep chatting, no mention needed.
- **DM**: always responds (disable with `respond_to_dms=False`).
- **Bots** (including itself): always ignored.

## Setup

1. Create a Discord application at https://discord.com/developers/applications
   and copy the bot token (**Bot -> Reset Token**).
2. Under **Bot**, enable the **Message Content Intent** (privileged intents
   section). Bots in fewer than 100 servers can enable it freely; larger bots
   need Discord verification.
3. Install the gateway dependency:

```bash
pip install discord.py
# or: pip install 'agno[discord]'
```

4. Invite the bot to a server with **Send Messages**, **Create Public
   Threads**, and **Send Messages in Threads** permissions.
5. Set env vars:

```bash
export DISCORD_BOT_TOKEN="your-bot-token"
export OPENAI_API_KEY="your-openai-api-key"
```

6. Run an example — no tunnel, no endpoint URL to configure:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/discord/gateway_adapter/basic.py
```

7. In Discord: `@YourBot hello` in a channel, or DM the bot directly.

## Examples

- `basic.py` -- Single agent with fluid chat: @mention it or DM it.
- `team.py` -- Multi-agent Researcher + Writer team behind one chat bot.
- `workflow.py` -- Sequential two-step Draft + Edit workflow.
- `research_assistant.py` -- Agent that combines `DiscordTools` (channel introspection) with web search.
- `support_team.py` -- Team that routes questions between a Technical Support agent and a Documentation Specialist.
- `channel_summarizer.py` -- Agent that reads recent channel history via `DiscordTools` and produces a structured summary (`reply_in_thread=False`).

Run any example:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/discord/gateway_adapter/<filename>.py
```

## Running the Relay Externally

The listener speaks plain HTTP to the events endpoint, so it can run as a
separate process feeding one or more stateless AgentOS replicas:

- On the AgentOS side, pass `run_listener=False` to `DiscordGateway(...)` and
  set `DISCORD_GATEWAY_SECRET` to a fixed value.
- Run the listener elsewhere with the same `DISCORD_GATEWAY_SECRET` and point
  it at your app with `app_url="https://your-agentos.example.com"` (or the
  `DISCORD_GATEWAY_APP_URL` env var).

If AgentOS serves on a non-default port, set `app_url` (or
`DISCORD_GATEWAY_APP_URL`) accordingly — the relay defaults to
`http://localhost:7777`.

## Operational Notes

- Keep `reload=False` when serving — auto-reload reconnects the gateway
  socket on every file change.
- Run a **single** listener instance. Multiple listeners (e.g. `workers > 1`
  with `run_listener=True`) each open their own gateway connection and
  produce duplicate replies. For multi-replica deployments, use
  `run_listener=False` plus one external relay.
- Sessions use the same keying as the interactions interface
  (`discord-{user_id}-{scope_id}-{epoch}`), so both can be mounted in one app
  and share conversation history.
- Gateway replies are regular Discord messages — there is no ephemeral mode
  here; that's an Interactions-only feature.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_BOT_TOKEN` | Yes | Bot token. Connects the listener and sends replies. |
| `DISCORD_GATEWAY_SECRET` | No | Shared secret between listener and endpoint. Auto-generated per process if unset; set explicitly only for external relays. |
| `DISCORD_GATEWAY_APP_URL` | No | Base URL the listener POSTs events to. Defaults to `http://localhost:7777`. |
| `OPENAI_API_KEY` | Depends | Required for OpenAI-based examples. |

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Bot never replies to channel messages | Not mentioned, or Message Content Intent disabled | @mention the bot, and check the intent toggle in the Dev Portal (a disabled intent disconnects the client with a PrivilegedIntentsRequired error in logs) |
| Relay logs "failed after retries" | App serving on a different port than the relay targets | Set `app_url=` on `DiscordGateway(...)` or export `DISCORD_GATEWAY_APP_URL` |
| Relay logs 401 | Listener and endpoint disagree on the secret | Set the same `DISCORD_GATEWAY_SECRET` on both sides (only needed for external relays) |
| Duplicate replies | Multiple listener processes (e.g. `workers > 1`) | Run one listener; use `run_listener=False` + an external relay for multi-replica deployments |
| Bot replies to itself or other bots | Should never happen (gated twice) | File a bug with logs |
| `ImportError: discord.py is required` | Gateway dependency missing | `pip install discord.py` (or `pip install 'agno[discord]'`) |
| Bot says "Error: ..." | Agent run raised | Check server logs for the full stack trace |
