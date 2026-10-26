# OS Manager

OS Manager is a team you talk to through AgentOS. It can check activity, run
diagnostics, run existing components and ask its members to build new ones.
Start with a model and a database:

```python
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager

agent_os = AgentOS(
    db=SqliteDb(db_file="tmp/manager.db"),
    manager=OSManager(model=OpenAIResponses(id="gpt-5.6-luna")),
)
```

## Try the examples

From the repository root, set up the environment:

```bash
./scripts/demo_setup.sh
```

Start with diagnostics. This makes no model calls and does not need an API key:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_diagnostics.py
```

Expect a JSON report. A missing `OPENAI_API_KEY` produces FAIL because the example
lists it as required. Disabled authorization produces WARN. These results show
what needs configuring; running the script itself does not require either.

For a conversation, set your API key and start one of the serving examples:

```bash
export OPENAI_API_KEY=...
.venvs/demo/bin/python cookbook/05_agent_os/29_manager/basic_manager.py
```

Connect the AgentOS UI to `http://localhost:7777` and select the **OS Manager**
team. Stop the server before starting another example on the same port.
Conversations use the configured model and incur provider charges.

| File | Ask OS Manager | What to expect |
|---|---|---|
| `basic_manager.py` | “Run diagnostics and explain any issues.” | A report from Platform Manager, including the authorization warning. The manager model is available for basic builds; no additional tools are declared. |
| `manager_user_access.py` | As Alice, ask “Run math-helper: what is 6 * 7?” Then ask to publish a new agent. | The permitted run succeeds; publishing is refused. Configure `JWT_VERIFICATION_KEY` and a JWT with `sub=alice`, `aud=manager-access-demo`. |
| `manager_builds_agents.py` | “Create a calculator agent named Budget Helper.” Then: “Run Budget Helper: what is 15% of 240?” | Platform Builder publishes the agent. The second request runs it and should return 36. |
| `manager_source.py` | “Read basic_manager.py, then check the Agno docs for how to add knowledge.” | Platform Manager reads the configured root and consults the docs MCP server; no notebook or memory setup is needed. |
| `manager_source.py` | “How does learning work?” | OS Manager can search docs directly and answer the concept question without a deployment audit. |
| `manager_source.py` | “What is Agno?” or “Can you tell me about learning machines?” | A brief explanation grounded in the Agno documentation, with links. An explicitly general machine-learning question retains its broader meaning. |
| `check_manager_permissions.py` | Run it directly; no chat or model key needed. | Seven HTTP checks confirm discovery, session access, rejected audiences, and denied publication. |
| `manager_with_resources.py` | “Save a note in project.md: the demo is on Friday.” Then: “Read project.md.” | The shared notebook stores and retrieves the note. |
| `manager_with_resources.py` | “Remember that I prefer short answers.” Then ask about your preference in a new session with the same user id. | The manager can save and retrieve a user preference across sessions. |
| `manager_with_resources.py` | “Read basic_manager.py and explain how the manager is configured.” | Platform Manager reads the example from its configured root. |

To try the build example:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_builds_agents.py
```

To try the notebook, memory and source tools:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_with_resources.py
```

Each serving example uses its own SQLite file under `tmp/`, so conversations,
notes and published components persist between runs. Use PostgreSQL in production.

## Check regular-user access without a model call

Set `JWT_VERIFICATION_KEY` to a local development signing key of at least 32
characters, then run:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/29_manager/check_manager_permissions.py
```

Expect seven `PASS` lines. This checks the same app as `manager_user_access.py`
without starting a server or calling a model. The example explicitly enables
`verify_audience=True`; setting `audience` alone does not enable audience checks.
Alice's managed role allows manager/math-helper discovery and runs, diagnostics,
and reading her own sessions. It does not grant publishing, scheduling, source
reads, or platform-wide operational reports. Even a signed JWT claiming admin
cannot override that role. Production tokens should come from your identity provider.

## Run Claude and Codex engineers

Register external agents in `AgentOS(agents=[...])` to let OS Manager discover
and run them by name or ID. For example:

```python
from pathlib import Path

