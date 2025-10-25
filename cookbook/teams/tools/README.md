# Team Tools

Teams with custom tools and tool coordination for enhanced functionality.

## Setup

```bash
pip install agno openai
```

Set your OpenAI API key:
```bash
export OPENAI_API_KEY=xxx
```

## Basic Integration

Teams can use custom tools and coordinate tool usage across members:

```python
from agno.team import Team
from agno.tools import tool

@tool()
def custom_search(query: str) -> str:
    """Custom search function"""
    return f"Results for: {query}"

team = Team(
    members=[agent1, agent2],
    tools=[custom_search],
)
```

## Examples

- **[01_team_with_custom_tools.py](./01_team_with_custom_tools.py)** - Teams with custom tool functions
- **[02_team_with_tool_hooks.py](./02_team_with_tool_hooks.py)** - Tool execution hooks and callbacks
- **[03_async_team_with_tools.py](./03_async_team_with_tools.py)** - Asynchronous teams with tools
- **[04_tool_hooks_for_members.py](./04_tool_hooks_for_members.py)** - User permissions for member delegation
