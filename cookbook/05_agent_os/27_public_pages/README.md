# Public documentation pages

`public_pages.py` uses one PostgreSQL database for the Knowledge catalog, quota-bounded FileSystem, vectors, sessions, durable jobs and shared public request counters. It demonstrates application-owned retrieval through a visible pre-hook, explicit search/read/grep tools, native MCP and a typed protected sync workflow.

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

## Addresses, authentication and limits

`PAGE_DEMO_SERVER_URL` sets the MCP client's destination, defaulting to `http://localhost:7777`. `PAGE_DEMO_MCP_URL` optionally sets the existing explicit MCP card URL; otherwise native request-derived discovery applies. For a proxy prefix, configure the mount or ASGI root path consistently. Add the deployed host to MCP allowed hosts and the browser origin to CORS.

Only the selected Agent, native MCP and protected sync Workflow are exposed. Sessions, configuration and unselected components are closed. Workflow trigger/status require verified bearer credentials even while chat is anonymous. Scoped service accounts require the workflow run/read permissions and cannot use internal-service exemptions. `PAGE_DEMO_SYNC_TOKEN` configures the existing internal-service principal for a trusted deployment hook; keep it out of browsers and MCP clients.

Public chat defaults to 10 requests/client/minute, 50 globally/minute, 80/client/day and 3,000 globally/day. Cancel and MCP use separate shared buckets. PostgreSQL counters use the stable AgentOS ID across replicas. Default identity ignores arbitrary forwarded headers; customize `PublicSurface.client_id` only for an edge-overwritten trusted header. Request bodies, output, duration and concurrency are bounded; uploads are disabled here. CORS includes admission failures and readiness checks table preparation.

In-process cancellation alone does not guarantee delivery across replicas; configure an existing shared cancellation backend when needed. Queues, source synchronization and public counters use PostgreSQL.

## Compatibility

`Knowledge` retains its existing `contents_db` constructor and positional fields; `page_store` is keyword-only. Other Knowledge configurations retain their behavior. Page storage supports synchronous PostgreSQL adapters in one logical database; custom embedders must enforce a timeout or use the supported OpenAI embedder.

Page-mode `search`/`asearch` and `retrieve`/`aretrieve` return revision-checked ranked chunks as Documents without expanding pages. Filters are unsupported; the configured corpus is shared among readers. Existing KnowledgeProtocol signatures and the ordinary `search_knowledge_base` tool remain. Applications needing completeness flags should consume `search_pages` directly. No new Agent/Team context machinery or Message retention alias is introduced.

Actual execution evidence is in [TEST_LOG.md](TEST_LOG.md).
