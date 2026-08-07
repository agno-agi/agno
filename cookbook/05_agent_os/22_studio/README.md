# Studio

`StudioTools` is the typed, authorization-gated control plane for composing
persisted Agents, Teams, and Workflows from an AgentOS `Registry`.
`StudioRunnerTools` is the data plane that dispatches those components. This
lesson keeps composition, lifecycle management, dispatch, human-in-the-loop
control, and the Registry/Components HTTP contracts distinct.

## Files

| File | What it teaches |
|---|---|
| `standalone_studio_agent.py` | Create, inspect, edit, and publish a versioned Agent without starting AgentOS. |
| `studio_tools_agent.py` | Serve an authorized Studio Agent beside code-defined Agents and create a typed component over HTTP. |
| `studio_hitl_agent.py` | Resolve structured feedback, free-text input, and confirmation pauses in a console process. |
| `studio_hitl_agent_os.py` | Resolve the same pauses through AgentOS run and continuation endpoints. |
| `registry_and_components.py` | Inspect the separate Registry and persisted Components HTTP contracts. |
| `studio_runner_dispatcher.py` | Dispatch Studio-built components from a runner-only Agent with `StudioRunnerTools`. |
| `studio_runner_direct.py` | Call runner tools directly and observe the registry guard's refusal. |

## Prerequisites

Set up the cookbook environment and provider keys:

```bash
./scripts/demo_setup.sh
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
```

All examples use synchronous `SqliteDb` databases under `22_studio/tmp/`.
`StudioTools` receives one catalog `db` at construction, and every create,
read, lifecycle, and dispatch operation uses that same database. A request
cannot select a different database.

Studio persistence and the `/components` router require a synchronous
`BaseDb`. If AgentOS receives an async database, it exposes a disabled
`/components` surface instead. `GET /registry` is independent of component
persistence and only requires `AgentOS(registry=...)`.

## The typed StudioTools contract

### Fix the catalog and authorize every call

`StudioTools` is an administrative surface. Its constructor requires an
explicit authorization callback in addition to the Registry and fixed catalog
database:

```python
from agno.run import RunContext
from agno.tools.studio import StudioAccess, StudioAction, StudioTools
from agno.tools.studio_schema import ModelRef


def authorize_studio_admin(
    run_context: RunContext,
    _access: StudioAccess,
    _action: StudioAction,
) -> bool:
    return run_context.user_id == "studio-admin"


studio_tools = StudioTools(
    registry=registry,
    db=db,
    authorize=authorize_studio_admin,
    default_model=ModelRef(
        id="gpt-5.5",
        provider="OpenAI",
        name="OpenAIResponses",
    ),
)
```

AgentOS injects its framework-managed `RunContext` into every model-initiated
tool call. Calls fail closed if that context is missing, the callback rejects
the action, or the callback raises. A direct Python caller must supply a real
`RunContext` to the `_agno_run_context` parameter; do not treat model-supplied
user or tenant fields as authorization evidence.

### Discover exact references, then compose typed requests

Call `list_models`, `list_tools`, and `list_functions`, then copy their exact
typed references. `ModelRef` identifies a registered model. `ToolRef`
distinguishes a whole toolkit from one function in a toolkit.

The create tools each accept one declarative request object:

```python
from agno.tools.studio_schema import (
    AgentCreate,
    AgentWorkflowStep,
    ComponentRef,
    FunctionWorkflowStep,
    ModelRef,
    TeamCreate,
    ToolRef,
    WorkflowCreate,
)

researcher = AgentCreate(
    component_id="researcher",
    name="Researcher",
    instructions="Research the topic and cite sources.",
    model=ModelRef(
        id="gpt-5.5",
        provider="OpenAI",
        name="OpenAIResponses",
    ),
    tools=[ToolRef(kind="toolkit", name="calculator")],
)

editors = TeamCreate(
    component_id="editors",
    name="Editors",
    instructions="Review the research before publication.",
    members=[
        ComponentRef(
            component_type="agent",
            component_id="researcher",
            version=1,
        )
    ],
)

editorial_flow = WorkflowCreate(
    component_id="editorial-flow",
    name="Editorial flow",
    steps=[
        AgentWorkflowStep(
            kind="agent",
            step_id="research",
            name="Research",
            component_id="researcher",
            version=1,
        ),
        FunctionWorkflowStep(
            kind="function",
            step_id="publish",
            name="Publish",
            function_name="publish_copy",
        ),
    ],
)
```

`AgentCreate`, `TeamCreate`, and `WorkflowCreate` reject unknown fields rather
than silently ignoring misspellings. Team members are typed `ComponentRef`
values, and workflow steps use a discriminated `kind`. A draft may explore a
code-defined component, but a published Team or Workflow must point to stored,
published component versions.

`component_id` is the stable control-plane identity. Studio derives a
deterministic slug from `name` when it is omitted and never invents a suffixed
id on collision. Creates reject an existing id by default; set
`request.if_exists="return_existing"` only for an idempotent retry whose
normalized request, component type, and requested stage are identical. This is
operation policy and is not persisted as component configuration.

### Use the draft-first, CAS-guarded lifecycle

Creates save a draft unless `save_as="published"` is explicit. The normal
reviewable lifecycle is:

