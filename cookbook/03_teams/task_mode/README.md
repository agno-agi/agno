# Task Mode for Teams

Task mode (`mode=TeamMode.tasks`) enables autonomous task-based execution where the team leader:

1. **Decomposes** a user's goal into discrete tasks
2. **Assigns** tasks to the most capable member agents
3. **Executes** tasks with proper dependency ordering
4. **Runs tasks in parallel** when they are independent
5. **Synthesizes** results into a final response

## Quick Start

```bash
.venvs/demo/bin/python cookbook/03_teams/task_mode/01_basic_task_mode.py
```

## Examples

| File | Description |
|------|-------------|
| `01_basic_task_mode.py` | Basic task decomposition with research, writing, and review |
| `02_parallel_tasks.py` | Parallel execution of independent analysis tasks |
| `03_task_mode_with_tools.py` | Task mode with tool-equipped agents (web search) |
| `04_async_task_mode.py` | Async task mode using `arun()` |
| `05_dependency_chain.py` | Complex dependency chains in a product launch pipeline |
| `06_custom_tools.py` | Agents with custom Python function tools (financial calculators) |
| `07_multi_run_session.py` | Multi-run session persistence across sequential requests |

## Key Concepts

### Creating a Task-Mode Team

```python
from agno.team.team import Team
from agno.team.mode import TeamMode

team = Team(
    name="My Team",
    mode=TeamMode.tasks,
    model=OpenAIChat(id="gpt-4o"),
    members=[agent1, agent2],
    max_iterations=10,  # max task loop iterations
)
```

### Available Tools (auto-provided to team leader)

- `create_task` - Create a new task with title, description, assignee, and dependencies
- `execute_task` - Execute a single task by delegating to a member agent
- `execute_tasks_parallel` - Execute multiple independent tasks concurrently
- `update_task_status` - Manually update a task's status
- `list_tasks` - View all tasks and their current status
- `add_task_note` - Add notes to a task
- `mark_all_complete` - Signal that the overall goal is achieved

### Task Dependencies

Tasks can declare dependencies using `depends_on` (list of task IDs). A task with unresolved dependencies is automatically marked as `blocked` and cannot be executed until all dependencies are completed.

### Parallel Execution

When tasks are independent (no dependencies on each other), the team leader can use `execute_tasks_parallel` to run them concurrently, significantly reducing total execution time.
