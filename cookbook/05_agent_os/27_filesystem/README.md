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
each instance's `agents` and the subset in `read_only_agents`. To browse one of an
agent's several stores, pass its `namespace` to the `/filesystem` routes.

## Namespaces and isolation

The agent receives its filesystem tools automatically. With the default
`user_isolation=False`, the namespace is shared by users of that agent:

```text
{agent_id}
```

When `AuthorizationConfig(user_isolation=True)` is enabled, it becomes:

```text
users/{user_id}/{agent_id}
```

Agent component versions with the same stable `agent.id` share this namespace;
versioning the component does not fork or snapshot its files. Bound user and agent
IDs preserve case through percent encoding, so `Alice` and `alice` stay distinct.
Literal namespace text is normalized to lowercase and percent-encoded.

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

`GET /config` exposes `filesystem.instances` discovered from concrete local
agents. Each instance includes backend metadata, limits, agent IDs in `agents`, and the
canonical namespace resolved for the caller. Use that namespace directly as a
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

## Existing development data

Earlier versions of this feature used `agents/{agent_id}` and
`users/{user_id}/agents/{agent_id}` for managed files. The shorter defaults do not
move existing data. To keep reading those files, configure the old namespace
explicitly:

```python
fs = FileSystem(db, namespace="agents/{agent_id}")
agent = Agent(id="research-agent", db=db, filesystem=fs)
```

For isolated files, use `namespace="users/{user_id}/agents/{agent_id}"` instead.
Existing files written with the earlier case-folding bug need a deliberate
migration if IDs contained uppercase characters; case-collided data cannot be
assigned to distinct identities automatically.
