# Studio

`StudioTools` lets an Agent compose persisted Agents, Teams, and Workflows from
the live objects in an AgentOS `Registry`, and `StudioRunnerTools` dispatches
what was built. This lesson separates five concerns: standalone composition,
composition served by AgentOS, human-in-the-loop control, dispatch, and the
Registry/Components HTTP contracts.

## Files

| File | What it teaches |
|---|---|
| `standalone_studio_agent.py` | Walk the full lifecycle ladder (create a draft, validate, preview, publish, edit, publish) without starting AgentOS, plus direct-Python workflow composition with a compound loop step. |
| `studio_tools_agent.py` | Serve a Studio Agent beside code-defined Agents and create a published component over HTTP as an owning user. |
| `studio_hitl_agent.py` | Resolve structured feedback, free-text input, and confirmation pauses in a console process. |
| `studio_hitl_agent_os.py` | Resolve the same pauses through AgentOS run and continuation endpoints. |
| `registry_and_components.py` | Read `GET /registry` and complete a component lifecycle over the Components API: draft, guarded append, publish, archive, restore. |
| `studio_runner_dispatcher.py` | Dispatch Studio-built components from a runner-only Agent with `StudioRunnerTools`. |
| `studio_runner_direct.py` | Call the runner's list/run tools directly and observe the registry guard's refusal. |
| `registry_learning.py` | Declare `LearningMachine`s on the Registry, discover them with `list_learning`, wire a built agent with `learning_name`, and rehydrate it with the shared machine. |

## Prerequisites

