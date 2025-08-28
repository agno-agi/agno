# Team Dependencies

Team dependency management for injecting context and runtime dependencies.

## Setup

```bash
pip install agno openai
```

Set your OpenAI API key:
```bash
export OPENAI_API_KEY=xxx
```

## Basic Integration

Teams can use dependencies to inject context and functions:

```python
from agno.team import Team

def get_user_context(user_id: str) -> dict:
    return {"name": "John", "role": "Developer"}

team = Team(
    members=[agent1, agent2],
    dependencies=[get_user_context],
)

# Dependencies are available to all team members
team.print_response("What can you tell me about the user?")
```

## Examples

- **[add_dependencies_run.py](./add_dependencies_run.py)** - Runtime dependency injection
- **[add_dependencies_to_context.py](./add_dependencies_to_context.py)** - Context-aware dependencies
