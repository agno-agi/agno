# Public documentation pages

`public_pages.py` uses one PostgreSQL database for the Knowledge catalog, quota-bounded FileSystem, vectors, sessions, durable jobs and shared public request counters. It demonstrates application-owned retrieval through an explicit callable dependency, explicit search/read/grep tools, native MCP and a typed protected sync workflow.

The `docs_context` dependency is an async function that receives `run_input`, calls the application's `search_docs` function and returns evidence. Agno awaits it before pre-hooks and prompt construction. The application chooses the query and places the result through `{docs_context}` in its instructions. `add_dependencies_to_context` already defaults to `False`; it stays unset so dependencies are not additionally appended to the user message. Callables can also request `session` for previous-turn retrieval policy, plus `agent` and `run_context`.

Dependency resolution keeps its existing lifecycle: a successful value is reused on a model retry, while a fresh ordinary run resolves the configured callable again. It does not emit pre-hook events. On continuation, `run_input` refers to the original stored input (or `None` if it was not stored), not additional continuation instructions. Use a pre-hook when retrieval must run after another hook changes the input or when hook lifecycle events are needed. This cookbook change does not change the separate Docs Agent application's pre-hook or retrieval policy.

## Setup

Use the repository demo environment with `agno[os,mcp,pages]` and `openai` installed. Start `./cookbook/scripts/run_pgvector.sh` and create a separate `page_demo` database. Its user needs permission to create the vector extension, tables and indexes. Use a direct PostgreSQL connection for advisory locks.

```sh
export OPENAI_API_KEY=...
export PAGE_DEMO_DB_URL=postgresql+psycopg://ai:ai@localhost:5532/page_demo
export PAGE_DEMO_INDEX_URL=https://docs.agno.com/llms.txt
export PAGE_DEMO_SYNC_TOKEN=local-demo-secret
.venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_pages.py sync
.venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_pages.py chat
.venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_pages.py serve
```

Sync reconciles the entire configured index and makes embedding calls. Choose a small source for the first run. Discovery and redirects stay on the configured public HTTPS origin; private destinations are rejected. The store allows 4 MiB per file and 256 MiB per namespace. Call `setup`/`asetup` during trusted startup.

In another terminal:

```sh
curl http://localhost:7777/readyz
curl http://localhost:7777/agents
curl http://localhost:7777/mcp/server-card
curl -N http://localhost:7777/agents/docs/runs -F 'message=What is an agent?' -F stream=true
.venvs/demo/bin/python cookbook/05_agent_os/27_public_pages/public_pages.py mcp-client
curl http://localhost:7777/workflows/sync-docs/runs \
  -H "Authorization: Bearer $PAGE_DEMO_SYNC_TOKEN" \
  -F 'message={"reason":"manual"}' -F stream=false -F background=true
```

The background trigger returns run/session IDs. Poll `/workflows/sync-docs/runs/<run_id>?session_id=<session_id>` with the same bearer credential until completion. Execution and polling use the durable Agno queue.

An application can validate discovery before any page fetching, embedding, publication or pruning. Both sync methods accept an optional keyword-only `validate_discovery` callback. It receives the discovered count and current published count for this namespace under the writer lock. Keep it fast and synchronous; return `None` to accept or raise `ValueError` to abort. The async method runs it in the existing worker. For example, the following caller-owned policy rejects an unexpectedly shortened index:

```python
def validate_index(discovered: int, published: int) -> None:
    if published and discovered < published // 2:
        raise ValueError("Index unexpectedly shrank; verify the source before continuing")


await knowledge.async_sync_pages(url=index_url, validate_discovery=validate_index)
```

An application may bind an explicit override into its callback. Acceptance still requires the existing discovery and processing checks before pruning; the callback cannot turn empty discovery or partial processing into a successful reconciliation. Without a callback, the framework applies no shrink threshold. Validation adds one namespace-scoped catalog count only on sync, not on query traffic.

## Explicit retrieval and customization

`attach_docs_context` calls the same `search_docs` exposed to the model and places its bounded JSON in `{docs_context}` before the first model call. The example owns its instructions and evidence formatting; customize that hook for query alternatives or full-page rendering. No Knowledge object is attached to the Agent. The model can use the three explicitly named tools. Follow-up suggestions use a separately configured model after the answer.

Reads return `revision` and `next_offset`; preserve both for consistent Unicode-safe continuation. Literal grep reports incomplete scans. Search failures produce safe error codes. Source metadata/text/vectors publish atomically and failed refreshes keep the prior revision available.

`search_pages` and `asearch_pages` accept the keyword-only `max_output_bytes` option, defaulting to 24,000 with an allowed integer range of 24,000–32,000. It bounds the UTF-8 serialized search result, including framework metadata; ranking and query limits stay the same. An adapter that removes framework fields can explicitly request `await knowledge.asearch_pages(query, max_output_bytes=32_000)` before applying its own smaller output limit. The tools in this example return the framework JSON directly, so they keep the default. This option does not change read/list/grep limits or add a model-controlled tool parameter. More retained evidence can increase rendering work and model tokens; the allowance is not a latency optimization.

