# Super Agent

Super Agent is a team you talk to through AgentOS. It does the work itself with
direct tools: it checks activity, runs diagnostics, runs existing components and,
with Company, keeps company work on record. Its one member, Platform Builder,
builds new components. Start with a model and a database:

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

To inspect the roster without a model call or API key:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_discovery.py
```

Super Agent's `list_agents`, `list_teams`, and `list_workflows` tools use each
component's description, falling back to `config.manifest[id].description` when
it is missing or empty. This also works with a YAML config file. Manifest text
stays discovery metadata and does not change the component's system prompt.
The example checks both sync and async listings.

For a conversation, set your API key and start one of the serving examples:

```bash
export OPENAI_API_KEY=...
.venvs/demo/bin/python cookbook/05_agent_os/29_manager/basic_manager.py
```

Connect the AgentOS UI to `http://localhost:7777` and select the **Super Agent**
team. Stop the server before starting another example on the same port.
Conversations use the configured model and incur provider charges.

| File | Ask Super Agent | What to expect |
|---|---|---|
| `basic_manager.py` | “Run diagnostics and explain any issues.” | A diagnostics report from Super Agent, including the authorization warning. The manager model is available for basic builds; no additional tools are declared. |
| `manager_user_access.py` | As Alice, ask “Run math-helper: what is 6 * 7?” Then ask to publish a new agent. | The permitted run succeeds; publishing is refused. Configure `JWT_VERIFICATION_KEY` and a JWT with `sub=alice`, `aud=manager-access-demo`. |
| `manager_builds_agents.py` | “Create a calculator agent named Budget Helper.” Then: “Run Budget Helper: what is 15% of 240?” | Platform Builder publishes the agent. The second request runs it and should return 36. |
| `manager_source.py` | “Read basic_manager.py, then check the Agno docs for how to add knowledge.” | Super Agent reads the configured root and consults the docs MCP server; no notebook or memory setup is needed. |
| `manager_source.py` | “How does learning work?” | Super Agent can search docs directly and answer the concept question without a deployment audit. |
| `manager_source.py` | “What is Agno?” or “Can you tell me about learning machines?” | A brief explanation grounded in the Agno documentation, with links. An explicitly general machine-learning question retains its broader meaning. |
| `check_manager_permissions.py` | Run it directly; no chat or model key needed. | Seven HTTP checks confirm discovery, session access, rejected audiences, and denied publication. |
| `manager_with_resources.py` | “Save a note in project.md: the demo is on Friday.” Then: “Read project.md.” | The shared notebook stores and retrieves the note. |
| `manager_with_resources.py` | “Remember that I prefer short answers.” Then ask about your preference in a new session with the same user id. | The manager can save and retrieve a user preference across sessions. |

To try the build example:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/29_manager/manager_builds_agents.py
```

To try the notebook and memory tools:

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

Register external agents in `AgentOS(agents=[...])` to let Super Agent discover
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
| `model` | First registry model | Shared by Super Agent and Platform Builder; also available for builds. |
| `name` | `Super Agent` | Display name only; the ID and member are fixed. |
| `root` | `None` | Directory or `WorkspaceContextProvider` that Super Agent reads with `list_files`, `read_file` and `search_content`. |
| `access_docs` | `True` | Gives Super Agent the Agno docs tools. Connection failures are nonfatal; set `False` for offline deployments. |
| `tools`, `knowledge`, `learning` | Empty / `None` | Extra resources for Super Agent; not automatically available for builds. |
| `instructions` | `None` | Appends instructions to Super Agent's prompt. |
| `required_env` | Empty | Names whose presence diagnostics checks; values are never returned. |
| `tool_call_limit` | `24` | Ordinary tool executions per Super Agent run, including delegations. `None` disables the limit; `0` refuses all ordinary tools. |
| `member_tool_call_limit` | `24` | Ordinary tool executions per Platform Builder invocation. `None` disables the limit. |
| `num_history_runs` | `5` | Super Agent history depth. Platform Builder keeps five runs. |
| `offload_tool_results` | `True` | Stores large tool results on supported databases; accepts `False` or a `ResultStore`. |

`root` is resolved relative to the process working directory. Use a path based on
`__file__`, as in `manager_source.py`, for the same root regardless of where you
launch the server. Setting `root` does not enable file writes or shell execution.

Super Agent is instructed to do the work itself, stay within the question and
stop once the evidence supports the answer. Docs guidance is added when
`access_docs` is on, and source guidance when `root` is set. Platform Builder gets
short grounding and stopping rules.

The limits use the existing Agent/Team tool execution mechanism. Each Platform
Builder invocation has its own allowance; there is no shared budget across the run tree.
The `read_result` and `search_result` tools remain exempt when result offloading
is active. A refusal is returned to the model, which is instructed to stop and
report verified progress and gaps. These limits do not bound model turns, tokens,
latency, or application components dispatched through runner tools.

Increase the limits for larger builds or plans. Set either limit to `None` to
restore unlimited ordinary tool executions for that level. Ordinary application
agents and the Company Routine runner are not affected. Model choices still
determine routing and answer quality; prompt guidance is not a guarantee.

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
For the other `AgentOSTools` reports, such as `get_platform_metrics` or
`list_pending_approvals`, pass `OSManager(tools=[AgentOSTools(db=db)])`.

## The team and its members

The default team name is **Super Agent**, with id `superagent`. Set
`OSManager(name=...)` to change the display name. The ID and member are fixed.
Super Agent holds these tools:

- Run tools: `list_agents`, `run_agent`, `list_teams`, `run_team`, `list_workflows`, `run_workflow`.
- Platform tools: `get_run_activity`, `list_schedules`, `run_diagnostics`.
- Docs tools when `access_docs` is on, and `list_files`, `read_file`, `search_content` when `root` is set.
- Company tools when `company=CompanyConfig(...)` is set: company details, Products,
  Projects, Tasks, Sources, playbook, Routines and decisions. See `30_company`.
- Anything passed in `OSManager(tools=...)`.

Its context lists up to 20 components the caller may read and run. Its one
member, **Platform Builder** (`platform-builder`), creates and edits components
and schedules.

Only Super Agent is exposed as a standalone target in config, discovery, REST and MCP.
Platform Builder appears as a nested member in `/teams` and `/teams/superagent`.
It lists its model and tools but not its instructions, stays out of the registry,
`/config` and `/agents`, and its standalone agent route returns 422. Its child runs
and tool results stay inside Super Agent's session. Schedule Super Agent, not
Platform Builder. Ordinary run grants, including `teams:superagent:run`, let a user
talk to Super Agent. Access to Super Agent does not grant its tools additional permissions:

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
disabled, or enabled alongside them. Calling that same agent through Super Agent
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

Super Agent can run itself once with a fresh context, but not again from that run.

`OSManager(root="./")` gives Super Agent read-only file tools with default exclusions
for credential files. A supplied `WorkspaceContextProvider` is copied into tools
mode. Its model, prompt and custom tools are not used. Additional exclusions are
supported; `allow_paths` and custom `!` exemptions are rejected.

Super Agent has Agno documentation access by default through
`https://docs.agno.com/mcp`. If the docs server is unavailable, the failure is
logged, AgentOS starts normally and Super Agent keeps its other tools. A later
async run retries the connection. If the optional MCP dependency is missing, a
warning explains how to install it.