1. `create_agent(request)` creates draft v1. Team and Workflow creation follow
   the same pattern.
2. `publish_component(component_id, version=1,
   expected_current_version=None)` publishes the draft and makes it current.
3. `edit_agent(component_id, patch, expected_version=1)` appends draft v2.
   Edits use typed `AgentPatch`, `TeamPatch`, or `WorkflowPatch` objects.
4. `publish_component(component_id, version=2,
   expected_current_version=1)` publishes the reviewed edit.
5. `set_current_version(component_id, version=1,
   expected_current_version=2)` rolls back by making an older immutable
   published version current.

The `expected_version`, `expected_current_version`, and
`expected_latest_version` arguments are compare-and-swap guards. On a conflict,
read the latest state and retry only after deciding that the change is still
correct.

When StudioTools is mounted on an Agent, create and edit calls require framework
confirmation even when they save a draft, because the same tools can publish
through `save_as`. Publication, rollback, draft deletion, archive, and restore calls are
confirmation-gated too. The Agent pauses before the exact tool execution;
inspect its arguments, confirm or reject it, and continue the same run. Direct
Python method calls are trusted administrative calls and must enforce an
equivalent approval boundary in their host application.

Whole components are retired with the type-specific `archive_agent`,
`archive_team`, or `archive_workflow` call and an
`expected_current_version` guard. Archive is dependency-safe and does not hard
delete the component or release its id for a fresh create. Restore an archived
component with the matching `restore_agent`, `restore_team`, or
`restore_workflow` call and the same current-version guard. Restore changes
catalog visibility only; schedules remain a separate explicit policy surface.
`delete_version` is narrower: it removes one
unreferenced draft using `expected_latest_version`; it does not delete a
published version or an entire component.

All component control-plane and schedule operations return a typed
`StudioResult`. Check `ok`, `status`, and either `data` or `error`; do not parse
display strings as an API contract. Only the `run_*` data-plane tools retain
their JSON string contracts.

## Run standalone composition

The standalone example uses `claude-sonnet-4-6` as the Studio Agent and carries
out a published-v1 to draft-v2 to published-v2 lifecycle:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/standalone_studio_agent.py
```

The example's authorizer permits only its explicit demo admin user, and the run
supplies that user identity so the Agent runtime can inject it into the tool's
`RunContext`. It explicitly confirms the paused create, publish, edit, and
second publish executions before checking the final database state.

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
The HTTP Studio examples enable AgentOS authorization and mint a short-lived,
audience-bound development JWT for their `--demo` clients. The verified token
subject becomes the `RunContext.user_id`; the clients never submit an actor id
as form data. Set `JWT_VERIFICATION_KEY` to use your own local signing key. In
production, replace the development issuer with your normal identity provider.

Passing `agents_list` to `StudioTools` makes those code-defined Agents available
to Team and Workflow composition and auto-enables their operations. A
Studio-created component is persisted in the fixed catalog; it is not appended
to the code-defined Agent list.

## Run the dispatcher

`StudioRunnerTools` is the dispatch half of the Studio: it lists components in
the platform database and runs one by id, without exposing lifecycle mutation
tools. Mount it on a router or team lead that should hand work to built
components without holding Studio administration authority. Runs execute as
the current user, keep one session per component per conversation, pin
`stream=False`, and relay PAUSED results with their requirements.

Mount it instead of `StudioTools`, not alongside it. The two share component
list and run tool names, and the toolkit listed first wins duplicate names
while the other is skipped with a warning.

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_runner_dispatcher.py
```

The direct example calls the same tools as plain methods and shows the registry
guard: a runner constructed without the Registry refuses components whose
stored configs reference registry-backed resources, because rebuilding them
would silently drop those resources.

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/studio_runner_direct.py
```

## Console versus AgentOS HITL

The pause/resume mechanics used here (`RunRequirement`, `continue_run`, and the
`/continue` route) are taught in
[`../05_human_in_the_loop/`](../05_human_in_the_loop/); this folder only
applies them to Studio composition.

Both HITL examples deliberately start with an underspecified component. The
Studio Agent must:

1. ask a structured, multi-select tool question;
2. request free-text Agent instructions;
3. pause for confirmation on the exact typed `create_agent` call.

`StudioTools` marks `create_agent` for confirmation automatically; the examples
do not need to add it to `requires_confirmation_tools`.

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

Run its live client:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/22_studio/registry_and_components.py --demo
```

The two HTTP surfaces have different ownership:

- `GET /registry` describes live, code-defined tools, models, databases,
  schemas, functions, and reusable components. It is read-only and supports
  `resource_type`, partial `name`, `page`, and `limit` filters.
- `/components` exposes persisted component metadata and configuration records
  to platform clients. It is lower-level than the model-facing StudioTools
  lifecycle.

Studio-owned records have a single lifecycle writer. They remain readable
through `/components`, but generic create-config, publish, rollback, delete,
metadata-edit, and archive requests return a conflict for those records. Use
the typed StudioTools lifecycle instead; generic clients cannot claim Studio
ownership by supplying the reserved `_agno_studio` manifest key.

For Studio administration, use the typed, authorized lifecycle described
above: drafts, CAS-guarded publication and rollback, dependency-safe
archive/restore, and draft-only `delete_version`.
