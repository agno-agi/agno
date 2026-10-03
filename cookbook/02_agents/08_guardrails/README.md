# guardrails

Examples for input/output safety checks and policy enforcement.

## Files
- `custom_guardrail.py` - Demonstrates custom guardrail.
- `deepkeep_ai_firewall.py` - Demonstrates DeepKeep AI Firewall guardrails.
- `openai_moderation.py` - Demonstrates openai moderation.
- `output_guardrail.py` - Demonstrates output guardrail.
- `pii_detection.py` - Demonstrates pii detection.
- `prompt_injection.py` - Demonstrates prompt injection.
- `ismalicious_untrusted_content.py` - Gates a public-page fetch and its returned text with IsMalicious.
- `ismalicious_guard.py` - Cookbook-only HTTP adapter for the IsMalicious tool hook.

## Prerequisites
- Load environment variables with `direnv allow` (including `OPENAI_API_KEY`).
- Create the demo environment with `./scripts/demo_setup.sh`, then run cookbooks with `.venvs/demo/bin/python`.
- Some examples require optional local services (for example pgvector) or provider-specific API keys.

## Run
- `.venvs/demo/bin/python cookbook/02_agents/<directory>/<file>.py`

## IsMalicious: check before fetch and before the next model call

`ismalicious_untrusted_content.py` wraps `fetch_public_page` with an Agno
`tool_hooks` callback. The hook checks the destination using `GET /gate/url`,
executes the fetch once, then scans the entire returned text using `POST
/gate/scan` before returning it to Agno. These are the endpoints behind the
IsMalicious MCP tools `check_url` and `scan_before_use`. This recipe uses HTTP
directly and does not start an MCP server.

Install and configure:

```bash
uv pip install -e 'libs/agno[openai]'
# Set OPENAI_API_KEY, ISMALICIOUS_API_KEY and ISMALICIOUS_API_SECRET
# in your local secret manager or environment before running.
python cookbook/02_agents/08_guardrails/ismalicious_untrusted_content.py
```

Create an [IsMalicious account](https://ismalicious.com/app/account) to obtain
the key and secret pair. The hosted API has plan-dependent scan quotas and
paid tiers. These two checks consume the separate **scan quota**, not the
indicator-check request quota. The adapter encodes `apiKey:apiSecret` as Base64
in `X-API-KEY`; the key component alone is not the credential. Each approved
page normally uses two gate calls, with no automatic retry on quota errors.
See the [API documentation](https://ismalicious.com/api-docs) and
[MCP server](https://github.com/hexablob/ismalicious-mcp-server).

The demo approves exactly `https://example.com/`. Change the operator-owned
allowlist in the source for another public page. The model cannot expand it.
Keep it restricted to public pages you intend to inspect. This exact-URL policy
is not a DNS rebinding or network egress firewall. Redirects are refused rather
than followed to an unchecked destination.

The policy is explicit:

- `allow`: pass the original text unchanged. It means the current gate rules
  did not block, not that the text or destination is known-good. The API can
  return `allow` for an unknown link; that is not renamed `clean` by this hook.
- `warn`: stop the run. Review outside this run before deciding whether to retry.
- `block`: stop before fetching or before the text reaches the next model call.
- Failed HTTP calls, timeout, quota exhaustion, malformed decisions, incomplete
  embedded-link coverage and unsupported text: stop without an unscanned fallback.

The remote service receives the destination URL, the fetched text and its source
URL. The model receives the allowed original text. Use public, non-confidential
data in this example; do not submit secrets or sensitive documents without an
appropriate data-sharing policy. The adapter does not log API headers, response
bodies or fetched text. TLS verification remains enabled; credentialed redirects
are refused and gate calls have a 15-second HTTP timeout. `mode="fast"` uses the
current heuristic gate, with no claim of complete prompt-injection detection.

This recipe covers synchronous `Agent.run` / `print_response` and the one
registered text-page tool only. It does not intercept other tools, browser
navigation, MCP transports, user input, knowledge loading, model output, binary
attachments or incremental tool-result streams. `Agent.arun` is refused for
this hook. The example buffers at most 128 KiB of page text, rejects excess
instead of truncating, and refuses a scan whose link coverage is truncated.
API calls are private helper methods, not agent tools, so they do not rescan
themselves. Do not remove the hook or expose an alternative ungated fetch tool.

Run the offline tests with no API or model credentials:

```bash
uv pip install pytest
python -m pytest -q -o log_cli=false libs/agno/tests/unit/cookbook/test_ismalicious_guard.py
```

The tests include the real Agno `Agent.run` and `OpenAIChat` call chain with
synthetic HTTP transports. They verify refusal before the fetch, refusal before
the next model request, original allow text, warning policy and HTTP failure
handling. They do not measure live detector accuracy or test an authenticated
production account.
