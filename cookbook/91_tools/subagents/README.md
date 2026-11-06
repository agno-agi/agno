# Subagents

Let an agent spin up subagents (restricted copies of itself) to get tasks done in
parallel.

Set `Agent(enable_subagents=True)` for the defaults, or attach a `SubagentsConfig` via
`Agent(subagents_config=...)` to control the options. The agent then gets one tool,
`spawn_agent(task, model=None, tools=None)`: it runs the task on a subagent and
returns the result. The main agent parallelizes by calling `spawn_agent` multiple
times in the same response.

The model controls each spawn from the allowed options declared on the config:

- **model** — named model options (`models={"fast": ..., "deep": ...}`); the model
  picks the option per task, the first entry is the default. A value can also be a
  `(Model, "when to use it")` tuple - the description is shown next to the option
  name in the spawn_agent tool description. A single model
  (`model=OpenAIResponses(id="gpt-5.6-luna")`) runs every subagent on it. Omitting
  both inherits the main agent's model.
- **tools** — the allowed tools (defaults to the main agent's tools); the model may
  restrict a spawn to a subset by name (a pure research spawn only needs websearch).

Subagents run **in-process inside the parent's run and session**, the same way team
members run inside a team's session. Their events stream nested into the parent's chat
tagged with `parent_run_id` (the same rendering as team member delegation and
context-provider sub-agents), and the tool result is the subagent's answer. Subagent
runs are **ephemeral**: they are never written to the database, and subagents cannot
spawn subagents of their own.

## Cookbooks

| File | Description |
|------|-------------|
| `subagents_enabled.py` | The one-liner: `Agent(enable_subagents=True)` - default config, subagents inherit the agent's model and tools |
| `subagents_defaults.py` | Minimal config: `SubagentsConfig()` with no options - same defaults, ready to grow options |
| `subagents_single_model.py` | Single model: `SubagentsConfig(model=OpenAIResponses(id="gpt-5.6-luna"))` - the orchestrator thinks on GPT-5.6 Terra, every subagent runs on Luna |
| `subagents_os.py` | AgentOS app: GPT-5.6 Terra research orchestrator picking "fast" (Luna) or "deep" (Terra) subagents per topic |
| `coding_agent_os.py` | AgentOS coding orchestrator with an explicit allowed toolset: subagents get websearch + website + coding tools, while artifact generation and workspace move/delete stay with the orchestrator |
| `subagents_combined_os.py` | One AgentOS app serving all four configuration styles side by side |

## Quick Start

```python
from agno.agent import Agent
from agno.models.openai import OpenAIResponses
from agno.subagent import SubagentsConfig

# The one-liner: subagents inherit this agent's model and tools
agent = Agent(model=OpenAIResponses(id="gpt-5.6-terra"), enable_subagents=True)

# Full control: named model options and allowed tools
agent = Agent(
    model=OpenAIResponses(id="gpt-5.6-terra"),
    subagents_config=SubagentsConfig(
        models={
            "fast": OpenAIResponses(id="gpt-5.6-luna"),
            "deep": OpenAIResponses(id="gpt-5.6-terra"),
        }
    ),
)
```

## Setup

```bash
export OPENAI_API_KEY=<your-api-key>
```
