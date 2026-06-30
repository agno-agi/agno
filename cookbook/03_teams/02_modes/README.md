# Team Modes

Agno teams support four execution modes that control how the team leader coordinates work with member agents.

## Modes at a Glance

| Mode | Enum | Description | Best For |
|------|------|-------------|----------|
| **Coordinate** | `TeamMode.coordinate` | Leader picks members, crafts tasks, synthesizes results | General-purpose orchestration |
| **Route** | `TeamMode.route` | Leader routes to one specialist, returns their response directly | Specialist selection, language routing |
| **Broadcast** | `TeamMode.broadcast` | Leader sends the same task to all members, synthesizes results | Multi-perspective analysis, consensus |
| **Tasks** | `TeamMode.tasks` | Leader decomposes goal into a task list, executes with dependencies | Complex multi-step workflows, parallel execution |

## Usage

```python
from agno.team.mode import TeamMode
from agno.team.team import Team

team = Team(
    name="My Team",
    mode=TeamMode.coordinate,  # or .route, .broadcast, .tasks
    members=[...],
)
```

## Directory Structure

```
modes/
  coordinate/
    01_basic.py              # Basic coordination with two specialists
    02_with_tools.py         # Coordination where members have tools
    03_structured_output.py  # Coordination with structured output schema
  route/
    01_basic.py              # Basic routing to language-specific agents
    02_specialist_router.py  # Routing to domain specialists
    03_with_fallback.py      # Routing with a fallback agent
  broadcast/
    01_basic.py              # Basic broadcast for multi-perspective analysis
    02_debate.py             # Broadcast for structured debate
    03_research_sweep.py     # Broadcast for parallel research across sources
  tasks/
    01_basic.py              # Basic task decomposition and execution
    02_parallel.py           # Parallel task execution
    03_dependencies.py       # Tasks with dependency chains
    04_basic_task_mode.py    # Foundational autonomous task decomposition
    05_parallel_tasks.py     # Parallel execution in a task workflow
    06_task_mode_with_tools.py # Task mode with web-capable members
    07_async_task_mode.py    # Async task execution
    08_dependency_chain.py   # Complex dependency workflow
    09_custom_tools.py       # Task mode with custom function tools
    10_multi_run_session.py  # Session persistence across task runs
```

Advanced task-mode scenarios are now included in `modes/tasks/` (parallel execution, tools, async, and persistence examples).

## Running

```bash
.venvs/demo/bin/python cookbook/03_teams/02_modes/coordinate/01_basic.py
```
