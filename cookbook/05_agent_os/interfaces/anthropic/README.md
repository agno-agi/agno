# Anthropic Cookbook

Examples for `interfaces/anthropic` in AgentOS. Each example boots an AgentOS app
whose `/anthropic/v1/messages` endpoint speaks the Anthropic Messages API, so the
Anthropic Python SDK and tools like Claude Code (pointed at the server via
`ANTHROPIC_BASE_URL`) can use Agno agents and teams as upstream Claude models.

## Files
- `basic.py` — Single agent exposed as one Claude-compatible model.
- `coder.py` — Local-first coding agent (file ops, GitHub read-only, web search).
- `researcher.py` — Web research agent powered by Parallel.
- `team.py` — **Multi-model example.** One `AnthropicInterface` exposes the
  coder, the researcher, and a routing team — each visible as a separate model
  in Claude Code's model picker.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- Optionally set `AGNO_ANTHROPIC_INTERFACE_API_KEY` to require a static API key
  on every request (mirrors how Claude Code authenticates to gateways).

## Trying it from the Anthropic SDK

```python
import anthropic

client = anthropic.Anthropic(api_key="dev", base_url="http://localhost:9001/anthropic")
msg = client.messages.create(
    model="claude-agno-assistant",
    max_tokens=256,
    messages=[{"role": "user", "content": "Tell me a fact about Saturn."}],
)
print(msg.content[0].text)
```

## Trying it from Claude Code

```bash
export ANTHROPIC_BASE_URL=http://localhost:9001/anthropic
export ANTHROPIC_AUTH_TOKEN=dev
export CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1
claude
```

For `team.py`, the model picker in Claude Code will list:
- `claude-agno-coder`
- `claude-agno-researcher`
- `claude-agno-coder-researcher-team`

Switching models in the UI routes the next request to the matching agent or
team — all from a single `AnthropicInterface`.