from agno.agents.claude import ClaudeAgent
from agno.agents.codex import CodexAgent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIResponses
from agno.os import AgentOS, OSManager

db = SqliteDb(db_file="tmp/engineers.db")
claude = ClaudeAgent(id="claude-engineer", name="Claude Engineer", cwd=str(Path.cwd()), db=db)
codex = CodexAgent(id="codex-engineer", name="Codex Engineer", cwd=str(Path.cwd()), db=db)
agent_os = AgentOS(
    db=db,
    agents=[claude, codex],
    manager=OSManager(model=OpenAIResponses(id="gpt-5.6-luna")),
)
agent_os.manager.print_response("List the available agents.")
agent_os.manager.print_response("Ask Codex Engineer to explain this repository without changing files.")
```

Install and authenticate the corresponding harness SDKs before running an
engineer. These calls spend model usage and execute in the configured workspace.
The manager's sync and async run tools preserve the caller's identity and keep a
separate continuing session for each engineer and user. Existing run permissions
still apply. External agents are dispatch targets, not Studio edit targets or
persisted team/workflow members.

## Manager settings

| Setting | Default | Effect |
|---|---|---|
| `model` | First registry model | Shared by the manager and both members; also available for builds. |
| `name` | `OS Manager` | Display name only; the ID and member composition are fixed. |
| `root` | `None` | Platform Manager's read-only source directory or constrained workspace provider. |
| `access_docs` | `True` | Gives OS Manager and Platform Manager access to Agno docs through one shared connection. Connection failures are nonfatal; set `False` for offline deployments. |
| `tools`, `knowledge`, `learning` | Empty / `None` | Extra resources for the lead team; not automatically available for builds. |
| `instructions` | `None` | Appends instructions to the lead team's existing prompt. |
| `required_env` | Empty | Names whose presence diagnostics checks; values are never returned. |
| `tool_call_limit` | `8` | Ordinary tool executions per coordinator run, including delegations. `None` disables the limit; `0` refuses all ordinary tools. |
| `member_tool_call_limit` | `24` | Ordinary tool executions per specialist invocation, including the Company Manager member when Company is enabled. `None` disables the limit. |
| `num_history_runs` | `7` | Lead-team history depth. Members retain five runs. |
| `offload_tool_results` | `True` | Stores large tool results on supported databases; accepts `False` or a `ResultStore`. |

`root` is resolved relative to the process working directory. Use a path based on
`__file__`, as in `manager_source.py`, for the same root regardless of where you
launch the server. Setting `root` does not enable file writes or shell execution.

The manager is instructed to keep explanations scoped to the question and to
request concise specialist answers when delegation is necessary. Documentation
access on the lead lets it answer framework questions without a specialist run.
Short grounding and stopping rules also reach the builder, operator and attached
Company Manager member. Guidance for explaining framework concepts from the docs goes only
to the lead and Platform Manager, the roles with documentation access. Source
investigation guidance stays with Platform Manager.

The limits use the existing Agent/Team tool execution mechanism. Each member
invocation has its own allowance; there is no shared budget across the run tree.
The `read_result` and `search_result` tools remain exempt when result offloading
is active. A refusal is returned to the model, which is instructed to stop and
report verified progress and gaps. These limits do not bound model turns, tokens,
latency, or application components dispatched through runner tools.

Increase the limits for larger builds or plans. Set either limit to `None` to
restore unlimited ordinary tool executions for that level. Ordinary application
agents and the served Company Manager, which runs direct chat and Routines, retain their existing limits. Custom
`instructions` remain specific to the lead team. Model choices still determine
actual routing and answer quality; prompt guidance is not an execution guarantee.

## When to use a registry

You do not need to configure a registry just to add a manager. Pass its model
through `OSManager`, as in the basic example. That model is added to the registry,
without replacing an equivalent explicitly registered model. With no other
resources declared, the builder can create basic model-backed agents. It explains
which tools or knowledge sources are missing when a richer build needs them.

Use a `Registry` when you want to choose resources for components the builder
creates: models, tools, workflow functions, knowledge or learning. The build
example supplies a model, calculator tools and JSON/CSV functions. It uses
`manager=True` so the manager uses the first model in that registry too.

Tools passed to `OSManager(tools=[...])` are for the manager itself. They do
not become tools for new agents. To share a resource with the builder, include
it in the registry as well. Code-defined application components also contribute
resources through AgentOS registry discovery. Manager components are excluded.

## The team and its members

The default team name is **OS Manager**, with id `os-manager-internal`. Set
`OSManager(name=...)` to change the display name. The ID and two-member
composition are fixed. Its members are:

- **Platform Builder** (`platform-builder-internal`): creates components and schedules.
- **Platform Manager** (`platform-manager-internal`): checks activity, runs diagnostics,
  reads source when `root` is set, and queries Agno documentation by default.

Only OS Manager is exposed as a standalone target in config, discovery, REST and MCP.
Platform Builder and Platform Manager appear as nested members in `/teams` and
`/teams/os-manager-internal`, so the team graph shows its composition. Built-in members,
including Product Manager, list their model and tools but not their instructions. They remain
excluded from the application registry, `/config` agent list and `/agents`, and
their standalone agent routes return 422 with an explanation that the component
ID is reserved. OS Manager delegates to them; their child runs and tool results remain
available inside its session for replay and diagnostics. Schedule the manager
team, not either specialist. Ordinary run grants, including `teams:os-manager-internal:run`, let a user talk to the manager. Access
to the manager does not grant its tools additional permissions:

- Running another component requires its agent, team or workflow `run` permission.
- Discovery filters components by their `read` permission. Registry discovery
  requires `registry:read`; catalog inspection requires `components:read`.
- Creating, editing and publishing components requires `components:write`.
  Archiving, restoring and deleting versions requires `components:delete`.
- Schedule tools require the corresponding `schedules:read`, `schedules:write`
  or `schedules:delete` permission. Creating or editing a schedule also checks
  permission to run its target.
- Diagnostics requires `config:read`; workspace reads require `filesystem:read`.
- Platform-wide operational aggregates remain administrator-only because these
  queries do not provide a per-user view.

Operation checks apply during manager execution and to work it delegates.
Existing agents using StudioTools or other platform toolkits retain their existing
run-permission behavior when called directly, whether the manager is omitted,
disabled, or enabled alongside them. Calling that same agent through OS Manager
keeps the manager caller's operation checks active. Shared toolkits are not mutated.

These decisions use the configured authorization provider, including managed
roles and custom policies. JWT claims cannot override those policies. Service
accounts retain their own token ACL. Authority follows specialist delegation,
MCP calls and queued execution; a continuation uses its current caller's authority.
Permission-sensitive tools recheck access rather than serving cached results.

Schedules created or edited under authorization retain the caller's permission
snapshot. The executor uses that snapshot for the target and its tools, rather
than its internal transport credential. Managed policies are consulted when the
schedule runs. Token-scope grants are captured when the schedule is saved; edit
or delete the schedule to change them. Existing schedules without a snapshot
retain ordinary agents' existing behavior. A manager target cannot use protected
tools without a caller snapshot; recreate or edit that schedule as an authorized
caller. Work scheduled from inside a manager tool retains operation checks when
it executes later, even if its target is an ordinary agent.

Direct Python calls, security-key access, unauthenticated deployments and interfaces
bound directly to the team are trusted application entry points. Expose those only
to trusted operators; binding Slack does not enforce REST user roles. Custom tools
supplied through `OSManager.tools` remain application-defined capabilities:
use `RunContext.authorization` or `requires_permission` from
`agno.run.authorization` when they need caller authorization.

All three IDs are reserved, even when the manager is disabled. Application
components and Studio builds cannot use them. The manager can run itself once with a fresh context; it cannot start
another self-run from that run.

`OSManager(root="./")` gives Platform Manager read-only file tools with default exclusions
for credential files. A supplied `WorkspaceContextProvider` is copied into tools
mode. Its model, prompt and custom tools are not used. Additional exclusions are
supported; `allow_paths` and custom `!` exemptions are rejected.

Platform Manager has Agno documentation access by default through
`https://docs.agno.com/mcp`. No extra configuration is needed. If the docs server
is unavailable, the connection failure is logged and AgentOS starts normally;
Platform Manager can still use its other tools. A later async run retries the connection.
If the optional MCP dependency is missing, a warning explains how to install it.

