# Public documentation pages

`public_pages.py` uses one PostgreSQL database for the Knowledge catalog, a quota-bounded FileSystem, vectors, sessions, and shared public request counters. It demonstrates initial references, custom tool names/instructions, Agent and Team selection, native MCP, and a typed protected sync workflow.

## Setup

Use the repository demo environment with `agno[os,mcp,pages]` and `openai` installed. Start the cookbook PostgreSQL service with `./cookbook/scripts/run_pgvector.sh`, then create a separate `page_demo` database on that local service. Its user needs permission to create the `vector` extension, tables, and indexes. Point `PAGE_DEMO_DB_URL` at that database if its port differs from 5532.

```sh
export OPENAI_API_KEY=...
export PAGE_DEMO_DB_URL=postgresql+psycopg://ai:ai@localhost:5532/page_demo
export PAGE_DEMO_INDEX_URL=https://docs.agno.com/llms.txt
export AGENTOS_URL=http://localhost:7777
export PAGE_DEMO_SYNC_TOKEN=local-demo-secret
.venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_pages.py sync
.venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_pages.py chat
.venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_pages.py serve
```

The `sync` command reconciles the entire configured index and makes embedding calls. Choose a small documentation source for an inexpensive first run. Discovery and redirects remain on the configured public HTTPS origin; local/private source destinations are rejected. The store allows 4 MiB per file and 256 MiB per namespace. Call `setup`/`asetup` during trusted startup, before serving queries. Use a direct PostgreSQL connection for session advisory locks.

In another terminal:

```sh
curl http://localhost:7777/readyz
curl http://localhost:7777/agents
curl http://localhost:7777/teams
curl http://localhost:7777/mcp/server-card
curl -N http://localhost:7777/agents/docs/runs -F 'message=What is an agent?' -F stream=true
.venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_pages.py mcp-client
curl http://localhost:7777/workflows/sync-docs/runs \
  -H "Authorization: Bearer $PAGE_DEMO_SYNC_TOKEN" \
  -F 'message={"reason":"manual"}' -F stream=false
```

The public Team is `docs-team`. Its `researcher` member is not independently public. Sessions, configuration, arbitrary components, and write tools are closed to anonymous requests. Native MCP publishes exactly `search_docs`, `read_docs`, and `grep_docs`; default/lifecycle tools are disabled. Full-page reads return `next_offset` for Unicode-safe continuation; grep explicitly reports an incomplete scan. All model-facing errors use safe codes.

## Addresses, authentication, and limits

`AgentOS.url` prefers an explicit argument, then `AGENTOS_URL`. Without either, scheduler and MCP discovery keep their existing fallbacks. The resolved base includes deployment prefixes and derives `/mcp`. `PAGE_DEMO_SCHEDULER_URL` and `PAGE_DEMO_MCP_URL` demonstrate the existing explicit scheduler/card overrides; neither changes the socket bind address. When using a proxy prefix, mount the application at that prefix or configure ASGI root_path consistently. Forwarded headers do not override an explicit canonical URL. Add the real host to the MCP host allowlist and the browser origin to CORS before using a remote deployment.

Workflow trigger and status routes require verified bearer credentials even while chat is anonymous. Scoped service accounts need the selected workflow's run/read permissions; they cannot submit scheduler-only overrides. `PAGE_DEMO_SYNC_TOKEN` configures the existing internal-service principal for a trusted scheduler or deploy hook. Use the same token on independently configured scheduler and callback instances. Keep that credential out of browsers and MCP clients.

Public chat defaults to 10 requests/client/minute, 50 globally/minute, 80/client/day and 3,000 globally/day. Cancel and MCP use separate shared buckets. Counters live in PostgreSQL, keyed by the stable AgentOS id; replicas share admission. Socket-derived client identity ignores arbitrary forwarded headers. Configure `PublicSurface.client_id` only for a deployment header your trusted edge overwrites. Run bodies, uploads, durations, output and active concurrency are bounded; uploads are disabled in this example. CORS includes failures and readiness is checked after table preparation.

Cancellation follows existing AgentOS deployment behavior: in-process cancellation alone is not a cross-replica delivery guarantee. Configure the existing shared cancellation backend when requests can land on different replicas. Queues, source synchronization and public counters still use PostgreSQL.

## Compatibility

`Knowledge.content_db` and `contents_db` name one value; conflicting constructor objects fail. Legacy knowledge without `page_store` keeps its behavior. Page storage supports the listed synchronous PostgreSQL adapters in one logical database; custom embedders must accept and enforce a `timeout` keyword, or use the supported OpenAI embedder.

`add_knowledge_to_context` retrieves one separate user-role reference message per run. `search_knowledge` independently enables page tools. This example supplies custom tools and leaves automatic tool registration off. References remain available during the active tool loop, stay out of recorded history, and are refreshed before checkpoint continuation. `Message.add_to_history` aliases `add_to_agent_memory`; normal Pydantic serialization retains the existing key, while the existing `to_dict()` intentionally omits the retention flag.

Actual local/live execution evidence is in [TEST_LOG.md](TEST_LOG.md).
