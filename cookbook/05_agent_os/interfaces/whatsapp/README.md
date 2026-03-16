# WhatsApp Cookbook

Examples for connecting Agno agents, teams, and workflows to WhatsApp using the
`Whatsapp` interface in AgentOS. Supports text, images, video, audio, documents,
and interactive messages (buttons, lists, location pins).

**Requirements:** `httpx` (included with agno).

## WhatsApp Business Setup

### 1. Create a Meta Business Account

1. Go to [Meta Business Manager](https://business.facebook.com/) and create a Business Portfolio.
2. Complete [business verification](https://www.facebook.com/business/help/2058515294227817) to unlock production messaging limits and API access.

> Unverified accounts can still send messages to test numbers but are limited
> to 250 business-initiated conversations per 24 hours.

### 2. Create a Meta App

1. Go to the [Meta Developer Portal](https://developers.facebook.com/apps) and click **Create App**.
2. Select **Other** as the use case, then **Business** as the app type.
3. Give it a name and link it to your Business Portfolio from step 1.
4. On the app dashboard, find **WhatsApp** and click **Set Up**.

This creates your WhatsApp Business Account (WABA) and connects it to your app.

> For detailed steps, see Meta's [Get Started with the WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started).

### 3. Register a Phone Number

1. In the Meta portal sidebar, go to **WhatsApp > API Setup**.
2. Under **From**, click **Add phone number** to register your business number.
3. Complete verification via SMS or voice call.
4. Note the **Phone Number ID** displayed below the number — you'll need it for configuration.

> You can also use the test phone number Meta provides for development.
> See [Add a Phone Number](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/add-a-phone-number).

### 4. Generate an Access Token

#### Option A: Permanent Token (Recommended for Production)

System User tokens never expire and are the recommended approach for production.

1. Go to [Business Settings > System Users](https://business.facebook.com/settings/system-users).
2. Click **Add** and create a System User with **Admin** role.
3. Click **Assign Assets**, select your Meta App under the **Apps** tab, and grant **Full Control**.
4. Click **Generate New Token**, select your app, and check these permissions:
   - `whatsapp_business_messaging`
   - `whatsapp_business_management`
5. Click **Generate Token** and copy it immediately — it won't be shown again.

> This is the most commonly missed step: you must assign both the App and the
> WABA as assets to the System User before generating the token.
> See [System User Access Tokens](https://developers.facebook.com/docs/whatsapp/business-management-api/get-started#system-user-access-tokens).

#### Option B: Temporary Token (Quick Testing)

1. Go to **WhatsApp > API Setup** in the Meta developer portal.
2. Click **Generate access token**.
3. This token expires after ~24 hours and is only suitable for development.

### 5. Get Your App Secret

1. Go to **App Settings > Basic** in the Meta developer portal.
2. Copy the **App Secret** — this is used for webhook signature verification.

### 6. Set Environment Variables

```bash
export WHATSAPP_ACCESS_TOKEN="EAAW..."           # System User token (step 4A) or temporary token (step 4B)
export WHATSAPP_PHONE_NUMBER_ID="123456789"      # Phone Number ID from step 3
export WHATSAPP_APP_SECRET="..."                 # App Secret from step 5
export WHATSAPP_VERIFY_TOKEN="my-verify-token"   # Any string you choose (must match webhook config)
export OPENAI_API_KEY="sk-..."                   # Or whichever model provider you use
```

### 7. Configure the Webhook

1. In the Meta developer portal, go to **WhatsApp > Configuration**.
2. Under **Webhook**, click **Edit**.
3. Set **Callback URL** to your server's public URL + `/whatsapp/webhook`:
   ```
   https://your-domain.com/whatsapp/webhook
   ```
4. Set **Verify Token** to the same string as your `WHATSAPP_VERIFY_TOKEN` env var.
5. Click **Verify and Save** — your server must be running for verification to succeed.
   Meta sends a GET request with a challenge; the Agno server handles this automatically.
6. Under **Webhook fields**, subscribe to **messages**.

> See [Set Up Webhooks](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks)
> for details on the verification handshake and payload format.

### 8. Run an Example

```bash
.venvs/demo/bin/python cookbook/05_agent_os/interfaces/whatsapp/basic.py
```

Send a message to your business number from WhatsApp to test.

## Local Development

For quick local testing without a full production setup:

1. **Temporary token:** Use a temporary token from step 4B (~24 hour expiry).
2. **Test numbers:** Add your personal number as a test recipient on the **API Setup** page under "To".
   During development you can only message numbers registered here.
3. **Tunnel:** Use [ngrok](https://ngrok.com/) or [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
   to expose your local server:
   ```bash
   ngrok http 7777
   # or: cloudflared tunnel --url http://localhost:7777
   ```
   Use the tunnel URL as your webhook Callback URL (step 7.3). The free ngrok tier
   gives you a random subdomain that changes on restart — update the webhook URL each time.
4. **Skip signature validation:** Set `WHATSAPP_SKIP_SIGNATURE_VALIDATION=true` in your
   environment. Without this (or `WHATSAPP_APP_SECRET`), the server returns 500 on every
   webhook. Never set the skip flag in production.
5. **macOS SSL fix:** If you get certificate errors:
   ```bash
   export SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())")
   ```

## Examples

### Getting Started

- `basic.py` — Minimal agent that responds to messages with session history.
- `agent_with_user_memory.py` — Agent with MemoryManager that learns about users across conversations.

### Multimodal

- `agent_with_media.py` — Agent that receives and processes images, video, audio, and documents.
- `image_generation_model.py` — Image generation using a model with native image output.
- `image_generation_tools.py` — Image generation using DALL-E via tools.
- `video_generation.py` — Video generation agent.

### Interactive Messages

- `tourist_guide.py` — Tourist guide with reply buttons, location pins, and list messages.
- `interactive_concierge.py` — Full interactive features: buttons, lists, location, reactions.

### Reasoning

- `reasoning_agent.py` — Agent with step-by-step reasoning display.
- `deep_research.py` — Deep research agent with multiple toolkits.

### Teams and Workflows

- `support_team.py` — Support team routing between specialized agents.
- `multimodal_team.py` — Team combining vision input with image generation.
- `multimodal_workflow.py` — Multi-step workflow with parallel research and synthesis.

### Advanced

- `multiple_instances.py` — Multiple agents on one server with separate webhook prefixes.

## Webhook Security

The WhatsApp interface validates all incoming webhooks:

1. **Signature verification** — `X-Hub-Signature-256` header checked against `WHATSAPP_APP_SECRET`
   using HMAC-SHA256. If the secret is not set, the server returns **500** (fail-closed).
2. **Dev bypass** — Set `WHATSAPP_SKIP_SIGNATURE_VALIDATION=true` to disable signature checks
   for local development. Never set this in production.

## WhatsApp Formatting

WhatsApp supports limited formatting compared to Slack or web:

| Supported | Not Supported |
|-----------|---------------|
| `*bold*` | Tables |
| `_italic_` | Headers |
| `~strikethrough~` | Clickable links |
| `` ```monospace``` `` | Numbered lists |
| `> quote` | Images in text |

Messages are automatically chunked at 4,096 characters. Image captions are
limited to 1,024 characters.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Bot doesn't respond | Webhook not configured or server not running | Check webhook shows "Verified" in Meta portal |
| 401 Unauthorized | Token expired | Use a System User token (never expires) or regenerate temporary token |
| SSL certificate errors (macOS) | Missing cert bundle | `export SSL_CERT_FILE=$(python3 -c "import certifi; print(certifi.where())")` |
| Webhook verification fails | Verify token mismatch | `WHATSAPP_VERIFY_TOKEN` must match Meta webhook config exactly |
| 500 on every webhook | `WHATSAPP_APP_SECRET` not set | Set the secret, or set `WHATSAPP_SKIP_SIGNATURE_VALIDATION=true` for dev |
| Signature validation fails | Wrong app secret | `WHATSAPP_APP_SECRET` must match App > Settings > Basic |
| Messages not arriving | Not subscribed to events | Subscribe to **messages** field in webhook config |
| Non-PDF documents fail | API limitation | Only PDF documents are currently supported for document input |
| Can only message test numbers | Not in production mode | Complete business verification and request production access |