Use `OSManager(model=model, access_docs=False)` to disable docs access in offline
or restricted-network deployments. The docs tools are not added to the build palette.

The public team response exposes its built-in identity through existing metadata:

```json
{"metadata": {"_agno": {"internal": true, "id": "superagent"}}}
```

Internal member runs carry their own reserved ID in the same place. This is a UI marker,
not an authorization grant. Ordinary application metadata is unchanged.

Call Super Agent with `POST /teams/superagent/runs` or MCP `run_team`, not a
specialist. Creating or re-enabling a specialist schedule returns HTTP 409. Disable
or delete existing ones; Studio-managed schedules have immutable targets, so create
a replacement targeting Super Agent first. Run access, component discovery
(`teams:read` or `agents:read`) and session access (`sessions:read` plus ownership
restrictions) remain separate permissions.

The resources example shares notebook files across users, while learning keeps
user memory separate. It does not configure a knowledge base or `root`: tools in
`OSManager(tools=...)` that share a name with the source file tools take precedence.

## Large tool results

Super Agent and Platform Builder offload tool results by default on SQLite and
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


## Reserved IDs

The public manager IDs are `superagent` (Super Agent) and `platform-builder`
(Platform Builder). `superagent-routines` is the internal Company Routine runner.
`product-manager-internal` and the pre-3.2 IDs `os-manager-internal`,
`company-manager-internal`, `platform-builder-internal` and
`platform-manager-internal` stay reserved and do not resolve; requests that use
them get an error naming `superagent` or `platform-builder`. These IDs are
reserved even when managers are disabled. Other IDs, such as `super-agent`,
`platform-manager` and `company-manager`, are ordinary user IDs. Startup refuses
to replace a custom catalog component that uses a manager ID; rename it first.

When upgrading:

- **Managed-role policies:** startup refuses any stored policy that names a former ID,
  because a stored deny that stopped matching could let a denied user through. Update those
  policies to the new IDs, including roles declared in code.
- **Token scopes, FGA tuples and API clients:** update them to the new IDs. Old grants no
  longer match, so access is refused until you do.
- **Schedules and Routines:** stored endpoints that use a former ID stop resolving, so
  recreate or edit them.
- **History:** sessions, runs, traces and memories keep the ID they were saved with, so
  they don't appear under the new ID.

## Breaking changes in 3.2

- `platform-manager` and `company-manager` do not exist. Super Agent does their work
  with its own tools; nothing is served at `/agents/company-manager`.
- `AgentOS.company_manager` and `AgentOS.product_manager` are removed. Use
  `AgentOS.manager` or talk to Super Agent at `/teams/superagent`.
- Routines name team `superagent`: `executor_type="team", executor_id="superagent"`.
- `OSManager.tool_call_limit` defaults to 24 and `num_history_runs` to 5.

Before upgrading, audit existing components, sessions and authorization grants for the newly reserved names. Rename custom components and migrate their references; do not let a grant intended for a custom component authorize a built-in manager. Catalog collisions fail at startup, but external token scopes and custom policy stores require an operator audit.

Drain queued or paused manager runs before upgrading. Mixed pre-3.2 and 3.2 servers sharing manager state are unsupported; do not roll back without restoring or migrating the corresponding state and policies. Updating template code does not rewrite already-saved Routine endpoints.