Use `OSManager(model=model, access_docs=False)` to disable docs access in offline
or restricted-network deployments. The docs tools remain private to Platform
Manager and are not added to the build palette.

The public team response exposes its built-in identity through existing metadata:

```json
{"metadata": {"_agno": {"internal": true, "id": "os-manager-internal"}}}
```

Internal member runs carry their own reserved ID in the same place. This is a UI marker,
not an authorization grant. Ordinary application metadata is unchanged.

Clients that previously called a specialist directly should use
`POST /teams/os-manager-internal/runs` or MCP `run_team` with that team ID.
Existing direct-specialist schedules can be disabled or deleted. Unmanaged
schedules can be repointed to OS Manager. Studio-managed schedules have immutable
targets: create a replacement targeting OS Manager, then delete the old schedule.
Changing only their endpoint causes execution to fail and disables the schedule.
Creating or re-enabling a direct-specialist schedule returns HTTP 409. Old catalog rows do not
restore specialist endpoints. Obsolete specialist manifest entries are omitted.
Stored rows remain available for deliberate administrative cleanup.
Ordinary application agents and teams keep their existing routes.

This unreleased API replaces `ManagerConfig` with `OSManager`, `workspace` with
`root`, `docs` with `access_docs` (now enabled by default), and the earlier manager
IDs with the fixed IDs above. Update client IDs and permission grants accordingly. Existing sessions under earlier IDs are not
migrated automatically. Run access, component discovery (`teams:read` or
`agents:read`), and session access (`sessions:read` plus ownership restrictions)
remain separate permissions.

