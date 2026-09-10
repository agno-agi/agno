# AgentOS File System

## Runnable AgentOS examples

Each cookbook starts an AgentOS server. Connect the control plane to
`http://127.0.0.1:7777`, choose the agent in Chat, then browse its files on the
File System page. Run one example at a time because they share port 7777.

| Cookbook | Setup | Prompt to try |
| --- | --- | --- |
| `basic.py` | Managed `filesystem=True` with SQLite | Save our meeting decisions to notes/decisions.md. |
| `with_postgres.py` | Managed files using the PostgreSQL database supplied by AgentOS | Save our deployment checklist to notes/deployment.md. |
| `with_local_files.py` | Files on disk, sessions in SQLite | Save a project outline to notes/project.md. |
| `with_custom_namespace.py` | Explicit namespace and file/namespace size limits | Save three product decisions to decisions/product.md. |
| `with_shared_files.py` | Researcher and Editor share one filesystem | Ask Researcher to save briefs/launch.md; ask Editor to read it and save drafts/launch.md. |
| `with_user_isolation.py` | JWT-authenticated users get separate managed files | Save my preferences to notes/preferences.md, then reconnect as another user. |
| `with_knowledge.py` | Read-only published documentation through `filesystem=pages` | Explore the docs and explain a concept with its source path. |
| `with_existing_knowledge.py` | Reuse a configured Knowledge instance, including its vector store/embedder | Read one reference page and summarize it with a citation. |
| `with_knowledge_and_notes.py` | One agent with read-only documentation and writable notes | Read one reference page and save a cited summary to notes/summary.md. |

`knowledge_filesystem.py` is the existing alternate shorthand example.
These are applications, not automated test harnesses. No examples or tests have
been run; see `TEST_LOG.md`.

### Start an example

Use the demo environment with local Agno and the relevant dependencies installed.
Set `OPENAI_API_KEY` for agent conversations. SQLite examples persist under
`tmp/`; they do not delete their files on exit.

```sh
.venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/with_local_files.py
```

Replace the filename with the example you want to use.

- Postgres files: set `FILESYSTEM_DB_URL` to an existing demo PostgreSQL database.
- Local files: optionally set `FILESYSTEM_ROOT`; the default is `tmp/agent_files`.
  Files are stored inside its `local-assistant` namespace directory. A mounted
  Docker volume works as this root; it is not access to arbitrary host files.
- Knowledge: set `FILESYSTEM_KNOWLEDGE_DB_URL` and sync with
  `with_knowledge.py sync --url ...` as described below. All three reference-docs
  examples reuse that corpus and matching vector table. Serving never syncs.
- User isolation: set a strong `JWT_VERIFICATION_KEY` and configure the client
  with a short-lived HS256 token. Its audience is `isolated-files-os`, its subject
  identifies the user, and its scopes should include `agents:read`,
  `agents:personal-assistant:run`, `sessions:read`, and `sessions:write`.
  Use distinct subjects to see separate files. Never expose the signing secret
  to a browser client or use an admin token to demonstrate regular-user isolation.

Most examples are unauthenticated local demos bound to loopback. Configure
authentication and authorization before deployment; SQLite is for local use.
Explicit shared namespaces stay shared—AgentOS only derives per-user namespaces
for `filesystem=True`. The browser is read-only even when agents have write tools.

### Using the File System page

After a chat creates a file, refresh the File System page and select its source.
Navigate directories, follow breadcrumbs, search file contents, and open a text
preview. Both sources in `with_shared_files.py` show the same files.

For `with_knowledge_and_notes.py`, select the agent's working files for notes or
**Reference documentation — Knowledge** for published pages. The manually attached
page toolkit needs explicit Knowledge registration and startup setup; the example
includes both without adding custom HTTP endpoints.

Plain files do not require Knowledge or a vector database. The current
`PageFileSystem` wraps Knowledge's published-page APIs, whose coordinator requires
PgVector. Reading and literal search do not generate embeddings; source sync and
semantic search do. Git and remote object storage are not native backends in
these examples.

## Managed agent files

`basic.py` enables durable files with one agent setting:

```python
Agent(id="filesystem-agent", db=db, filesystem=True)
```

You can also supply a configured filesystem directly:

```python
from agno.fs import FileSystem

fs = FileSystem(db, namespace="agents/research-agent")
agent = Agent(id="research-agent", db=db, filesystem=fs)
```

The explicit form keeps the supplied backend, namespace, and limits. The
application owns its isolation policy; AgentOS only derives a namespace for the
managed `filesystem=True` shorthand.

The agent receives its filesystem tools automatically. With the default
`user_isolation=False`, the namespace is shared by users of that agent:

```text
agents/{agent_id}
```

When `AuthorizationConfig(user_isolation=True)` is enabled, it becomes:

```text
users/{user_id}/agents/{agent_id}
```

In isolated mode the user id comes from trusted run/request context and missing
identity fails closed. AgentOS exposes only read-only browser routes:

- `GET /agents/{agent_id}/files`
- `GET /agents/{agent_id}/files/content`
- `GET /agents/{agent_id}/files/search`

The listing and search routes accept `page` and `limit` and return pagination
metadata. The API does not accept a namespace or provide write/delete routes.

