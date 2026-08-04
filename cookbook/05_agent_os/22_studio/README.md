# Studio

`StudioTools` lets an Agent compose persisted Agents, Teams, and Workflows from
the live objects in an AgentOS `Registry`. This lesson separates four concerns:
standalone composition, composition served by AgentOS, human-in-the-loop
control, and the Registry/Components HTTP contracts.

## Files

| File | What it teaches |
|---|---|
| `standalone_studio_agent.py` | Create, edit, inspect, and publish a versioned Agent without starting AgentOS. |
| `studio_tools_agent.py` | Serve a Studio Agent beside code-defined Agents and create a component over HTTP. |
| `studio_hitl_agent.py` | Resolve structured feedback, free-text input, and confirmation pauses in a console process. |
| `studio_hitl_agent_os.py` | Resolve the same pauses through AgentOS run and continuation endpoints. |
| `registry_and_components.py` | Read `GET /registry` and complete a persisted component CRUD lifecycle. |

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

## Run standalone composition

The standalone example uses `claude-sonnet-4-6` as the Studio Agent and carries
out a full published-v1 to draft-v2 to published-v2 lifecycle:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/standalone_studio_agent.py
```

`versions=True` is opt-in. With it, `edit_agent`, `edit_team`, and
`edit_workflow` write a draft that `publish_component` must promote. Without
versioning, edits publish a new current version immediately.

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

Passing `agents_list` to `StudioTools` makes those code-defined Agents available
to Team and Workflow composition and auto-enables their operations. A
Studio-created component is persisted in the database; it is not appended to
the code-defined Agent list.

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
`POST /agents/{agent_id}/runs/{run_id}/continue`.

## Registry and Components APIs

Start the catalog server:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_and_components.py
```

Run its live CRUD client:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_and_components.py --demo
```

The two surfaces have different ownership:

- `GET /registry` describes live, code-defined tools, models, databases,
  schemas, functions, and reusable components. It is read-only and supports
  `resource_type`, partial `name`, `page`, and `limit` filters.
- `/components` owns persisted component metadata and versioned configuration.
  The example executes `POST /components`, filtered `GET /components`,
  `GET /components/{id}`, `PATCH /components/{id}`,
  `GET /components/{id}/configs/current`, and `DELETE /components/{id}`.

The Components API also provides config-version create, read, update, delete,
and set-current routes. Published configs are immutable; draft configs can be
updated or deleted, and only a published version can become current.
