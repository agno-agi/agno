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

The API does not accept a namespace or provide write/delete routes.