The resources example shares notebook files across users, while learning keeps
user memory separate. It does not configure a knowledge base.

## Large tool results

OS Manager and its members offload tool results by default on SQLite and
PostgreSQL. Results above 16,000 characters are stored in the database; the
model receives a preview and can read or search the full result. Small results
stay inline. Other database adapters warn and leave offloading disabled.

Use `OSManager(offload_tool_results=False)` to disable it, or pass a
`ResultStore` to customize the threshold and retention:

```python
from agno.offload import ResultStore

manager_config = OSManager(
    model=OpenAIResponses(id="gpt-5.6-luna"),
    offload_tool_results=ResultStore(threshold_chars=32000, ttl_seconds=86400),
)
```

Pass this config as `AgentOS(db=db, manager=manager_config)`. The custom example
expires stored results after one day; the default has no time-based expiry.

## Direct use

`agent_os.manager` is a regular Team, or `None` when disabled. Use its sync or
async methods with a user id and session id:

```python
result = agent_os.manager.run("Run diagnostics", user_id="alice", session_id="review")
```

In async code:

```python
result = await agent_os.manager.arun("Run diagnostics", user_id="alice", session_id="review")
```

The manager needs a synchronous database because Studio uses it to save
components. Both sync and async Team runs are supported. Creating the OS raises
an error if the model is missing or the database type is unsupported.

To attach an interface or expose `agent_os.manager.as_tool()` through MCP, create
the OS first, configure the interface or MCP tools, then call `get_app()`.

## Diagnostics

`agent_os.run_diagnostics()` and `await agent_os.arun_diagnostics()` make no model
calls. SQL diagnostics probe the connection before reading sessions, including
when the database has no tables yet. Scheduler checks scan up to 10,000 enabled
schedules and report WARN if the scan is incomplete or an overdue schedule is found.

To probe MCP, pass `network_probe=True, public_url="https://your-os.example"`.
Use the OS base URL, including any proxy path prefix; the probe appends the
configured MCP path or uses `/` on the configured MCP root host.

### Editing scheduled runs

Changing a schedule's timing or description through the REST API preserves its
saved execution identity. Changing its endpoint, method or payload requires the
editor to have permission to run the target and saves that editor's authority.
To refresh captured token-scope grants, update the payload as an authorized caller.
