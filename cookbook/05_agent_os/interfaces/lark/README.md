# Lark (Feishu) Cookbook

Examples for connecting Agno agents, teams, and workflows to Lark (飞书) using
the `Lark` interface in AgentOS. Supports text, media, streaming, and
multi-agent teams via the Lark Open Platform IM API with webhook-based message
delivery.

## Lark App Setup

Follow these steps to create and configure a Lark custom app bot for use with
Agno.

### 1. Create the App

1. Go to the [Feishu Developer Console](https://open.feishu.cn/app) (or
   [Lark Developer Console](https://open.larksuite.com/app) for the
   international version).
2. Click **Create Custom App** and fill in the name and description.
3. Under **Features**, enable the **Bot** ability.

### 2. Configure Credentials

On the app's **Credentials & Basic Info** page, copy:

| Credential | Where | Env Var |
|------------|-------|---------|
| App ID | Credentials page (prefix `cli_`) | `LARK_APP_ID` |
| App Secret | Credentials page | `LARK_APP_SECRET` |

Under **Events & Callbacks → Encryption Strategy**, optionally configure:

| Credential | Where | Env Var | Purpose |
|------------|-------|---------|---------|
| Verification Token | Encryption Strategy page | `LARK_VERIFICATION_TOKEN` | Origin check (`header.token`) |
| Encrypt Key | Encryption Strategy page | `LARK_ENCRYPT_KEY` | AES event encryption + `X-Lark-Signature` verification |

### 3. Grant Permissions

Under **Permissions & Scopes**, add:

- `im:message` — read and send messages
- `im:message:send_as_bot` — send messages as the bot
- `im:message:receive_as_bot` — receive messages (event subscription)
- `im:message:update` — edit messages (required for streaming card updates)

### 4. Subscribe to Events

Under **Events & Callbacks → Event Subscriptions**:

1. Add the event `im.message.receive_v1` (Receive message).
2. Set the **Request URL** to your public webhook URL:
   `https://<your-host>/lark/webhook`
3. Lark sends a `url_verification` challenge; the interface responds
   automatically. You should see "verified" in the console.

### 5. Publish the App

Under **Version Management & Release**, create a version and submit for
review. For development, you can use the app within your own tenant
immediately. For production, the app must be approved and published.

### 6. Set Environment Variables

```bash
export LARK_APP_ID="cli_xxxxxxxxxxxxxxxx"
export LARK_APP_SECRET="xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export LARK_VERIFICATION_TOKEN="xxxxxxxxxxxxxxxx"    # optional but recommended
export LARK_ENCRYPT_KEY="xxxxxxxxxxxxxxxx"           # optional, enables encryption + signature
export OPENAI_API_KEY="your-openai-api-key"          # For OpenAI-based examples
```

### 7. Start a Tunnel

Lark needs a public HTTPS URL to deliver webhook events. Use
[ngrok](https://ngrok.com/) or
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/):

```bash
ngrok http 7777
# or: cloudflared tunnel --url http://localhost:7777
```

Copy the public HTTPS URL (e.g. `https://abc123.ngrok-free.app`). Set this as
the event Request URL in step 4.

### 8. Run an Example

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/lark/basic.py
```

The server starts on `http://localhost:7777`.

### 9. Verify It Works

Open your bot in Lark (search for the app name in the search bar, or open the
app page and click "Add to chat"). Send a message. You should see:

- An interactive card appear as a reply, updating in real-time as the agent
  streams its response (when `streaming=True`).
- Server logs showing `Processing Lark message from user <open_id> in chat <chat_id>`.

## Examples

### Getting Started

- `basic.py` — Minimal agent with conversation history, streaming, and group
  chat mention filtering (OpenAI).

Run any example:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/lark/<filename>.py
```

## Group Chat Support

By default, the bot only responds when @mentioned in group chats. This is
controlled by the `reply_to_mentions_only` flag:

```python
Lark(
    agent=my_agent,
    reply_to_mentions_only=True,   # Default: only respond to @mentions
)
```

To have the bot respond to all messages in a group, set
`reply_to_mentions_only=False`. Note that Lark only delivers group messages to
the bot when @mentioned by default — this is a platform-level setting
configured in the Feishu console.

## Features

- Text messages with conversation history
- Inbound media: images, files, audio, video
- Outbound media: images and files from agent responses
- Streaming responses with progressive interactive card updates (PATCH)
- Per-chat session tracking (`lark:{entity_id}:{chat_id}`)
- Group chat @mention detection and filtering
- Built-in `/new` (reset session) and `/help` command handlers
- Event signature verification (SHA-256) and AES decryption (when encrypt_key set)
- Event deduplication (Lark retries if not ACKed within 3s)
- Works with Agent, Team, and Workflow
- Supports both Feishu (`open.feishu.cn`) and Lark (`open.larksuite.com`) domains

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LARK_APP_ID` | Yes | - | App ID from the Feishu console |
| `LARK_APP_SECRET` | Yes | - | App secret from the Feishu console |
| `LARK_VERIFICATION_TOKEN` | No | - | Origin verification token |
| `LARK_ENCRYPT_KEY` | No | - | AES encryption key (enables signature verification + event encryption) |
| `OPENAI_API_KEY` | Depends | - | Required for OpenAI-based examples |

## Production Notes

- Lark requires HTTPS for webhook URLs. Use a reverse proxy (nginx, Caddy) with
  TLS in production.
- The server runs on port 7777 by default via AgentOS.
- The webhook must respond within 3 seconds — the interface ACKs immediately and
  processes the agent run in a background task.
- Rate limits: 5 QPS per user (P2P), 5 QPS per group, 1000/min and 50/sec overall.
- Message edit (PATCH) limits: 5 QPS per message, 14-day window.
- Interactive card content limit: 30 KB (longer responses are truncated in-place
  during streaming).

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| 403 "Invalid signature" | `LARK_ENCRYPT_KEY` set but webhook signature mismatch | Ensure the encrypt_key in the console matches `LARK_ENCRYPT_KEY` |
| 403 "Invalid verification token" | `LARK_VERIFICATION_TOKEN` mismatch | Ensure the token in the console matches the env var |
| URL verification fails | Server not running or not publicly reachable | Start the server and tunnel, then retry in the console |
| No response from the bot | Event subscription not configured or app not published | Verify `im.message.receive_v1` is subscribed and the app is released |
| Bot ignores group messages | Not @mentioned (default behavior) | @mention the bot, or set `reply_to_mentions_only=False` |
| `LARK_APP_ID is not set` | Missing env var | Export `LARK_APP_ID` and `LARK_APP_SECRET` before running |
| Streaming card not updating | `streaming=True` not set, or `im:message:update` permission missing | Pass `streaming=True` and grant the update permission |