Set up the cookbook environment and provider keys:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
```

All examples use synchronous `SqliteDb` databases under `22_studio/tmp/`.
StudioTools persistence and the `/components` router require a synchronous
`BaseDb`. If AgentOS receives an async database, it exposes a disabled
`/components` surface instead. `GET /registry` is independent of component
persistence and only requires `AgentOS(registry=...)`.

## The component lifecycle

Every `create_*` writes version 1 as a **draft** unless `publish=True`, or
unless the toolkit was built with `versions=False`, which publishes every
write. A draft is readable, editable, and previewable, but never serves users,
schedules, or dispatch until published. The full ladder:

1. `create_agent` / `create_team` / `create_workflow` — draft version 1
2. `validate_component` — dry-run the stored config against the live registry,
   exactly as dispatch would rebuild it
3. `run_agent(version=1)` — preview the draft as a real, recorded run
4. `publish_component` — promote the draft and point the live version at it
5. `run_agent` — the published version now serves everyone

`edit_*` appends a new immutable draft version (or a published one with
`publish=True`), renames in place with `name=` (the id never changes), and
takes `expected_version` as an optional compare-and-set guard against
concurrent edits. `set_current_version` re-points among published versions;
`archive_component` retires a component (id reserved, history kept, dependents
refuse) and `restore_component` reverses it; only unpublished drafts can be
deleted with `delete_version`.

The control-plane tools return one `StudioResult` JSON envelope:
`{ok, status, data, error: {code, message, details, retryable}, warnings}`.
Drivers branch on `error.code` (stable, machine-readable), never on message
text.

The run tools are the deliberate exception, because a run result is the
component's output rather than a control-plane response. `run_agent`,
`run_team`, and `run_workflow` return the runner's flat payload:
`{agent_id | team_id | workflow_id, run_id, session_id, status, content}`,
which StudioTools also aliases onto `id`, with `status` one of `COMPLETED`,
`ERROR`, or `PAUSED`, plus `requirements` on a paused run and `media` counts
when the run produced artifacts. An id that does not resolve comes back as a
flat `{"error": "<message>"}` — that `error` is a prose string, not an object,
so it carries no `code`.

`run_*(version=N)` answers in both shapes. The preview gate refuses in the
envelope (`component_not_found`, `version_not_found`, `validation_failed`),
while a preview it admits runs and returns the flat payload. A driver reads
`ok` when the key is present and falls back to the flat `status` and `error`
string when it is not.

The schedule tools mounted from `SchedulerTools` when `schedules=True`
(`list_schedules`, `get_schedule`, `get_schedule_runs`, `trigger_schedule`,
`enable_schedule`, `disable_schedule`, `delete_schedule`) return the
scheduler's flat payloads for the same reason, error included. Studio's own
`create_schedule` and `update_schedule` are control-plane tools and return
envelopes.

Changes from the 2.x flat API: `delete_agent/team/workflow` are replaced by
`archive_component` + `restore_component` (exact id required);
`get_agent/team/workflow` and `list_agents/teams/workflows` are merged into
`get_component` + `list_components`; `get_version` is `get_component(version=N)`;
`list_dbs` is gone — one catalog database is bound at construction and there is
no per-call `db_id`.

## Versioning and confirmation defaults

`versions=True` is now the default: constructing
`StudioTools(registry=..., db=...)` gives the full lifecycle (drafts,
`list_versions`, `publish_component`, `set_current_version`, `delete_version`).
Set `versions=False` to publish every edit immediately and hide the version
tools.

`requires_confirmation_tools` defaults to the deletion-shaped operations
(`archive_component`, `delete_version`, `delete_schedule`). Passing your own
list replaces the default — the HITL lessons pass
`requires_confirmation_tools=["create_agent"]` so creation itself pauses for
approval, and `[]` clears confirmation entirely.

## Identity and ownership

The framework injects the caller's `RunContext` into every StudioTools call.
Components (and schedules) created under a `user_id` are owned by that user.
While a component is draft-only, other scoped users get `component_not_found`
for it; publishing puts it on the platform, where every user can read and run
it. Editing, archiving, and version writes stay owner-scoped throughout
(`not_owner` for other users), and schedules are never shared on publish.
Calls without a run context (direct Python, tests) write unowned, shared
rows. The AgentOS demos pass `user_id` on the run request to show this.

## Learning

Learning is the only memory surface a Studio-built component can be given, and
the deployer decides what learning exists. Declare `LearningMachine`s by name
on the `Registry` (`Registry(learning=[LearningMachine(name="shared-brain",
...)])` or `registry.add_learning(...)`); the builder discovers them with
`list_learning` and wires one with `learning_name` on `create_agent`,
`edit_agent`, `create_team` and `edit_team` (`""` detaches). The stored config
carries `{"name": ...}`, never the machine's config, so a component cannot
author learning the deployer did not declare; an undeclared name returns
`learning_not_found`.

Without a declared machine, `enable_learning=True` is the zero-config path: the
config carries `learning: True` and the framework builds the default machine
(user profile and user memory on the component's own db and model) at init.
On a component already wired to a machine, `enable_learning=True` keeps that
machine and says so in `warnings`; `learning_name=""` in the same call drops
the reference first, so the pair switches it to the default machine.
`enable_learning=False` turns learning off whatever shape it had, and a
non-empty `learning_name` takes precedence when both are given. The legacy
memory pair is cleared whenever the call ends with learning wired.

Every component wired to a machine reads and writes that machine's namespace,
so `list_learning` shows the namespace (machine-level and per store) first,
plus each store's mode and whether the machine already binds a `model`, `db`
or `knowledge`. A registry machine is one shared instance: the framework
injects a component's db and model into it only when it has none, so the first
component to run binds them, permanently, for every sharer — declare `db` and
`model` on the machine if the deployer, not the first component, should decide.
`create_*` / `edit_*` return that as `warnings` in the success envelope when the
machine you wire declares no db or model, or is bound to a different db than
the component. Namespaces are literal strings; there is no per-component
templating of a learning namespace.

A named machine on a code-defined Agent or Team is folded into the Registry the
way its knowledge is, so the stored reference resolves and `list_learning`
shows it; `GET /registry` lists declared machines under `type: learning` with
the same summary. Two distinct machines under one name are refused at wiring
time (`ambiguous_reference`).

The legacy `memory_manager_id` / `enable_agentic_memory` pair is gone from the
Studio forms. Wiring `learning_name` onto a component stored with them clears
both, and `get_component` still shows `enable_agentic_memory` on a component
that carries it, so the real state stays visible.

Upgrade note (3.0.0a3): `learned_knowledge` enabled by a bool or by a bound
knowledge now follows the machine's `namespace`, the way `entity_memory`
already did. A deployment that ran `LearningMachine(namespace="team_west",
knowledge=kb)` on 2.8.4 through 3.0.0a2 saved its learnings under `global`;
recall filters on the exact namespace, so those rows are not returned until
their namespace is updated to `team_west` (or the machine is left on the
default namespace).

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_learning.py
```

## Palette policy

