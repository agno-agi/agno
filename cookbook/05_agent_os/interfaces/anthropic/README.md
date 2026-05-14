# Anthropic Cookbook

Examples for `interfaces/anthropic` in AgentOS. Each example boots an AgentOS app
whose `/v1/messages` endpoint speaks the Anthropic Messages API, so the Anthropic
Python SDK and tools like Claude Code (pointed at the server via `ANTHROPIC_BASE_URL`)
can use the Agno agent as the upstream model.

## Files
- `basic.py` — Basic Anthropic Messages API gateway backed by a single agent.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Optionally set `AGNO_ANTHROPIC_INTERFACE_API_KEY` to require a static API key
  on every request (mirrors how Claude Code authenticates to gateways).

## Trying it from the Anthropic SDK

```python
import anthropic

client = anthropic.Anthropic(api_key="dev", base_url="http://localhost:9001")
msg = client.messages.create(
    model="claude-agno-assistant",
    max_tokens=256,
    messages=[{"role": "user", "content": "Tell me a fact about Saturn."}],
)
print(msg.content[0].text)
```

## Trying it from Claude Code

```bash
export ANTHROPIC_BASE_URL=http://localhost:9001
export ANTHROPIC_AUTH_TOKEN=dev
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
claude
```
