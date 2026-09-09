# Discord Integration

`DiscordClient` connects one Agno agent to Discord and keeps each Discord
thread as an agent session. Incoming text and attachments are forwarded to the
agent, and the response is posted back to the originating thread.

## Files

| File | Description |
|---|---|
| `basic.py` | Run a history-aware Agno agent as a Discord bot. |

## Prerequisites

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

## Run

From the repository root:

```bash
.venvs/demo/bin/python cookbook/integrations/discord/basic.py
```

Send the bot a direct message or mention it in a server channel. The client
creates or reuses a Discord thread and uses that thread ID as the agent session
ID.
