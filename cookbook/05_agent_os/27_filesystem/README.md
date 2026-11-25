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

`filesystem` takes `True`, a `FileSystem`, or a list of them. What an agent may do
with a store is set on the `FileSystem`: `read_only`, `allow_delete`, `include_tools`
and `instructions`. A consumer that must never change the records gets the three
read tools only (`read_only_consumer.py`):

```python
decisions = FileSystem(db, namespace="research/decisions")
decisions_read_only = FileSystem(db, namespace="research/decisions", read_only=True)
recorder = Agent(id="recorder", db=db, filesystem=decisions)
answerer = Agent(id="answerer", db=db, filesystem=decisions_read_only)
```

Both objects point at the same files; the options only shape the agent's tools,
never the `FileSystem`'s own `read()` and `write()`. They are stored with the
agent config.

An agent with several stores lists them, `filesystem=[drafts, handbook]`, and each
store's tools get a distinct name (`multiple_stores_agent.py`). To attach the
toolkit yourself instead, use `tools=[fs.tools(...)]`; `tools()` defaults to the
FileSystem's own options. The setting and a manually attached toolkit cannot be
combined on one agent.

AgentOS discovers filesystems from both the setting and `tools`. `/config` lists
each namespace's linked `agents`, with `access: "read_only"` on read-only agents
and omitted `access` defaulting to `"full"`. To browse one of an
agent's several stores, pass its `id` from `/config` to the `/filesystem` routes
as `filesystem_id`.

## File systems declared on AgentOS

A file system can also be declared on the AgentOS itself (`os_level_filesystem.py`).
Pass one, or a list of any number:

```python
handbook = FileSystem(db, namespace="handbook")
drafts = FileSystem(db, namespace="drafts")
agent_os = AgentOS(db=db, agents=[...], filesystem=[handbook, drafts])
```

A declared file system is listed in `/config` and browsable through the
`/filesystem` routes even when no agent holds it. `/config` marks it with
`declared: true`, and shows `agents: []` when no agent holds it. With
authorization enabled, `filesystem:read` alone is enough to browse it. A request
for it loads no agent.

It is not handed to agents: an agent gets file tools on it only by holding the
same store with `filesystem=` or `tools=`, as `AgentOS(knowledge=[...])` does not
give agents a knowledge base. `Agent(filesystem=True)` keeps its own `{agent_id}`
namespace.

Any backend works: a database, or a local folder. Namespaces are not restricted.
Two declared file systems may use one namespace on two databases, or on two
tables of one database.

A namespace may use `{user_id}`, which is filled from the caller.

A namespace that uses `{agent_id}` is filled from the agent that holds the
store. It has no entry in `/config` until an agent holds it, and then it is
listed with that agent's id in place: `scratch/{agent_id}` held by the agent
`writer` is the file system `scratch/writer`.

A namespace that uses `{team_id}` is filled only when a team runs. Nothing on
these routes fills it. Declared alone it has no entry in `/config`. When an
agent holds it, `/config` lists the namespace as it is written, for example
`teams/{team_id}/notes`, and the `/filesystem` routes do not open it.

`AgentOS(user_isolation=True)` partitions a declared file system by user unless
the store sets `user_scoped` itself. The setting is applied to what the AgentOS
serves, not written onto the `FileSystem` you declared, so one `FileSystem`
declared on two AgentOS instances follows the setting of each.

## Namespaces and isolation

The agent receives its filesystem tools automatically. The managed namespace is
always `{agent_id}`. Files are keyed by `(namespace, user_id, path)`: `user_id` is
the user partition, and `""` is the shared partition.

With the default `user_isolation=False`, every user of the agent works in the
shared partition of that namespace. When `AgentOS(user_isolation=True)` is set
(the legacy `AuthorizationConfig(user_isolation=True)` still works), AgentOS marks
every agent filesystem user-scoped: each run acts in the
partition of its verified user, a run with no user is refused, and two users of one
agent never see each other's files. The namespace stays the same either way.

