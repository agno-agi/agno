# Discord Cookbook

Examples for connecting Agno agents, teams, and workflows to Discord using
the `Discord` interface in AgentOS. Uses Discord's HTTP Interactions API
(webhook-based), not the Gateway/WebSocket.

## Discord App Setup

### 1. Create the App

1. Go to https://discord.com/developers/applications and click **New Application**.
2. Under **Bot**, click **Reset Token** and copy the token.
3. Under **General Information**, copy the **Application ID** and **Public Key**.
4. Under **Installation** (or **OAuth2 -> URL Generator**), add the `bot` and
   `applications.commands` scopes and invite the bot to a server. Grant at
   minimum **Send Messages**, **Create Public Threads**, and **Send Messages
   in Threads** (the bot replies in threads by default). If you disable
   threads via `reply_in_thread=False`, only **Send Messages** is needed.

### 2. Set Environment Variables

```bash
export DISCORD_PUBLIC_KEY="your-public-key"
export DISCORD_APP_ID="your-application-id"
export DISCORD_BOT_TOKEN="your-bot-token"
export OPENAI_API_KEY="your-openai-api-key"
```

### 3. Start a Tunnel

Discord needs a public HTTPS URL to deliver interaction events. Use
[ngrok](https://ngrok.com/) or
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):

```bash
ngrok http 7777
```

Copy the HTTPS URL (e.g. `https://abc123.ngrok-free.app`).

### 4. Run an Example

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/discord/basic.py
```

The server starts on `http://localhost:7777` and auto-registers both
the `/ask` and `/new` slash commands on startup.

### 5. Set the Interactions Endpoint URL

In the Discord Developer Portal, go to **General Information ->
Interactions Endpoint URL** and paste:

```
https://YOUR-NGROK-URL/discord/interactions
```

Click **Save Changes**. Discord validates the URL by sending a PING with
a valid signature and a second request with a deliberately invalid
signature. Both checks must pass (PING returns `{"type": 1}`, bad
signature returns 401) before the URL is saved.

### 6. Try It

In any server where the bot is installed:

```
/ask question: what's the weather on mars?
/ask question: describe this image file: <drop an image>
/new                                    # start a fresh conversation in the current channel
```

## Slash Commands

- `/ask question:<text> [file:<attachment>]` — ask the agent. If the bot is
  configured with `reply_in_thread=True` (the default), a new thread is opened
  for the answer. Inside an existing thread, the reply stays in that thread.
- `/new` — rotate the current user's session in the current channel so the
  next `/ask` starts fresh with no prior context. No effect inside a thread
  (threads already have their own session) and no effect on other users.
  Requires the agent to have a DB configured for session memory.

## Examples

- `basic.py` -- Single agent responding to `/ask`, with optional file attachment.
- `team.py` -- Multi-agent Researcher + Writer team coordinated behind one bot.
- `workflow.py` -- Sequential two-step Draft + Edit workflow exposed through Discord.
- `research_assistant.py` -- Agent that combines `DiscordTools` (channel introspection) with web search to answer research questions.
- `support_team.py` -- Team that routes questions between a Technical Support agent and a Documentation Specialist (the latter searches Discord history via `DiscordTools`).
- `channel_summarizer.py` -- Agent that reads recent channel history via `DiscordTools` and produces a structured summary.

Run any example:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/discord/<filename>.py
```

### Notes on DiscordTools

The examples that use `agno.tools.discord.DiscordTools` need the bot to have
**Read Message History** and **View Channels** permissions in each channel
you want it to introspect. The Discord interface automatically passes
`discord_channel_id`, `discord_thread_id`, and `discord_guild_id` as agent
dependencies so tool-using agents can act on "this channel" without the user
pasting IDs.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_PUBLIC_KEY` | Yes | Public Key from the Developer Portal. Used to verify signed interaction requests. |
| `DISCORD_APP_ID` | Yes | Application ID. Used for followup webhook URLs. |
| `DISCORD_BOT_TOKEN` | Yes (default) | Bot token. Used to register slash commands at startup. Only optional if you pass `auto_register_command=False` to the `Discord(...)` constructor. |
| `OPENAI_API_KEY` | Depends | Required for OpenAI-based examples. |

## Features

- `/ask` with a required `question` and optional `file` attachment
- `/new` to rotate the current user's session in the current channel
- Inbound media: image/audio/video/document attachments routed to the agent
  as `Image` / `Audio` / `Video` / `File` based on MIME type
- Thread replies by default: a new thread opens on the bot's response message
  using the question as the thread title. Disable with `reply_in_thread=False`.
- Live tool-call status: while the agent is running, the reply message shows
  `Running tool: <tool_name>...`, swapping for the final answer when done.
- Per-user session scope: `discord-{user_id}-{scope_id}-{epoch}`, where
  `scope_id` is the thread id if inside a thread, else the channel id. Two
  users in the same channel keep separate conversations. `/new` bumps the
  epoch for the invoking user only.
- Long responses are chunked at paragraph/line/word boundaries into
  Discord's 2000-character messages.
- Ed25519 signature verification on every request; signature-invalid probes
  from the Dev Portal get `401` as expected.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Dev Portal refuses to save the URL | Public key mismatch, or server not reachable | Check `DISCORD_PUBLIC_KEY` matches the portal exactly, and that `curl https://YOUR-NGROK-URL/discord/interactions` returns 401 (not 404/500) |
| 401s in server logs after saving | Mostly normal - Discord sends bogus-signature probes | If *every* real interaction also 401s, the public key is wrong |
| "DISCORD_BOT_TOKEN is required" on startup | Missing env var | Export `DISCORD_BOT_TOKEN` or pass `auto_register_command=False` |
| Slash command doesn't appear | Registration failed | Check server logs for "Discord command registration returned ..." |
| Bot says "Error: ..." | Agent run raised | Check server logs for the full stack trace |
| `/new` says "Session memory isn't configured" | Agent has no `db=` wired up | Pass `db=SqliteDb(...)` (or another Agno DB) to the agent so sessions persist |
| Tool-call status doesn't update | Agent isn't using tools, or status edits were rate-limited | Expected for plain chat. Tool names only show when the agent actually invokes a tool. |
