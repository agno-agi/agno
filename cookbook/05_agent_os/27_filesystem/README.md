# AgentOS File System

`postgres_filesystem.py` follows `custom_filesystem.py` with a `PostgresDb`
backend. It uses the local PostgreSQL database started by
`./cookbook/scripts/run_pgvector.sh` and requires `psycopg` in the cookbook
environment. Set `OPENAI_API_KEY` for agent runs.

```bash
.venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/postgres_filesystem.py
```

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

## Permissions and several stores

`filesystem` also accepts a toolkit, which carries its own permissions. A consumer
that must never change the records gets the three read tools only
(`read_only_consumer.py`):

```python
decisions = FileSystem(db, namespace="research/decisions")
recorder = Agent(id="recorder", db=db, filesystem=decisions)
answerer = Agent(id="answerer", db=db, filesystem=decisions.tools(read_only=True, add_instructions=True))
```

A toolkit passed this way is used as given: its `read_only`, `allow_delete`,
`include_tools` and `add_instructions` settings stand. `read_only`, `allow_delete`
and `add_instructions` are stored with the agent config; an `include_tools` or
`exclude_tools` selection is not.

The setting holds one store. An agent that needs several attaches them through
`tools`, splitting the tool names with `include_tools` so they do not collide
(`multiple_stores_per_agent.py`). The setting and a manually attached
`FileSystemTools` cannot be combined on one agent.

AgentOS discovers filesystems from both the setting and `tools`. `/config` lists
each namespace's linked `agents`, with `access: "read_only"` on read-only agents
and omitted `access` defaulting to `"full"`. To browse one of an
agent's several stores, pass its `namespace` to the `/filesystem` routes.

## Namespaces and isolation

The agent receives its filesystem tools automatically. The managed namespace is
always `{agent_id}`. Files are keyed by `(namespace, user_id, path)`: `user_id` is
the user partition, and `""` is the shared partition.

A run acts in the partition of its user, the same way memories are kept per user:
two users of one agent never see each other's files, and the namespace stays the
same. A run with no user identity acts in the shared partition. The browser
routes follow the same rule for the requesting user.

`AuthorizationConfig(user_isolation=True)` adds the API-level guarantees it adds
everywhere else: every request must carry a verified identity, and a request
without one is refused rather than served from the shared partition.

An explicit `FileSystem` can override the default with `user_scoped`:

```python
FileSystem(db, namespace="handbook", user_scoped=False)  # one store for every user
FileSystem(db, namespace="diary", user_scoped=True)      # refuses a run with no user
```

A namespace that names `{user_id}` isolates by name instead; its files stay in
the shared partition, so data written before partitions existed is still found.

Agent component versions with the same stable `agent.id` share this namespace;
versioning the component does not fork or snapshot its files. Bound user and agent
IDs preserve case, so `Alice` and `alice` stay distinct. Literal namespace text is
normalized to lowercase and percent-encoded.

In isolated mode the user id comes from trusted run/request context and missing
identity fails closed. AgentOS exposes read-only browser routes:

- `GET /filesystem/files` — list or search across every filesystem the caller can reach
- `GET /filesystem/entries` — files and directories directly under one directory
- `GET /filesystem/content` — a preview of one file
- `GET /filesystem/search` — content search within one filesystem

Filesystems are addressed by namespace, not by agent. `entries`, `content` and
`search` take `namespace`, `agent_id`, or both:

- `namespace` alone browses that filesystem when an agent the caller can read holds it.
- `agent_id` alone browses that agent's first filesystem (the setting, then `tools` order).
- Both together pick one of an agent's several filesystems, and settle the rare case
  of one namespace used on two backends, which otherwise returns 409.

Access always derives from the agents the caller may read: a namespace none of them
holds returns 404, the same as one that does not exist. Responses carry the resolved
`namespace` and the accessible `agent_ids` holding it.

`GET /filesystem/files` accepts optional `agent_id`, `namespace`, and `query` filters, plus
`page` and `limit`. The namespace filter matches an exact resolved namespace and
cannot widen access beyond the caller's agents and user scope. Shared files are
returned once with their accessible `agent_ids`. Remote agents are skipped in a
global listing; selecting one explicitly returns an unsupported response.

`GET /config` exposes `filesystem.namespaces` discovered from concrete local
agents. Each entry includes backend metadata, limits, linked agents with access
in `agents`, and the canonical namespace resolved for the caller. Use that namespace directly as a
`/filesystem` filter. When identity is unavailable, placeholders remain in config;
browsing requires the missing identity. Factory and stored agents are resolved
when browsing but are not included in config discovery.

With authorization enabled, file routes require `agents:read` or the corresponding
per-agent read scope; config requests require `config:read`. Content previews use the row's
`namespace` and relative `path`, with `offset` and `limit` for continuation.
The API provides no write or delete routes.

Listing reads each distinct filesystem once, with bounded concurrency. Page
counts are computed after collecting results; pagination does not yet limit
backend reads.

## Existing data

A filesystem table created by an earlier release is refused with
`SchemaOutdatedError` until it is upgraded: the change to the table's key is a
deliberate step. Run `libs/agno/migrations/migrate_filesystem.py` once, or call
`DbFileSystem(db=db).upgrade_schema()`. Existing rows keep their namespace and land
in the shared partition, so a custom `users/{user_id}/...` template still finds
its files.

Development builds before that used `agents/{agent_id}`; those files are not
moved. Configure the old namespace explicitly to keep reading them:

```python
fs = FileSystem(db, namespace="agents/{agent_id}")
agent = Agent(id="research-agent", db=db, filesystem=fs)
```