An explicit `FileSystem` can decide for itself with `user_scoped`, which AgentOS
leaves alone:

```python
FileSystem(db, namespace="handbook", user_scoped=False)  # one store for every user, even under isolation
FileSystem(db, namespace="diary", user_scoped=True)      # per user even without it; refuses a run with no user
```

The browser routes follow the same rule for the requesting user. An admin (the
`agent_os:admin` scope) sees every partition of a user-scoped store, with each
file's `user_id`, and may pass `user_id` to browse or open one user's files; other
callers may name only their own.

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

A filesystem is addressed by its id. `GET /config` lists every filesystem the
caller can reach in `filesystem.namespaces`, each with an `id`. Pass it to
`entries`, `content` and `search` as `filesystem_id`:

```bash
curl "http://localhost:7777/filesystem/entries?filesystem_id=handbook"
```

The id is the namespace resolved for the caller. When two filesystems share a
namespace, each id also names its backend: `handbook:main-db`, and
`handbook:main-db:fs.agno_fs` when the two are tables of one database. A declared
filesystem keeps its id whatever agents hold.

`namespace` and `agent_id` are still accepted:

- `namespace` alone browses that filesystem when the AgentOS declares it or an agent
  the caller can read holds it. One namespace on two backends returns 409: pass
  `filesystem_id`.
- `agent_id` alone browses that agent's first filesystem (the setting, then `tools` order).
- Both together pick one of an agent's several filesystems.

A filesystem has one id, with or without `agent_id`. `filesystem_id` with
`agent_id` opens a filesystem only when that agent holds the one the id names;
otherwise the request returns 404. A request that names an agent reads the
store with that agent's limits.

A filesystem only an agent holds is reachable through the agents the caller may
read: one none of them holds returns 404, the same as one that does not exist.
Responses carry the `filesystem_id`, the resolved `namespace` and the accessible
`agent_ids` holding it. A declared filesystem read by `filesystem_id` loads no
agent, so its `agent_ids` is empty; `/config` names the agents that hold it.

`GET /filesystem/files` accepts optional `filesystem_id`, `agent_id`, `namespace`, and
`query` filters, plus `page` and `limit`. A filter cannot widen access beyond the
caller's filesystems and user scope. Every row carries its `filesystem_id`. Shared
files are returned once with their accessible `agent_ids`. Remote agents are skipped
in a global listing; selecting one explicitly returns an unsupported response.

`GET /config` exposes `filesystem.namespaces` discovered from the AgentOS
`filesystem` setting and from concrete local agents. Each entry includes its `id`,
whether it is `declared`, backend metadata, limits, linked agents with access in
`agents`, and the canonical namespace resolved for the caller. When identity is
unavailable, placeholders remain in config; browsing requires the missing identity.
Factory and stored agents are resolved when browsing but are not included in config
discovery.

With authorization enabled, file routes require `filesystem:read`. A declared
filesystem needs nothing more. A filesystem only an agent holds also needs
`agents:read` or the corresponding per-agent read scope. Config requests require
`config:read`. Content previews use the row's `filesystem_id` and relative `path`,
with `offset` and `limit` for continuation. The API provides no write or delete routes.

Listing reads each distinct filesystem once, with bounded concurrency. Page
counts are computed after collecting results; pagination does not yet limit
backend reads.

## Existing data

A filesystem table created by an earlier release is refused with
`SchemaOutdatedError` until it is upgraded: the change to the table's key is a
deliberate step. Run `libs/agno/migrations/migrate_filesystem_postgres.py` or
`migrate_filesystem_sqlite.py` once, or call
`DbFileSystem(db=db).upgrade_schema()`. Existing rows keep their namespace and land
in the shared partition, so a custom `users/{user_id}/...` template still finds
its files.

Development builds before that used `agents/{agent_id}`; those files are not
moved. Configure the old namespace explicitly to keep reading them:

```python
fs = FileSystem(db, namespace="agents/{agent_id}")
agent = Agent(id="research-agent", db=db, filesystem=fs)
```
