# Baizhi Agent Toolkit

`BaizhiTools` provides three native Agno tools backed by the hosted Streamable HTTP MCP endpoint `https://agent-toolkit.app.baizhi.cloud/mcp`: `websearch_search`, `web_scrape`, and `web_extract`. Each has a synchronous method and an asynchronous `a`-prefixed method. The native toolkit maps domain lists into the server's nested `filter` object and extraction fields into its `fields` object; it does not use an undocumented REST API.

The service backend is closed source. [Official integration documentation](https://github.com/chaitin/baizhi-agent-toolkit) is public; its license is separate from the online service's terms and fees. Create your own dedicated key in the [Baizhi console](https://agent-toolkit.app.baizhi.cloud/) and set `BAIZHI_API_KEY` through your secret manager. Never paste a key into the prompt, source, command-line arguments, or logs. Tool calls may consume paid credits and inputs are sent to the hosted service. Do not send private URLs or sensitive data without authorization.

## Setup

From a source checkout, install the MCP and OpenAI dependencies in your cookbook environment:

```sh
uv pip install --python .venvs/demo/bin/python -e libs/agnoctl -e 'libs/agno[mcp,openai]'
```

MCP dependencies require a compatible Python version (tested with Python 3.12, MCP 2.2.0 and FastMCP 4.0.5). Set `BAIZHI_API_KEY` and `OPENAI_API_KEY` in the process environment before running an agent. The toolkit performs no network request at construction time.

## Run

```sh
.venvs/demo/bin/python cookbook/91_tools/baizhi/research.py
.venvs/demo/bin/python cookbook/91_tools/baizhi/research.py --async
```

The example exposes only search, caps the agent at one tool call, and pauses for explicit approval before executing it. Approval defaults to no. Model usage can incur separate charges. `--inspect` prints the selected schema without making model or MCP requests; it needs `BAIZHI_API_KEY` to construct the toolkit but does not need an OpenAI key.

```sh
.venvs/demo/bin/python cookbook/91_tools/baizhi/research.py --inspect
.venvs/demo/bin/python cookbook/91_tools/baizhi/research.py --inspect --async
```

## Direct calls and scope

Use `tools.web_scrape(url)` / `await tools.aweb_scrape(url)` for page text, or `tools.web_extract(url, fields={"title": "string"})` / its async variant for structured extraction. Extraction requires `fields`, `instruction`, or both. Supported field types are `string`, `number`, `boolean`, and `array`. Reading and extraction explicitly disable downloadable exports.

Search filters accept bare domain names or IP addresses, without URL paths, ports, or credentials. Page URLs containing a username or password are rejected before contacting the service.

The three constructor flags `enable_search`, `enable_scrape`, and `enable_extract` control both sync and async registration. `all=True` enables only these three supported tools, never the full remote catalog. Direct calls to a disabled tool are also rejected. Use Agno's `requires_confirmation_tools` for approval in agents; direct Python calls bypass the agent approval flow and may be billable.

Results retain the MCP `content`, `structuredContent` when provided, and `isError` fields as JSON. Inspect `isError` before using results. This integration makes no blanket read-only or idempotency claim about the service.

During a Baizhi call, filters on the MCP SDK's transport/session loggers redact the current key from messages and omit exception tracebacks that may include raw service responses. These filters retain diagnostic messages and log levels; unrelated calls outside that task context keep their normal logging behavior.

Each call owns and closes its MCP session. `timeout` bounds initialization, execution and cleanup together. There is no application retry: a timeout does not prove that a billable call did not execute. Use async methods inside an existing event loop. A request hook requires every request to use the fixed endpoint, including redirects managed by the MCP SDK. Environment proxy discovery is disabled; environment HTTP proxies are not supported by this toolkit.

## Verification

The committed fixture contains only the three tool definitions from authenticated discovery on 2026-09-20; discovery made zero tool calls. Unit tests use synthetic credentials and in-memory HTTP responses with the real MCP SDK and Agno function dispatch. They do not establish current service health, availability, uptime, billing behavior, or model-generated answer quality. See `TEST_LOG.md` for the checks actually run.