The build palette is enforced, not prompted. Tools declared on the `Registry`
are buildable; tools that arrived via the AgentOS fold (every registered
agent's own wiring) are resolvable for rebuilds but **not** buildable unless
allowed with `allowed_tools=[...]`; `denied_tools` always wins; composing a
component that itself carries `StudioTools` is refused the same way.
`list_tools` reports `buildable` and `source` (`declared` or `folded`) per
row, and wiring a non-buildable name returns `tool_not_allowed` (distinct from
`tool_not_found`).

## Run standalone composition

The standalone example uses `claude-sonnet-4-6` as the Studio Agent and walks
the whole ladder, then composes a workflow (including a compound `loop` step)
by calling the toolkit directly from Python:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/standalone_studio_agent.py
```

## Run the AgentOS Studio Agent

Start the server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_tools_agent.py
```

Then run its repeatable HTTP client from another terminal:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_tools_agent.py --demo
```

Each server defaults to port 7777. Set `PORT` for the server and
`AGENT_OS_BASE_URL` for its client when that port is already occupied.

Passing `include_agents` to `StudioTools` makes those code-defined Agents available
to Team and Workflow composition and auto-enables their operations. A
Studio-created component is persisted in the database; it is not appended to
the code-defined Agent list.

## Run the dispatcher

`StudioRunnerTools` is the dispatch half of the Studio: it lists the components
in the platform database and runs one by id, with no create/edit/archive
surface. Mount it on a router or team lead that should hand work to built
components without holding the Studio's mutation tools. Runs execute as the
current user, keep one session per component per conversation, pin
`stream=False`, and relay PAUSED results with their requirements. Dispatch
resolves only the current published version: a draft-only component answers
not-found until it is published.

Mount it instead of `StudioTools`, not alongside it. The two share the run
tool names (`run_agent`, plus `run_team` and `run_workflow` once teams or
workflows are enabled), and the tool namespace is flat, so the toolkit listed
first wins those names and the other is skipped with a warning.

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_runner_dispatcher.py
```

The direct example calls the same tools as plain methods and shows the
registry guard: a runner constructed without the registry refuses components
whose stored configs reference registry-backed resources (tools, knowledge,
code-defined members), because the rebuild would silently drop them.

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_runner_direct.py
```

## Console versus AgentOS HITL

The pause/resume mechanics used here (`RunRequirement`, `continue_run`, the
`/continue` route) are taught in
[`../05_human_in_the_loop/`](../05_human_in_the_loop/); this folder only
applies them to Studio composition.

Both HITL examples deliberately start with only a component name. The Studio
Agent must:

1. ask a structured, multi-select tool question;
2. request free-text Agent instructions;
3. pause for confirmation on the exact `create_agent` call.

The console lesson resolves live `RunRequirement` objects and calls
`Agent.continue_run()`:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_hitl_agent.py
```

Use the deterministic answers used by the test log:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_hitl_agent.py --auto
```

The AgentOS lesson serializes paused executions in the run's `tools` array.
Start it, then run the client in another terminal:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_hitl_agent_os.py
```

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_hitl_agent_os.py --demo
```

The client fills `selected_options` or user-input `value`, sets `answered`, and
finally sets `confirmed=true` before sending the updated tools to
`POST /agents/{agent_id}/runs/{run_id}/continue`. In both lessons the confirmed
create writes a draft that `publish_component` would make live.

## Registry and Components APIs

Start the catalog server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_and_components.py
```

Run its live lifecycle client:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_and_components.py --demo
```

The two surfaces have different ownership:

- `GET /registry` describes live, code-defined tools, models, databases,
  schemas, functions, learning machines, and reusable components. It is read-only and supports
  `resource_type`, partial `name`, `page`, and `limit` filters.
- `/components` owns persisted component metadata and versioned configuration.
  The demo executes `POST /components` (a draft), a refused
  `POST /agents/{id}/runs` (drafts are not dispatchable until published), a
  guarded `POST /components/{id}/configs` append, a publish via
  `PATCH /components/{id}/configs/{version}`, `PATCH /components/{id}`,
  `DELETE /components/{id}` (an archive), and
  `POST /components/{id}/restore`.

Every mutating `/components` body accepts an optional
`guard: {latest_version, current_version}`; when present the write is
compare-and-set (409 on conflict), when absent it stays last-writer-wins.
Published configs are immutable; draft configs can be edited or deleted, and
only a published version can become current. The run routes accept an optional
`version` form field that previews an exact version — drafts included — gated
to the component's owner or an admin.