## Optional search tuning

`PgVector(vector_index=HNSW(ef_search=200))` controls the HNSW search breadth used
by page search. Page search honors the existing HNSW setting; it has no separate
`ef_search` override. Lower search breadth can retain fewer vector candidates and
change retrieved evidence. The SQL candidate limit alone does not guarantee that
many approximate-nearest-neighbor results.

`Knowledge(page_search=PageSearchConfig(...))` supplies typed, transaction-local
PostgreSQL planner options. Unset scan preferences, parallel costs, scan thresholds
and worker counts inherit the database configuration. The default
`plan_cache_mode="force_custom_plan"` lets parameterized searches use the
namespace-specific partial HNSW index; set it to `None` to inherit the database
setting. Parallel alternative queries use zero PostgreSQL parallel workers to
bound nested parallelism. They reuse existing pooled connections; cold optional
queries can run on the parent's snapshot instead of opening another connection.

The example keeps `HNSW(ef_search=200)` explicit and omits `page_search`, using
the framework defaults described above. No planner-cost or scan-preference
overrides are needed to run it. Applications can optionally supply
`PageSearchConfig` to tune index preference, parallel costs, scan thresholds and
worker counts after measuring their own corpus and load. Docs Agent's deployment
tuning belongs in that application's configuration.
`min_parallel_table_scan_size` uses PostgreSQL blocks, normally 8 KiB. The typed
configuration accepts no arbitrary SQL or deadline overrides.

## Addresses, authentication and limits

`PAGE_DEMO_SERVER_URL` sets the MCP client's destination, defaulting to `http://localhost:7777`. `PAGE_DEMO_MCP_URL` optionally sets the existing explicit MCP card URL; otherwise native request-derived discovery applies. For a proxy prefix, configure the mount or ASGI root path consistently. Add the deployed host to MCP allowed hosts and the browser origin to CORS.

Only the selected Agent, native MCP and protected sync Workflow are exposed. Sessions, configuration and unselected components are closed. Workflow trigger/status require verified bearer credentials even while chat is anonymous. Scoped service accounts require the workflow run/read permissions and cannot use internal-service exemptions. `PAGE_DEMO_SYNC_TOKEN` configures the existing internal-service principal for a trusted deployment hook; keep it out of browsers and MCP clients.

Public chat defaults to 10 requests/client/minute, 50 globally/minute, 80/client/day and 3,000 globally/day. Cancel and MCP use separate shared buckets. PostgreSQL counters use the stable AgentOS ID across replicas. Default identity ignores arbitrary forwarded headers; customize `PublicSurface.client_id` only for an edge-overwritten trusted header. Request bodies, output, duration and concurrency are bounded; uploads are disabled here. CORS includes admission failures and readiness checks table preparation.

Successful non-SSE responses are buffered up to `PublicSurface.max_output_bytes` (1 MiB by default) before sending headers. Overflow returns a complete `503` JSON response with `error.code="output_limit"`. The limit applies to the entire serialized response, including any attached input or run metadata, not just the model's answer. Accepted response headers and body are preserved; SSE retains its existing streaming behavior.

In-process cancellation alone does not guarantee delivery across replicas; configure an existing shared cancellation backend when needed. Queues, source synchronization and public counters use PostgreSQL.

## Compatibility

Page result types and errors live in `agno.knowledge.page.types` and are re-exported from `agno.knowledge.page`, so imports such as `from agno.knowledge.page import Page, SearchResult` remain unchanged. Importing these types does not load the private discovery/coordinator modules or their PostgreSQL/vector dependencies. The chunking strategy remains in `agno.knowledge.chunking.page`.

All `Knowledge` constructor arguments are keyword-only. `content_db` is preferred;
`contents_db` remains a supported keyword and read/write alias without warnings.
Both names share the existing dataclass field; serialization and
`dataclasses.replace(..., contents_db=...)` retain its legacy spelling. Distinct
objects supplied under both keywords are rejected. Positional constructor calls
must be updated to use keyword arguments. Other Knowledge configurations retain
their behavior.
Page storage supports synchronous PostgreSQL adapters in one logical database;
custom embedders must enforce a timeout or use the supported OpenAI embedder.

Startup validates an already-initialized schema and namespace without waiting for
the long-running sync writer lock. First setup and required schema changes remain
serialized and must finish validation before the instance becomes ready.

Page-mode `search`/`asearch` and `retrieve`/`aretrieve` return revision-checked ranked chunks as Documents without expanding pages. Filters are unsupported; the configured corpus is shared among readers. Existing KnowledgeProtocol signatures and the ordinary `search_knowledge_base` tool remain. Applications needing completeness flags should consume `search_pages` directly. No new Agent/Team context machinery or Message retention alias is introduced.

Public non-streaming Agent failures use a safe `503 run_failed` JSON response,
matching the safe error behavior of streaming Agent runs. Successful responses
retain their content. Authenticated sync operators retain workflow diagnostics.

Actual execution evidence is in [TEST_LOG.md](TEST_LOG.md).
