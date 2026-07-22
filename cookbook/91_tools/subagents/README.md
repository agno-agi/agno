# SubAgent

Let an agent spin up subagents (copies of itself) to get tasks done in parallel.

The toolkit exposes one tool, `run_task(task)`: it runs the task on a subagent and
returns the result. The main agent parallelizes by calling `run_task` multiple times
in the same response.

Subagents inherit the main agent's **model**, **tools** and **db** by default. Any of
these can be overridden in the `SubAgent` constructor. Subagents cannot spawn subagents
of their own.

Each `run_task` call runs in its own `<parent id>-subagent-task-<uuid>` session with
`user_id` set to the main agent's id, so subagent runs show up as separate live
sessions in the db / AgentOS UI.

When a db is set, subagent runs execute as detached background runs on the server —
the same pipeline as the AgentOS "Run in background" toggle — so a page refresh never
kills them. The main agent's run is controlled by the toggle itself: turn it on so
the orchestrator also survives refreshes and can collect the subagent results.

Subagent events are also streamed back into the main agent's run tagged with
`parent_run_id`, so each `run_task` call renders as nested sub-agent activity inside
the main chat in the AgentOS UI (the same treatment as team member delegation and
context-provider sub-agents) — in addition to the separate per-task session.

## Cookbooks

| File | Description |
|------|-------------|
| `subagents_os.py` | AgentOS app: Claude Sonnet 5 orchestrator with Claude Haiku subagents |
| `coding_agent_os.py` | AgentOS coding orchestrator: Sonnet 5 plans and integrates, Haiku subagents build frontend/backend/database/scripts in parallel in a shared `tmp/projects` workspace |

## Quick Start

```python
from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.tools.subagents import SubAgent

agent = Agent(
    model=Claude(id="claude-sonnet-5"),
    tools=[SubAgent(model=Claude(id="claude-haiku-4-5"))],
)
```

## Setup

```bash
export ANTHROPIC_API_KEY=<your-api-key>
```