## Knowledge pages as the agent filesystem

`with_knowledge.py` attaches read-only documentation directly:

```python
from agno.knowledge.page import PageFileSystem

pages = PageFileSystem(db=db, namespace="reference-docs")
agent = Agent(
    id="docs-assistant",
    model=OpenAIResponses(id="gpt-5.6-luna"),
    filesystem=pages,
)
agent_os = AgentOS(db=db, agents=[agent])
```

The shorthand creates Knowledge, its PostgreSQL page store, a namespace-derived
PgVector table, and `text-embedding-3-small` embeddings (1536 dimensions). Storage
defaults are 4 MiB per file and 256 MiB per namespace. Override `name`, `table_name`,
`embedder`, `vector_db`, or the storage limits when needed. The cookbook preserves
its previous `reference_page_vectors` table and display name explicitly.

The agent gets `query_pages` and read-only guidance automatically. AgentOS discovers
the underlying Knowledge and prepares its tables during startup when
`auto_provision_dbs=True` (the default). No manual tools list, Knowledge registration,
or custom lifespan is required. Construction and startup never sync documents.

This replaces writable working files for this agent. It cannot save notes. Existing
notes are not deleted. `knowledge_filesystem.py` demonstrates the same shorthand.
For both capabilities, keep `filesystem=True` and explicitly
add `tools=[pages.tools()]`, registering `pages.knowledge` with AgentOS as before.

Existing `PageFileSystem(knowledge=knowledge)` remains supported. Do not mix that
form with database/storage options. Persisted agent configs reference Knowledge by
name and namespace; restoration requires that same named Knowledge in the Registry
(AgentOS registers it automatically for code-defined top-level agents).

The cookbook uses AgentOS's built-in routes without adding custom endpoints.
In the source-aware File System page, select **Reference documentation — Knowledge**.
The legacy agent-only browser does not list this read-only page filesystem as a
working-file store.

### Setup and run

Use the demo environment with `agno[os,pages]`, `openai`, `psycopg`, and `pgvector`
installed. Start PostgreSQL with pgvector (for example through
`./cookbook/scripts/run_pgvector.sh`) and create a dedicated `filesystem_knowledge`
database. Its role needs permission to provision the required tables and vector
extension. Knowledge's catalog, page store, and vectors must share that database;
use a direct connection for advisory locks.

```sh
export FILESYSTEM_KNOWLEDGE_DB_URL=postgresql+psycopg://ai:ai@localhost:5532/filesystem_knowledge
export OPENAI_API_KEY=...

# Fetch and embed the selected index. Prefer a small index for the first run.
.venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/with_knowledge.py sync --url https://docs.agno.com/llms.txt

# Read the docs through the agent's automatically attached query_pages tool.
.venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/with_knowledge.py chat

# Serve the agent (the default mode) on http://127.0.0.1:7777; OpenAPI is at /docs.
.venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/with_knowledge.py
```

Sync makes embedding calls and reconciles the selected index, including removals
after a successful reconciliation. Use a dedicated demo database and keep the
source URL stable. Serving initializes storage but does not sync it. Agent runs
and semantic search require the model provider key; listing and reading already
published pages do not make model calls.

### Explicit sync and standalone use

Outside AgentOS, call `pages.setup()` (or `await pages.asetup()`) before using an
unprepared store. Sync remains an explicit operation:

```python
pages.setup()
report = pages.sync_pages(url="https://docs.agno.com/llms.txt")
# Async: await pages.async_sync_pages(url="https://docs.agno.com/llms.txt")
```

To explore the reference documentation, ask the agent to use `query_pages` with
`ls`, `tree`, `cat`, or `rg`, or select its Knowledge source in the browser.

### Source-aware browser API

- `GET /filesystem/sources` lists authorized, configured sources.
- `GET /filesystem/sources/{source_id}/files` lists a directory (`directory`, `page`, `limit`).
- `GET /filesystem/sources/{source_id}/files/content` previews a file (`path`, optional Knowledge `revision`).
- `GET /filesystem/sources/{source_id}/files/search` searches literal text (`query`, `directory`, `page`, `limit`).

Use the source IDs returned by discovery, not namespace names. Existing agent-file
routes remain supported. Agent sources retain agent-read authorization and user
isolation; Knowledge sources require `knowledge:read` when authorization is enabled.
Knowledge page stores are shared corpora, not per-user namespaces. Register only
corpora that Knowledge readers should be allowed to browse. Attaching a
PageFileSystem to a top-level AgentOS agent also exposes its corpus to these
Knowledge readers. User isolation does not rewrite this shared corpus namespace.

Knowledge browsing uses published-page APIs, not raw storage reads. Previews carry
revisions and are capped at 24,000 characters; unavailable size and timestamp
metadata stays empty. Listing aggregates at most 10,000 pages within 20 seconds
and explicitly fails if the catalog changes or exceeds the bound. Search scans
are bounded, and the UI warns when `partial` is true. Counts then describe only
returned results, not the complete corpus. No browser write/delete routes exist.

This is a local, unauthenticated demo bound to `127.0.0.1`. The documentation corpus
is shared. Before deployment, configure AgentOS authentication and authorization,
and ensure callers allowed to run this agent may access the shared documentation.
