# Studio Cookbook

Examples for composing AgentOS agents, teams, and workflows with `StudioTool`.

## Files
- `standalone_studio_agent.py` — Runs a local agent with `StudioTool` and SQLite persistence, without starting AgentOS.
- `studio_tools_agent.py` — Starts an AgentOS app with code-defined agents, registry primitives, and a Studio agent that can create/edit/version components.
- `studio_hitl_agent.py` — Human-in-the-loop studio on the console: the agent pauses with a structured multi-select question for tool choice (`UserFeedbackTools`), asks for free-text instructions (`UserControlFlowTools`), and `create_agent` requires explicit user confirmation before anything is persisted.
- `studio_hitl_agent_os.py` — The same HITL studio agent served through AgentOS: pauses surface through the AgentOS API/chat UI, which collects the answers and continues the run.

## Versioning

Versioning tools (`list_versions`, `get_version`, `publish_component`, `set_current_version`, `delete_version`) are opt-in: pass `versions=True` to `StudioTool`. With versioning enabled, edits are saved as drafts that need `publish_component`; without it (the default), edits are published immediately as the new current version.

## Prerequisites
- Load environment variables with `direnv allow` (requires `.envrc`).
- Run examples with `.venvs/demo/bin/python <path-to-file>.py`.
- The examples create their SQLite files under `cookbook/05_agent_os/studio/tmp/`.

## Studio UI

Run the AgentOS example:

```bash
.venvs/demo/bin/python cookbook/05_agent_os/studio/studio_tools_agent.py
```

Open the Studio frontend and connect it to the local AgentOS server on port `7777`.

Useful Studio routes:
- Registry primitives: `/studio/registry`
- Agents: `/studio/agents/edit?agent_id=<component_id>`
- Teams: `/studio/teams/edit?team_id=<component_id>`
- Workflows: `/studio/workflows/edit?workflow_id=<component_id>`

## Expected StudioTool Output

When the Studio agent creates or edits a component, the user-facing response should include:
- `component_type`
- `component_id`
- `name`
- `db_version` for creates, or `draft_version` for edits
- the next action, such as publishing a draft
- the Studio route for that component

Do not include a component link when the tool returns an error. Registry primitives live on `/studio/registry`; persisted components should link directly to their edit route.

