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
2. Under **App details**, give it a name and continue.
3. Under **Use cases**, select **Connect with customers through WhatsApp**, then click **Next**.
4. Under **Business**, link the app to your Business Portfolio from step 1, then finish the **Requirements** and **Overview** steps to create the app.
5. On the app dashboard, click **Customize the Connect with customers through WhatsApp use case** (or open **Use cases** in the sidebar) to set up WhatsApp.

This creates your WhatsApp Business Account (WABA) and connects it to your app.

> For detailed steps, see Meta's [Get Started with the WhatsApp Cloud API](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started).

### 3. Get Your Token and Phone Number ID (Step 1: Try it out)

In the **Connect with customers through WhatsApp** use case, go to
**Basic setup > Step 1. Try it out**. Everything you need for testing is here.
Copy each value and set it as an environment variable as you go:

1. Meta automatically claims a **WhatsApp test number** under **Test number**. Copy the
   **Phone Number ID** shown next to it:
   ```bash
   export WHATSAPP_PHONE_NUMBER_ID="123456789"
   ```
2. Under **Access token**, click **Generate token**, then copy the token. This temporary
   token expires after ~24 hours and is only suitable for development:
   ```bash
   export WHATSAPP_ACCESS_TOKEN="EAAW..."
   ```

> The test number is enough for development — it can message any recipient you
> register on the **Step 1. Try it out** page. Even while testing, you still
> configure the webhook under **Step 2. Production setup** (steps 7–9 below).
> Adding and verifying your own business number with a permanent token is only
> required when you go to production.
> See [Add a Phone Number](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started/add-a-phone-number).

### 4. Get Your App Secret

1. In the side menu, open **App settings > Basic**.
2. Copy the **App Secret** and set it as an environment variable — this is used for
   webhook signature verification:
   ```bash
   export WHATSAPP_APP_SECRET="..."
   ```

### 5. Set the Remaining Environment Variables

You set the WhatsApp credentials in steps 3 and 4. Add the last two:

```bash
export WHATSAPP_VERIFY_TOKEN="my-verify-token"   # Any string you choose (must match webhook config)
export OPENAI_API_KEY="sk-..."                   # Or whichever model provider you use
```

### 6. Start the Server and Tunnel It

Webhook verification requires your AgentOS server to be running and publicly
reachable, so start it **before** configuring the webhook in Meta.

1. With `WHATSAPP_VERIFY_TOKEN` set (step 5), run any WhatsApp example:
   ```bash
   .venvs/demo/bin/python cookbook/05_agent_os/interfaces/whatsapp/basic.py
   ```
2. Expose it publicly with ngrok or any tunnel/gateway of your choice:
   ```bash
   ngrok http 7777
   # or: cloudflared tunnel --url http://localhost:7777
   ```
   Your webhook callback URL will be `{your-public-domain}/whatsapp/webhook`.

### 7. Configure the Webhook

1. In the use case, go to **Basic setup > Step 2. Production setup > Configure Webhooks**.
2. Set **Callback URL** to your public domain + `/whatsapp/webhook`:
   ```
   https://your-public-domain/whatsapp/webhook
   ```
3. Set **Verify Token** to the same string as your `WHATSAPP_VERIFY_TOKEN` env var.
4. Click **Verify and save** — Meta sends a GET challenge to your running server,
   which Agno verifies automatically.

> See [Set Up Webhooks](https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks)
> for details on the verification handshake and payload format.

### 8. Subscribe to Webhook Fields

After you verify and save, Meta usually opens the **Webhook fields** list and
auto-subscribes the standard fields. Confirm this happened — at minimum the
**messages** field must show **Subscribed**, or your server will never receive
incoming messages even though verification succeeded.

If the fields are not subscribed (or Meta didn't open the list), subscribe them
manually:

1. In the side menu, open **Use cases > Connect with customers through WhatsApp > Customize**.
2. Go to **Basic setup > Step 2. Production setup** and scroll down to **Webhook fields**.
3. Toggle the fields to **Subscribed**. The **messages** field is required;
   **message_template_status_update** and **history** are commonly enabled too.

### 9. Test It — and Register the Number if Needed

Send a message to the test number from any recipient on your **Step 1. Try it
out** allow-list. If your AgentOS server receives the webhook and the agent
replies, setup is complete.

If you message the number but **no webhook requests arrive** at your
tunnel/gateway, the test number must be programmatically activated — even though
the Meta dashboard shows it as "Active." Meta accepts your outgoing payloads
(returns `200 OK` with a `message_id`) but silently drops them during routing
until the number is registered. Run both calls below with your access token:

1. **Register the number** — provisions your `phone_number_id` on WhatsApp servers:
   ```bash
   curl -X POST "https://graph.facebook.com/v25.0/$WHATSAPP_PHONE_NUMBER_ID/register" \
     -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"messaging_product": "whatsapp", "pin": "123456"}'
   ```
2. **Subscribe the app to your WABA** — links your app to the Business Account:
   ```bash
   curl -X POST "https://graph.facebook.com/v25.0/<WABA_ID>/subscribed_apps" \
     -H "Authorization: Bearer $WHATSAPP_ACCESS_TOKEN"
   ```
   Replace `<WABA_ID>` with your WhatsApp Business Account ID (shown in the use
   case under **Step 1. Try it out**). This call sends no body.

After running both, message the test number again — webhooks should now arrive.

Once it works, you can keep developing as-is with the temporary token and the
provided test number, or move toward production by adding and verifying your own
business number and generating a permanent token (see
[Local Development](#local-development) and **Step 2. Production setup**).

## Local Development

For quick local testing without a full production setup:

1. **Temporary token:** Use the temporary token from step 3 (~24 hour expiry).
2. **Test numbers:** Add your personal number as a test recipient on the **Step 1. Try it out** page under "To".
   During development you can only message numbers registered here.
3. **Tunnel:** Use [ngrok](https://ngrok.com/) or [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)
   to expose your local server:
   ```bash
   ngrok http 7777
   # or: cloudflared tunnel --url http://localhost:7777
   ```
   Use the tunnel URL as your webhook Callback URL (step 7.2). The free ngrok tier
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
| Messages not arriving | Not subscribed to events | Subscribe to **messages** field in webhook config (setup step 8) |
| Outbound returns 200 but nothing delivered / no webhooks | Test number not registered | Run the `/register` and `/subscribed_apps` calls (setup step 9) |
| Non-PDF documents fail | API limitation | Only PDF documents are currently supported for document input |
| Can only message test numbers | Not in production mode | Complete business verification and request production access |
