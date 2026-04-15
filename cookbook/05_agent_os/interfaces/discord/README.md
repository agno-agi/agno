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
   `applications.commands` scopes and invite the bot to a server.

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

The server starts on `http://localhost:7777` and auto-registers the
`/ask` slash command on startup.

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
```

## Examples

- `basic.py` -- Single agent responding to `/ask`, with optional file attachment.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DISCORD_PUBLIC_KEY` | Yes | Public Key from the Developer Portal. Used to verify signed interaction requests. |
| `DISCORD_APP_ID` | Yes | Application ID. Used for followup webhook URLs. |
| `DISCORD_BOT_TOKEN` | Yes (default) | Bot token. Used to register slash commands at startup. Only optional if you pass `auto_register_command=False` to the `Discord(...)` constructor. |
| `OPENAI_API_KEY` | Depends | Required for OpenAI-based examples. |

## Features

- `/ask` slash command with a required `question` string and optional file attachment
- Inbound media: image, audio, video, or document attachments routed to the
  agent as `Image`, `Audio`, `Video`, or `File` based on MIME type
- Per-channel session in guilds, per-user session in DMs
- Ed25519 signature verification on every request
- Deferred response pattern (`type: 5`) so the agent has more than 3 seconds
  to run before Discord times out

## Limitations (prototype)

- Response text is truncated at Discord's 2000-character limit -- no chunking
- No streaming -- the agent runs to completion, then sends a single followup
- No outbound media (the agent can't send images/files back through Discord yet)
- No progress embeds or reasoning indicators

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Dev Portal refuses to save the URL | Public key mismatch, or server not reachable | Check `DISCORD_PUBLIC_KEY` matches the portal exactly, and that `curl https://YOUR-NGROK-URL/discord/interactions` returns 401 (not 404/500) |
| 401s in server logs after saving | Mostly normal - Discord sends bogus-signature probes | If *every* real interaction also 401s, the public key is wrong |
| "DISCORD_BOT_TOKEN is required" on startup | Missing env var | Export `DISCORD_BOT_TOKEN` or pass `auto_register_command=False` |
| Slash command doesn't appear | Registration failed | Check server logs for "Discord command registration returned ..." |
| Bot says "Error: ..." | Agent run raised | Check server logs for the full stack trace |
