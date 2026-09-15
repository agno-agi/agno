# AgentOS File System

## Docker and sandbox filesystems

These examples use the same `Agent(filesystem=...)` interface and File System
browser, with different storage locations:

| Example | Where AgentOS runs | Where agent files live | Lifetime |
| --- | --- | --- | --- |
| [`docker_filesystem.py`](docker_filesystem.py) | Docker container | Named volume through `LocalFileSystem` | Survive container replacement |
| [`e2b_filesystem.py`](e2b_filesystem.py) | Your machine | E2B sandbox through a cookbook `BaseFS` adapter | Until sandbox shutdown or timeout |

Both are local, single-user demos. SQLite stores session records; it does not
store their filesystem contents. Their explicit namespaces are shared by all
callers of the demo agent. Neither example gives the model shell or container
management tools.

### Docker with a persistent volume

Start Docker, set `OPENAI_API_KEY` in your shell, then run from the repository root:

```bash
docker compose -f cookbook/05_agent_os/27_filesystem/docker-compose.yaml up --build
```

The image installs Agno from this checkout. A Dockerfile-specific ignore file
limits the build context to the package and example; credentials are passed at
runtime. Connect Agno OS to `http://localhost:7777` and choose **Docker File System
Agent**. Ask: "Save our decision to prioritize onboarding in notes/decisions.md."

The storage flow is:

```text
Agent -> FileSystem(namespace="docker-workspace")
      -> LocalFileSystem(root="/data/files") -> Docker named volume
```

The file lives at `/data/files/docker-workspace/notes/decisions.md` inside the
container. This is container deployment of `LocalFileSystem`, not a remote Docker
API backend. The container runs as a non-root user with a read-only root
filesystem, a writable `/tmp`, and a persistent `/data` volume. It has no host
project or Docker socket mounted.

To stop the demo while keeping its files:

```bash
docker compose -f cookbook/05_agent_os/27_filesystem/docker-compose.yaml down
```

Start it again with the first command and ask the agent to read the saved
decision. Docker retains the named volume across `down`/`up`; adding `--volumes`
to `down` deletes the demo's files and sessions.

Reference: [Docker volumes](https://docs.docker.com/engine/storage/volumes/).

### E2B sandbox storage

Install dependencies into the demo environment from the repository root:

```bash
uv pip install --python .venvs/demo/bin/python -e 'libs/agno[os]' openai 'e2b>=2.5,<3'
```

Set `OPENAI_API_KEY` and `E2B_API_KEY` in your shell, then run:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/e2b_filesystem.py
```

Running this example creates a cloud sandbox and uses your E2B account. Connect
Agno OS to `http://localhost:7778`, select **E2B File System Agent**, and ask:
"Read notes/project.md and save a three-step launch plan in reports/launch.md."
Browse the result in File System while the sandbox is running.

```text
Local agent -> FileSystem(namespace="sandbox-workspace")
            -> E2BFileSystem -> E2B files API
            -> /home/user/agno-files/sandbox-workspace/reports/launch.md
```

[`e2b_backend.py`](e2b_backend.py) implements the four required `BaseFS` methods:
read, write, list, and delete. `BaseFS` supplies search, usage, append, move, and
async wrappers. This adapter is an example, not a built-in Agno integration;
`/config` reports its backend type as `E2BFileSystem`. Keep it code-defined:
custom-backend serialization for Studio is not supported.

The sandbox is created once, has a 30-minute timeout, and is killed on normal
server shutdown. Restarting creates a fresh sandbox and seeds `notes/project.md`
again. Session records remain in `tmp/e2b-filesystem-sessions.db`, but sandbox
files do not. Export wanted files before stopping. If the sandbox expires while
the server is running, restart the example to create a new one.

Use this adapter for small text workspaces: search reads files over the network,
file versions are unsupported, and append/move and quota checks are not atomic
across concurrent operations. The example uses a dedicated sandbox with no
shell tools; the namespace layout does not isolate files from arbitrary code
executing inside that same sandbox.

Reference: [E2B Python SDK](https://docs.e2b.dev/sdk-reference/python-sdk/v2.5.0/sandbox_sync).

## Workspace quickstart

[`workspace_quickstart.py`](workspace_quickstart.py) runs two agents sharing one
durable filesystem, inspired by the [AgentFS Python SDK README](https://github.com/tursodatabase/agentfs/blob/main/sdk/python/README.md).
The Notes Agent saves project configuration, feedback, and decisions. The Report
Agent reads those files and writes reports.

```bash
.venvs/demo/bin/python cookbook/05_agent_os/27_filesystem/workspace_quickstart.py
```

Set `OPENAI_API_KEY` for agent runs and connect Agno OS to `http://localhost:7777`.
Ask the Notes Agent: "Our project is Docs Assistant. Users need a simpler setup
example and source citations. Save this feedback and prioritize onboarding."
Then ask the Report Agent: "Read our project notes and save the next three
priorities to reports/next-steps.md."

Browse the shared files in File System. They persist in `tmp/workspace.db` under
the `project-workspace` namespace.

## AgentOS setup

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
