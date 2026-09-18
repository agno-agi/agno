# AgentOS File System

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

- `GET /files` — list or search across accessible agent filesystems
- `GET /agents/{agent_id}/files`
- `GET /agents/{agent_id}/files/content`
- `GET /agents/{agent_id}/files/search`

`GET /files` accepts optional `agent_id`, `namespace`, and `query` filters, plus
`page` and `limit`. The namespace filter matches an exact resolved namespace and
cannot widen access beyond the caller's agents and user scope. Shared files are
returned once with their accessible `agent_ids`. Remote agents are skipped in a
global listing; selecting one explicitly returns an unsupported response.

`GET /config` exposes `filesystem.instances` discovered from concrete local
agents. Each instance includes backend metadata, limits, agent IDs in `agents`, and the
canonical namespace resolved for the caller. Use that namespace directly as a
`/files` filter. When identity is unavailable, placeholders remain in config;
browsing requires the missing identity. Factory and stored agents are resolved
when browsing but are not included in config discovery.

With authorization enabled, file routes require `agents:read` or the corresponding
per-agent read scope; config requests require `config:read`. Content previews use an `agent_id` from
the row and its relative `path`, with `offset` and `limit` for continuation.
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
