# Lark Interface Test Log

## test results

### basic.py

**Status:** PASS

**Description:** End-to-end test with a real Feishu custom app (app_id
`cli_xxxxxxxxxxxxxxxx`), DeepSeek model (`deepseek-v4-flux`), encrypt_key +
verification_token enabled, ngrok public webhook tunnel, and a group chat
where the bot was @mentioned.

**Result:** Full message round-trip verified:

1. User @mentioned the bot in a Feishu group chat with message "你好".
2. Feishu delivered an encrypted `im.message.receive_v1` event to the webhook.
3. agno decrypted the event (AES-256-CBC with encrypt_key), verified the
   signature (SHA256 timestamp+nonce+key+body), and validated the
   verification_token.
4. `get_bot_open_id` fetched the bot's open_id (`ou_6ce840c...`) and matched
   it against the event's `mentions` array — mention check passed.
5. DeepSeek agent was invoked via `entity.arun()` with streaming enabled.
6. An interactive card was sent as a reply and PATCHed in place as tokens
   streamed.
7. The user received the bot's response in the Feishu group chat.

No errors or warnings in the agno log during processing. Session persistence
via SQLite (`tmp/lark_basic.db`) verified across the run.

**Bugs found and fixed during testing:**
- `url_verification` challenge was stripped by `response_model` filtering —
  fixed by returning `JSONResponse` directly.
- Challenge handling order: moved before signature verification because Lark
  does not always sign the challenge request.
- `LarkClient` httpx inherited the host's SOCKS proxy env — fixed with
  `trust_env=False` so Lark/DeepSeek APIs connect directly.
- `get_bot_open_id` returned `None` because `/bot/v3/info` puts `bot` at the
  top level (not inside `data`) — fixed to parse the full response payload.

---
